import os
import io
import json
import re
import mimetypes
import asyncio
import secrets
import jwt
import face_recognition
import bcrypt
import time
import cv2
import numpy as np
import requests
import pandas as pd
import httpx
import fastapi
from fastapi import FastAPI, Depends, Response, File, UploadFile, HTTPException, Form, APIRouter, BackgroundTasks, Query, Body
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

from pydantic import ValidationError
from typing import Optional
from zoneinfo import ZoneInfo
from collections import defaultdict

from .database import init_db, get_db
from .models import Student, Exam, Admin, ExamRegistration, AccessLog, Examiner, AdminLog, SessionType, SecureKey
from .schemas import (
    AdminCreateSchema, ExaminerCreateSchema, StudentEnrollSchema,
    ExamUploadValidationSchema, StudentLoginSchema, StudentLoginResponseSchema,
    ChangePasswordSchema, CameraRegisterSchema, StudentProfileSchema,
    StudentSummarySchema, SecureKeyGenerateSchema, UnifiedRegisterSchema
)
from .auth import (
    create_access_token, get_current_user, get_current_examiner, require_admin, require_examiner,
    require_student, require_superadmin, is_superadmin_user, verify_password,
    get_password_hash, validate_secure_key, SECRET_KEY, ALGORITHM
)
from .seed import seed_superadmin
from .stream_esp32 import (
    generate_from_memory, fetch_frames_from_esp32,
    ACTIVE_CAMERAS, CAMERA_TASKS, AI_ROOM_STATES, CAMERA_HEALTH,
    subscribe_room_events, unsubscribe_room_events, emit_room_event
)
from .storage import init_storage, upload_photo_to_cloud, get_photo_from_cloud, BUCKET_NAME
from .mailer import send_welcome_email, send_allocation_email

from starlette.middleware.gzip import GZipMiddleware

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=1000)
templates = Jinja2Templates(directory="app/templates")
timezone = ZoneInfo("Europe/Sofia")

# Речник за активни квесторски назначения по зали (1-Examiner Exclusive Lock)
ACTIVE_EXAMINER_ASSIGNMENTS: dict[str, dict] = {}
EXAMINER_HEARTBEAT_TIMEOUT = 60.0  # секунди валидност на сърцебиенето

def _cleanup_expired_assignments():
    """ Изчиства квесторски назначения с изтекъл heartbeat таймаут """
    now = time.time()
    expired = [
        room for room, data in list(ACTIVE_EXAMINER_ASSIGNMENTS.items())
        if now - data.get("last_heartbeat", 0) > EXAMINER_HEARTBEAT_TIMEOUT
    ]
    for r in expired:
        del ACTIVE_EXAMINER_ASSIGNMENTS[r]


def _parse_admin_log_details(details: Optional[str]) -> dict:
    if not details:
        return {}
    try:
        parsed = json.loads(details)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    return {"raw": details}


def _student_payload(student: Student) -> dict:
    return {
        "id": str(student.id),
        "full_name": student.full_name,
        "student_id_number": student.student_id_number,
        "email": student.email,
        "faculty": student.faculty,
        "specialty": student.specialty,
        "course": student.course,
        "stream": student.stream,
        "group": student.group,
        "status": student.status,
        "is_active": bool(student.is_active),
        "email_sent": bool(student.is_active or (student.hashed_password and student.hashed_password != "LOCKED_UNTIL_EMAIL_SENT")),
        "photo_path": student.photo_path,
        "photo_url": f"/admins/students/{student.id}/photo" if student.photo_path else None,
        "student_book_photo_path": student.student_book_photo_path,
        "student_book_photo_url": f"/admins/students/{student.id}/student-book-photo" if student.student_book_photo_path else None,
        "created_at": student.created_at.isoformat() if student.created_at else None,
    }


def _exam_payload(
    exam: Exam,
    db: Optional[Session] = None,
    precomputed_allocated_counts: Optional[dict] = None,
    precomputed_student_stats: Optional[dict] = None,
) -> dict:
    allocated_count = 0
    eligible_count = 0
    approved_count = 0

    if precomputed_allocated_counts is not None:
        allocated_count = precomputed_allocated_counts.get(exam.id, 0)
    elif db:
        allocated_count = db.query(ExamRegistration).filter(ExamRegistration.exam_id == exam.id).count()
    elif exam.registrations is not None:
        allocated_count = len(exam.registrations)

    if precomputed_student_stats is not None:
        if exam.group:
            allowed_groups = [int(g.strip()) for g in str(exam.group).split(",") if g.strip().isdigit()]
            for g in allowed_groups:
                key = (exam.faculty, exam.specialty, exam.course, str(exam.stream), g)
                stat = precomputed_student_stats.get(key)
                if stat:
                    eligible_count += stat.get("total", 0)
                    approved_count += stat.get("approved", 0)
    elif db and exam.group:
        allowed_groups = [int(g.strip()) for g in str(exam.group).split(",") if g.strip().isdigit()]
        if allowed_groups:
            students_query = db.query(Student.id, Student.status).filter(
                Student.faculty == exam.faculty,
                Student.specialty == exam.specialty,
                Student.course == exam.course,
                Student.stream == exam.stream,
                Student.group.in_(allowed_groups)
            ).all()
            eligible_count = len(students_query)
            approved_count = sum(1 for s in students_query if s.status == "APPROVED")

    return {
        "id": str(exam.id),
        "session_type": exam.session_type.value if exam.session_type else None,
        "subject": exam.subject,
        "lecturer": exam.lecturer,
        "room_number": exam.room_number,
        "date_time": exam.date_time.isoformat() if exam.date_time else None,
        "faculty": exam.faculty,
        "specialty": exam.specialty,
        "course": exam.course,
        "stream": exam.stream,
        "group": exam.group,
        "allocated_count": allocated_count,
        "eligible_count": eligible_count,
        "approved_count": approved_count,
        "pending_bio_count": max(0, eligible_count - approved_count),
    }


def _admin_log_payload(log: AdminLog) -> dict:
    parsed_details = _parse_admin_log_details(log.details)
    return {
        "id": str(log.id),
        "action_type": log.action_type,
        "details": log.details,
        "parsed_details": parsed_details,
        "specialty": log.specialty,
        "group": log.group,
        "notification_sent": log.notification_sent,
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "student_ids": parsed_details.get("student_ids", []),
        "exam_ids": parsed_details.get("exam_ids", []),
    }


def _resolve_log_students(
    db: Session,
    log: AdminLog,
    selected_student_ids: Optional[list[str]] = None,
    preloaded_students_by_spec_group: Optional[dict] = None,
) -> list[Student]:
    parsed_details = _parse_admin_log_details(log.details)
    
    if log.action_type == "STUDENT_IMPORT":
        # ⚡ Безопасно преобразуваме стринга от лога към Integer
        group_int = None
        if log.group:
            try:
                group_int = int(float(log.group))
            except ValueError:
                pass

        if preloaded_students_by_spec_group is not None:
            target_group = group_int if group_int is not None else log.group
            matched = list(preloaded_students_by_spec_group.get((log.specialty, target_group), []))
            if selected_student_ids:
                sel_set = set(selected_student_ids)
                matched = [s for s in matched if str(s.id) in sel_set]
            return sorted(matched, key=lambda s: s.created_at if s.created_at else datetime.min)

        # Филтрираме по специалност
        query = db.query(Student).filter(Student.specialty == log.specialty)
        
        # Ако преобразуването е успешно, филтрираме по група
        if group_int is not None:
            query = query.filter(Student.group == group_int)
        else:
            query = query.filter(Student.group == log.group)

        if selected_student_ids:
            query = query.filter(Student.id.in_(selected_student_ids))
            
        return query.order_by(Student.created_at.asc()).all()

    if log.action_type.startswith("ALLOCATION_EXECUTION"):
        exam_ids = parsed_details.get("exam_ids", [])
        if not exam_ids:
            return []
        query = db.query(Student).join(ExamRegistration, ExamRegistration.student_id == Student.id).filter(
            ExamRegistration.exam_id.in_(exam_ids)
        )
        if selected_student_ids:
            query = query.filter(Student.id.in_(selected_student_ids))
        return query.distinct().order_by(Student.created_at.asc()).all()

    return []


def _resolve_log_exams(
    db: Session,
    log: AdminLog,
    all_exams_list: Optional[list[Exam]] = None,
    exams_by_id_map: Optional[dict] = None,
) -> list[Exam]:
    parsed_details = _parse_admin_log_details(log.details)
    
    if log.action_type == "EXAM_IMPORT":
        start_window = log.created_at - timedelta(seconds=10)
        end_window = log.created_at + timedelta(seconds=10)
        
        if all_exams_list is not None:
            matched = [e for e in all_exams_list if e.created_at and start_window <= e.created_at <= end_window]
            return sorted(matched, key=lambda e: e.date_time if e.date_time else datetime.min)

        return db.query(Exam).filter(
            Exam.created_at >= start_window,
            Exam.created_at <= end_window
        ).order_by(Exam.date_time.asc()).all()
        
    exam_ids = parsed_details.get("exam_ids", [])
    if not exam_ids:
        return []

    if exams_by_id_map is not None:
        matched = [exams_by_id_map[str(eid)] for eid in exam_ids if str(eid) in exams_by_id_map]
        return sorted(matched, key=lambda e: e.date_time if e.date_time else datetime.min)

    return db.query(Exam).filter(Exam.id.in_(exam_ids)).order_by(Exam.date_time.asc()).all()


def _resolve_log_registrations(
    db: Session,
    log: AdminLog,
    preloaded_registrations_by_exam_id: Optional[dict] = None,
) -> list[dict]:
    parsed_details = _parse_admin_log_details(log.details)
    exam_ids = [str(eid) for eid in parsed_details.get("exam_ids", [])]
    if not exam_ids:
        return []

    if preloaded_registrations_by_exam_id is not None:
        results = []
        for eid in exam_ids:
            results.extend(preloaded_registrations_by_exam_id.get(eid, []))
        return results

    registrations = db.query(ExamRegistration).filter(
        ExamRegistration.exam_id.in_(exam_ids)
    ).join(Student, ExamRegistration.student_id == Student.id
    ).join(Exam, ExamRegistration.exam_id == Exam.id
    ).order_by(Exam.date_time.asc(), Student.student_id_number.asc()).all()

    return [
        {
            "id": str(reg.id),
            "student_id": str(reg.student_id),
            "student_name": reg.student.full_name if reg.student else "Неизвестен",
            "student_fac_num": reg.student.student_id_number if reg.student else "-",
            "student_email": reg.student.email if reg.student else "",
            "student_specialty": reg.student.specialty if reg.student else "-",
            "student_group": reg.student.group if reg.student else "-",
            "exam_id": str(reg.exam_id),
            "exam_subject": reg.exam.subject if reg.exam else "Неизвестен",
            "session_type": reg.exam.session_type.value if (reg.exam and reg.exam.session_type) else None,
            "room_number": reg.exam.room_number if reg.exam else "-",
            "date_time": reg.exam.date_time.isoformat() if (reg.exam and reg.exam.date_time) else None,
        }
        for reg in registrations
    ]


def _photo_url_for_student(student: Student) -> Optional[str]:
    if not student.photo_path:
        return None
    return f"/admins/students/{student.id}/photo"

def _student_book_photo_url_for_student(student: Student) -> Optional[str]:
    if not student.student_book_photo_path:
        return None
    return f"/admins/students/{student.id}/student-book-photo"

@app.on_event("startup")
def on_startup():
    init_db()
    init_storage()
    seed_superadmin()

@app.get("/")
def read_root():
    return {"status": "AACAS API is running", "database": "Initialized and Connected"}

@app.post("/admins/upload/students")
async def upload_students_excel(
    faculty: str = Form(...),
    specialty: str = Form(...),
    course: int = Form(...),
    stream: int = Form(...),
    group: int = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_admin)
):
    """
    Sub-ендпоинт за масово импортиране на студенти от Excel файл.
    Автоматично генерира временни пароли и записва събитието в admin_logs.
    """
    admin = db.query(Admin).filter(Admin.id == current_admin['sub']).first()
    if not admin:
        raise HTTPException(status_code=403, detail="Unauthorized access. Admin privileges required.")
    if not admin.is_verified:
        raise HTTPException(status_code=403, detail="Account pending verification. Not authorized to upload students.")

    # 1. Валидация на разширението на файла
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Invalid file format. Please upload an Excel file.")

    try:
        # 2. Прочитане на Excel файла директно от паметта (буфера) без записване на диска
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        # Очаквани колони в Ексел файла (Име, Фамилия, Фак. Номер, Имейл)
        required_columns = ["Име", "Фамилия", "Фак. Номер", "Имейл"]
        for col in required_columns:
            if col not in df.columns:
                raise HTTPException(status_code=400, detail= f"Missing required column in Excel file: '{col}'")

        imported_count = 0
        generated_credentials = [] # Пазим ги тук локално, ако искаме да ги върнем като респонс за тест

        # 3. Обхождане на редовете от Ексел таблицата
        for index, row in df.iterrows():
            full_name = f"{str(row['Име']).strip()} {str(row['Фамилия']).strip()}"
            student_id_number = str(row['Фак. Номер']).strip()
            email = str(row['Имейл']).strip()

            # Проверка дали студентът вече съществува по Имейл или Фак. Номер
            exists = db.query(Student).filter(
                (Student.email == email) | (Student.student_id_number == student_id_number)
            ).first()

            if exists:
                continue # Прескачаме дублиращите се студенти, без да чупим целия импорт

            lock_password = "LOCKED_UNTIL_EMAIL_SENT"
            # Създаваме новия студент в състояние PENDING
            new_student = Student(
                full_name=full_name,
                student_id_number=student_id_number,
                email=email,
                hashed_password="LOCKED_UNTIL_EMAIL_SENT",
                faculty=faculty,
                specialty=specialty,
                course=course,
                stream=stream,
                group=group,
                status="PENDING",
                is_active=False
            )
            db.add(new_student)
            imported_count += 1
            
            # Записваме временно данните, за да може админът да ги види в респонса при желание
            generated_credentials.append({
                "email": email,
                "temporary_password": lock_password
            })

        if imported_count == 0:
            return {"message": "Няма нови студенти за импортиране от този файл."}

        # 4. СЪЗДАВАНЕ НА ЗАПИС В ADMIN_LOGS С ФЛАГ notification_sent = False 
        new_log = AdminLog(
            admin_id=admin.id,
            action_type="STUDENT_IMPORT",
            specialty=specialty,
            group=group,
            details=f"Успешен импорт на {imported_count} студенти за специалност {specialty}, група {group}.",
            notification_sent=False
        )
        db.add(new_log)
        
        db.commit()

        return {
            "message": f"Успешно импортирани {imported_count} студенти.",
            "admin_log_id": str(new_log.id),
            "notification_sent": False,
            "debug_credentials": generated_credentials # В реална среда ще го премахнем, за сигурност
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Грешка при обработка на Excel файла: {str(e)}")

@app.post("/admins/notifications/send/{log_id}")
def send_bulk_student_emails(log_id: str, payload: dict | None = Body(default=None), db: Session = Depends(get_db), current_admin: dict = Depends(require_admin)):
    """Изпраща известия за студентски импорт или изпитни регистрации."""
    admin = db.query(Admin).filter(Admin.id == current_admin['sub']).first()
    if not admin or not admin.is_verified:
        raise HTTPException(status_code=403, detail="Unauthorized access. Admin privileges required.")

    log = db.query(AdminLog).filter(AdminLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log entry not found for the provided ID.")

    selected_student_ids = []
    if isinstance(payload, dict):
        selected_student_ids = payload.get("student_ids") or []

    all_log_students = _resolve_log_students(db, log)
    target_students = _resolve_log_students(db, log, selected_student_ids or None)
    if not target_students:
        raise HTTPException(status_code=404, detail="There are no matching students for this log entry.")

    if log.action_type == "STUDENT_IMPORT":
        pending_students = [
            s for s in target_students
            if not (s.is_active or (s.hashed_password and s.hashed_password != "LOCKED_UNTIL_EMAIL_SENT"))
        ]
        if not pending_students:
            raise HTTPException(
                status_code=400,
                detail="Всички избрани студенти вече са активни и са получили своите временни пароли. Повторно изпращане не е разрешено."
            )
        target_students = pending_students

    success_sent_count = 0
    for student in target_students:
        if log.action_type == "STUDENT_IMPORT":
            new_temp_password = secrets.token_urlsafe(8) + "1A!"
            password_bytes = new_temp_password.encode('utf-8')
            hashed_bytes = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
            student.hashed_password = hashed_bytes.decode('utf-8')
            email_delivered = send_welcome_email(
                student_email=student.email,
                student_fac_num=student.student_id_number,
                student_name=student.full_name,
                temp_password=new_temp_password
            )
            if email_delivered:
                student.must_change_password = True
                student.is_active = True
                success_sent_count += 1
            continue

        if log.action_type.startswith("ALLOCATION_EXECUTION"):
            exams = []
            for exam in _resolve_log_exams(db, log):
                exists = db.query(ExamRegistration).filter(
                    ExamRegistration.student_id == student.id,
                    ExamRegistration.exam_id == exam.id
                ).first()
                if exists:
                    exams.append({
                        "subject": exam.subject,
                        "room_number": exam.room_number,
                        "date_time": exam.date_time.astimezone(timezone).strftime("%d.%m.%Y %H:%M") if exam.date_time else "",
                    })

            if not exams:
                continue

            email_delivered = send_allocation_email(
                student_email=student.email,
                student_name=student.full_name,
                exams=exams,
            )
            if email_delivered:
                success_sent_count += 1

    if success_sent_count == 0:
        raise HTTPException(status_code=500, detail="Грешка при изпращането на имейлите през SMTP сървъра.")

    selected_set = set(selected_student_ids)
    all_ids = {str(student.id) for student in all_log_students}

    if log.action_type == "STUDENT_IMPORT":
        all_active = all(bool(s.is_active) for s in all_log_students)
        if all_active or (not selected_student_ids or selected_set == all_ids):
            log.notification_sent = True
    elif log.action_type.startswith("ALLOCATION_EXECUTION") and (not selected_student_ids or selected_set == all_ids):
        log.notification_sent = True

    db.commit()
    return {
        "message": f"Успешно изпратени {success_sent_count} имейл известия.",
        "sent_count": success_sent_count
    }

@app.post("/students/enroll")
async def enroll_student(
    full_name: str = Form(...),
    student_id_number: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    faculty: str = Form(...),
    specialty: str = Form(...),
    course: int = Form(...),
    stream: int = Form(...),
    group: int = Form(...),
    #file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Ендпоинт за регистрация на студенти чрез мобилното приложение.
    Хешира паролата, извлича 128-измерен вектор от лицето и записва в Postgres.
    """
    try:
        validated_data = StudentEnrollSchema(
            full_name=full_name,
            student_id_number=student_id_number,
            email=email,
            password=password,
            faculty=faculty,
            specialty=specialty,
            course=course,
            stream=stream,
            group=group
        )
    except ValueError as e:
        # Ако имейлът или паролата са слаби, хвърляме грешката директно към клиента
        raise HTTPException(status_code=400, detail=str(e))
    # ALLOWED_EXTENSIONS = ["image/jpeg", "image/png", "image/jpg", "image/webp"]

    # if file.content_type not in ALLOWED_EXTENSIONS:
    #     raise HTTPException(
    #         status_code=400, 
    #         detail=f"Invalid file type! Only images are allowed: {', '.join(ALLOWED_EXTENSIONS)}"
    #     )

    # 1. Проверка за дублиране на факултетен номер или имейл
    existing_student = db.query(Student).filter(
        (Student.student_id_number == student_id_number) | (Student.email == email)
    ).first()
    
    if existing_student:
        raise HTTPException(status_code=400, detail="Student with this ID number or Email already exists.")

    try:
        # 2. Обработка на снимката (Селфито)
        # image_bytes = await file.read()
        # image = face_recognition.load_image_file(io.BytesIO(image_bytes))
        
        # photo_url = upload_photo_to_cloud(
        #     file_data=image_bytes,
        #     object_name=f"{student_id_number}_{int(time.time())}{os.path.splitext(file.filename)[1]}",
        #     content_type=file.content_type
        # )
    
        # # Извличане на векторите на лицата от снимката
        # face_encodings = face_recognition.face_encodings(image)
        
        # if len(face_encodings) == 0:
        #     raise HTTPException(status_code=400, detail="No face detected in the image. Please try another photo.")
            
        # # Взимаме вектора на първото открито лице
        # student_embedding = face_encodings[0].tolist()
        # if student_embedding:
        #     duplicate_face = db.query(Student).filter(
        #     Student.face_embedding.cosine_distance(student_embedding) < 0.05
        # ).first()
        
        # if duplicate_face:
        #     raise HTTPException(
        #         status_code=400, 
        #         detail=f"Biometric duplicate detected! This face is already registered to student {duplicate_face.full_name} ({duplicate_face.student_id_number})."
        #     )
        
        # 3. Хеширане на паролата с bcrypt
        password_bytes = password.encode('utf-8')
        # Генерираме salt и хешираме
        hashed_password_bytes = bcrypt.hashpw(password_bytes, bcrypt.gensalt())
        # Превръщаме байтовия хеш обратно в нормален текст (string) за запис в базата
        hashed_password = hashed_password_bytes.decode('utf-8')

        # 4. Генериране на новия запис за студент
        new_student = Student(
            full_name=full_name,
            student_id_number=student_id_number,
            email=email,
            faculty=faculty,
            specialty=specialty,
            course=course,
            stream=stream,
            group=group,
            hashed_password=hashed_password, # Записваме сигурния хеш, НЕ чистата парола
            face_embedding=None,#student_embedding,
            status="PENDING", # Студентът чака одобрение от администратор
            is_active=True
        )
        
        # 5. Запис в базата данни
        db.add(new_student)
        db.commit()
        db.refresh(new_student)
        
        return {
            "status": "success",
            "message": f"Student {full_name} enrolled successfully. Profile is pending admin activation.",
            "student_id": new_student.id
        }
    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed:{str(e)}")

@app.get("/register", response_class=HTMLResponse)
def get_register_page(request: fastapi.Request, role: Optional[str] = None):
    """ Връща HTML страницата за унифицирана регистрация """
    default_role = role if role in ("admin", "examiner") else "examiner"
    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"default_role": default_role}
    )

@app.post("/register")
def unified_register(
    register_data: UnifiedRegisterSchema,
    db: Session = Depends(get_db)
):
    """ Унифицирана регистрация за администратори и квестори със или без Secure Key """
    role = register_data.role.strip().lower()
    email = register_data.email.strip().lower()
    
    # Проверка и валидация на Secure Key при наличие
    is_verified = False
    if register_data.secure_key and register_data.secure_key.strip():
        validate_secure_key(db, register_data.secure_key)
        is_verified = True

    password_bytes = register_data.password.encode('utf-8')
    hashed_password = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode('utf-8')

    if role == "admin":
        existing_admin = db.query(Admin).filter(func.lower(Admin.email) == email).first()
        if existing_admin:
            raise HTTPException(status_code=400, detail="Admin with this email already exists.")
        
        new_admin = Admin(
            full_name=register_data.full_name.strip(),
            email=email,
            hashed_password=hashed_password,
            is_verified=is_verified
        )
        db.add(new_admin)
        db.commit()
        db.refresh(new_admin)
        
        msg = f"Admin {new_admin.full_name} registered and verified successfully." if is_verified else f"Admin {new_admin.full_name} registered successfully. Waiting for superadmin verification."
        return {
            "status": "success",
            "is_verified": is_verified,
            "message": msg,
            "id": str(new_admin.id),
            "role": "admin"
        }

    elif role == "examiner":
        existing_examiner = db.query(Examiner).filter(func.lower(Examiner.email) == email).first()
        if existing_examiner:
            raise HTTPException(status_code=400, detail="Examiner with this email already exists.")
        
        new_examiner = Examiner(
            full_name=register_data.full_name.strip(),
            email=email,
            hashed_password=hashed_password,
            is_verified=is_verified,
            role="EXAMINER"
        )
        db.add(new_examiner)
        db.commit()
        db.refresh(new_examiner)

        msg = f"Examiner {new_examiner.full_name} registered and verified successfully." if is_verified else f"Examiner {new_examiner.full_name} registered successfully. Waiting for superadmin verification."
        return {
            "status": "success",
            "is_verified": is_verified,
            "message": msg,
            "id": str(new_examiner.id),
            "role": "examiner"
        }
    else:
        raise HTTPException(status_code=400, detail="Невалидна роля. Разрешени роли: 'admin', 'examiner'.")

@app.post("/admins/register")
def register_admin(
    admin_data: AdminCreateSchema,
    db: Session = Depends(get_db)
):
    """ Регистрация на администратор (съвместимост с предишни извиквания) """
    unified_data = UnifiedRegisterSchema(
        email=admin_data.email,
        password=admin_data.password,
        full_name=admin_data.full_name,
        role="admin",
        secure_key=admin_data.secure_key
    )
    return unified_register(unified_data, db)

@app.post("/examiners/register")
def register_examiner(
    examiner_data: ExaminerCreateSchema,
    db: Session = Depends(get_db)
):
    """ Самостоятелна регистрация на квестор """
    unified_data = UnifiedRegisterSchema(
        email=examiner_data.email,
        password=examiner_data.password,
        full_name=examiner_data.full_name,
        role="examiner",
        secure_key=examiner_data.secure_key
    )
    return unified_register(unified_data, db)

@app.get("/admins/dashboard", response_class=HTMLResponse)
def get_admin_dashboard_page(request: fastapi.Request, response: Response):
    """ Връща HTML страницата за Администраторския контролен панел """
    admin_token = request.cookies.get("admin_token")
    if not admin_token:
        return RedirectResponse(url="/login", status_code=302)

    try:
        payload = jwt.decode(admin_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("role") not in ("admin", "superadmin") and not is_superadmin_user(payload):
            return RedirectResponse(url="/login", status_code=302)
        is_super = is_superadmin_user(payload)
    except Exception:
        return RedirectResponse(url="/login", status_code=302)

    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return templates.TemplateResponse(
        request=request, 
        name="admin_dashboard.html", 
        context={"request": request, "is_superadmin": is_super}
    )


@app.get("/admins/dashboard-data")
def get_admin_dashboard_data(db: Session = Depends(get_db), current_admin: dict = Depends(require_admin)):
    admin = db.query(Admin).filter(Admin.id == current_admin['sub']).first()
    if not admin or not admin.is_verified:
        raise HTTPException(status_code=403, detail="Unauthorized access. Admin privileges required.")

    # 1. Total counts
    total_student_import_logs_count = db.query(AdminLog).filter(AdminLog.action_type == "STUDENT_IMPORT").count()
    total_exam_import_logs_count = db.query(AdminLog).filter(AdminLog.action_type == "EXAM_IMPORT").count()
    total_allocation_logs_count = db.query(AdminLog).filter(AdminLog.action_type.in_(["ALLOCATION_EXECUTION", "ALLOCATION_EXECUTION_NO_NEW"])).count()

    # 2. Fetch recent logs (bounded to recent batches to eliminate multi-megabyte JSON bloat)
    student_import_logs = db.query(AdminLog).filter(AdminLog.action_type == "STUDENT_IMPORT").order_by(AdminLog.created_at.desc()).limit(30).all()
    exam_import_logs = db.query(AdminLog).filter(AdminLog.action_type == "EXAM_IMPORT").order_by(AdminLog.created_at.desc()).limit(30).all()
    allocation_logs = db.query(AdminLog).filter(AdminLog.action_type.in_(["ALLOCATION_EXECUTION", "ALLOCATION_EXECUTION_NO_NEW"])).order_by(AdminLog.created_at.desc()).limit(30).all()

    all_students = db.query(Student).order_by(Student.created_at.asc()).all()
    pending_students = [s for s in all_students if s.status == "PENDING_APPROVAL"]
    examiners = db.query(Examiner).order_by(Examiner.created_at.desc()).all()
    exams = db.query(Exam).order_by(Exam.date_time.asc()).all()

    # 3. Pre-index exams by str(id)
    exams_by_id_map = {str(e.id): e for e in exams}

    # 4. Pre-index students by (specialty, group) and build student group statistics for exam payload
    students_by_spec_group = defaultdict(list)
    student_stats_map = defaultdict(lambda: {"total": 0, "approved": 0})
    for s in all_students:
        students_by_spec_group[(s.specialty, s.group)].append(s)
        key = (s.faculty, s.specialty, s.course, str(s.stream), s.group)
        student_stats_map[key]["total"] += 1
        if s.status == "APPROVED":
            student_stats_map[key]["approved"] += 1

    # 5. Batch fetch allocated counts for all exams in 1 single query
    allocated_counts_raw = db.query(ExamRegistration.exam_id, func.count(ExamRegistration.id)).group_by(ExamRegistration.exam_id).all()
    allocated_counts = {eid: cnt for eid, cnt in allocated_counts_raw}

    # 6. Memoized exam payload generator
    cached_exam_payloads = {}
    def get_cached_exam_payload(exam: Exam) -> dict:
        if exam.id not in cached_exam_payloads:
            cached_exam_payloads[exam.id] = _exam_payload(
                exam,
                precomputed_allocated_counts=allocated_counts,
                precomputed_student_stats=student_stats_map
            )
        return cached_exam_payloads[exam.id]

    # 7. Pre-fetch registrations for recent allocation logs in 1 single joined query
    all_alloc_exam_ids = set()
    for log in allocation_logs:
        p_details = _parse_admin_log_details(log.details)
        for eid in p_details.get("exam_ids", [])[:20]:
            all_alloc_exam_ids.add(eid)

    preloaded_registrations_by_exam_id = defaultdict(list)
    if all_alloc_exam_ids:
        alloc_regs = db.query(ExamRegistration).filter(
            ExamRegistration.exam_id.in_(all_alloc_exam_ids)
        ).join(Student, ExamRegistration.student_id == Student.id
        ).join(Exam, ExamRegistration.exam_id == Exam.id
        ).order_by(Exam.date_time.asc(), Student.student_id_number.asc()).all()

        for reg in alloc_regs:
            reg_dict = {
                "id": str(reg.id),
                "student_id": str(reg.student_id),
                "student_name": reg.student.full_name if reg.student else "Неизвестен",
                "student_fac_num": reg.student.student_id_number if reg.student else "-",
                "student_email": reg.student.email if reg.student else "",
                "student_specialty": reg.student.specialty if reg.student else "-",
                "student_group": reg.student.group if reg.student else "-",
                "exam_id": str(reg.exam_id),
                "exam_subject": reg.exam.subject if reg.exam else "Неизвестен",
                "session_type": reg.exam.session_type.value if (reg.exam and reg.exam.session_type) else None,
                "room_number": reg.exam.room_number if reg.exam else "-",
                "date_time": reg.exam.date_time.isoformat() if (reg.exam and reg.exam.date_time) else None,
            }
            preloaded_registrations_by_exam_id[str(reg.exam_id)].append(reg_dict)

    # 8. Superadmin counts
    pending_verifications_count = 0
    if admin.is_superadmin:
        pending_admins_count = db.query(Admin).filter(Admin.is_verified == False, Admin.is_superadmin == False).count()
        pending_examiners_count = db.query(Examiner).filter(Examiner.is_verified == False).count()
        pending_verifications_count = pending_admins_count + pending_examiners_count

    # 9. Clean, de-duplicated allocation payloads
    allocation_payloads = []
    for log in allocation_logs:
        p_details = _parse_admin_log_details(log.details)
        eids = [str(x) for x in p_details.get("exam_ids", [])]

        # In allocation logs, include representative exam (at most 1) to prevent duplicating 1,720 exams 50 times
        log_exams = [get_cached_exam_payload(exams_by_id_map[eid]) for eid in eids if eid in exams_by_id_map][:1]
        
        regs = []
        for eid in eids[:20]:
            regs.extend(preloaded_registrations_by_exam_id.get(eid, []))

        # Trim parsed details exam_ids if huge (e.g. global allocation with thousands of UUIDs)
        trimmed_p_details = dict(p_details)
        if len(trimmed_p_details.get("exam_ids", [])) > 10:
            trimmed_p_details["exam_ids"] = trimmed_p_details["exam_ids"][:10]

        short_details = log.details
        if short_details and len(short_details) > 300:
            short_details = short_details[:300] + "..."

        allocation_payloads.append({
            "id": str(log.id),
            "action_type": log.action_type,
            "details": short_details,
            "parsed_details": trimmed_p_details,
            "specialty": log.specialty,
            "group": log.group,
            "notification_sent": log.notification_sent,
            "created_at": log.created_at.isoformat() if log.created_at else None,
            "student_ids": p_details.get("student_ids", [])[:10],
            "exam_ids": eids[:10],
            "exams": log_exams,
            "students": [],
            "registrations": regs,
        })

    # 10. Calculate personal and global multi-tenant KPI statistics
    # 10a. Student Imports
    all_student_import_logs_raw = db.query(AdminLog.admin_id, AdminLog.details).filter(AdminLog.action_type == "STUDENT_IMPORT").all()
    personal_student_batches = 0
    personal_student_count = 0
    for aid, details in all_student_import_logs_raw:
        m = re.search(r"(\d+)\s+студент", details or "")
        cnt = int(m.group(1)) if m else 0
        if str(aid) == str(admin.id):
            personal_student_batches += 1
            personal_student_count += cnt

    # 10b. Exam Imports
    all_exam_import_logs_raw = db.query(AdminLog.admin_id, AdminLog.details).filter(AdminLog.action_type == "EXAM_IMPORT").all()
    personal_exam_batches = 0
    personal_exam_count = 0
    for aid, details in all_exam_import_logs_raw:
        m = re.search(r"Създадени\s+(\d+)", details or "")
        cnt = int(m.group(1)) if m else 0
        if str(aid) == str(admin.id):
            personal_exam_batches += 1
            personal_exam_count += cnt

    # 10c. Biometrics
    personal_bio_approved = db.query(AdminLog).filter(
        AdminLog.action_type == "STUDENT_APPROVE",
        AdminLog.admin_id == admin.id
    ).count()
    global_bio_approved = db.query(AdminLog).filter(
        AdminLog.action_type == "STUDENT_APPROVE"
    ).count()
    approved_students_in_db = sum(1 for s in all_students if s.status == "APPROVED")
    if approved_students_in_db > global_bio_approved:
        global_bio_approved = approved_students_in_db

    # 10d. Allocations
    possible_allocations_count = 0
    for exam in exams:
        cached_p = get_cached_exam_payload(exam)
        if cached_p.get("approved_count", 0) > cached_p.get("allocated_count", 0):
            possible_allocations_count += 1

    personal_allocations_count = db.query(AdminLog).filter(
        AdminLog.action_type.in_(["ALLOCATION_EXECUTION", "ALLOCATION_EXECUTION_NO_NEW"]),
        AdminLog.admin_id == admin.id
    ).count()

    return {
        "is_superadmin": bool(admin.is_superadmin),
        "pending_verifications_count": pending_verifications_count,
        "counts": {
            "student_import_logs": total_student_import_logs_count,
            "exam_import_logs": total_exam_import_logs_count,
            "allocation_logs": total_allocation_logs_count,
            "pending_students": len(pending_students),
            "examiners": len(examiners),
            "exams": len(exams),
            "pending_verifications": pending_verifications_count,
        },
        "personal_stats": {
            "student_imports": {
                "batches": personal_student_batches,
                "students": personal_student_count,
            },
            "exam_imports": {
                "batches": personal_exam_batches,
                "exams": personal_exam_count,
            },
            "biometrics": {
                "approved": personal_bio_approved,
                "pending": len(pending_students),
            },
            "allocations": {
                "possible": possible_allocations_count,
                "completed": personal_allocations_count,
            },
        },
        "global_stats": {
            "student_imports": {
                "batches": total_student_import_logs_count,
                "students": len(all_students),
            },
            "exam_imports": {
                "batches": total_exam_import_logs_count,
                "exams": len(exams),
            },
            "biometrics": {
                "approved": global_bio_approved,
                "pending": len(pending_students),
            },
            "allocations": {
                "possible": possible_allocations_count,
                "completed": total_allocation_logs_count,
            },
        },
        "student_import_logs": [
            {
                **_admin_log_payload(log),
                "students": [
                    {
                        **_student_payload(student),
                        "photo_url": _photo_url_for_student(student),
                    }
                    for student in _resolve_log_students(
                        db,
                        log,
                        preloaded_students_by_spec_group=students_by_spec_group
                    )
                ],
            }
            for log in student_import_logs
        ],
        "exam_import_logs": [
            {
                **_admin_log_payload(log),
                "exams": [
                    get_cached_exam_payload(exam)
                    for exam in _resolve_log_exams(
                        db,
                        log,
                        all_exams_list=exams,
                        exams_by_id_map=exams_by_id_map
                    )
                ],
            }
            for log in exam_import_logs
        ],
        "allocation_logs": allocation_payloads,
        "pending_students": [
            {
                **_student_payload(student),
                "photo_url": _photo_url_for_student(student),
                "student_book_photo_url": _student_book_photo_url_for_student(student),
            }
            for student in pending_students
        ],
        "examiners": [
            {
                "id": str(examiner.id),
                "full_name": examiner.full_name,
                "email": examiner.email,
                "is_verified": examiner.is_verified,
                "created_at": examiner.created_at.isoformat() if examiner.created_at else None,
            }
            for examiner in examiners
        ],
        "exams": [get_cached_exam_payload(exam) for exam in exams],
    }


@app.get("/admins/students/{student_id}/photo")
def get_student_photo(student_id: str, token: str = Query(...), db: Session = Depends(get_db)):

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("role") not in ("admin", "superadmin") and not is_superadmin_user(payload):
            raise HTTPException(status_code=403, detail="Достъпът е отказан. Изискват се админ права.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Невалиден или изтекъл администраторски токен.")


    student = db.query(Student).filter(Student.id == student_id).first()
    if not student or not student.photo_path:
        raise HTTPException(status_code=404, detail="Student photo not found.")

    prefix = f"/{BUCKET_NAME}/"
    if student.photo_path.startswith(prefix):
        object_name = student.photo_path[len(prefix):]
    else:
        object_name = student.photo_path.lstrip("/")

    file_data = get_photo_from_cloud(object_name)
    content_type, _ = mimetypes.guess_type(object_name)
    return StreamingResponse(io.BytesIO(file_data), media_type=content_type or "image/jpeg")


@app.get("/admins/students/{student_id}/student-book-photo")
def get_student_book_photo(student_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("role") not in ("admin", "superadmin") and not is_superadmin_user(payload):
            raise HTTPException(status_code=403, detail="Достъпът е отказан. Изискват се админ права.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Невалиден или изтекъл администраторски токен.")

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student or not student.student_book_photo_path:
        raise HTTPException(status_code=404, detail="Student book photo not found.")

    prefix = f"/{BUCKET_NAME}/"
    if student.student_book_photo_path.startswith(prefix):
        object_name = student.student_book_photo_path[len(prefix):]
    else:
        object_name = student.student_book_photo_path.lstrip("/")

    file_data = get_photo_from_cloud(object_name)
    content_type, _ = mimetypes.guess_type(object_name)
    return StreamingResponse(io.BytesIO(file_data), media_type=content_type or "image/jpeg")

@app.post("/admins/upload/exams")
async def upload_exams(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_admin)
):
    """
    Импортиране на изпити от Excel файл.
    Очаква колони на български: Сесия, Дисциплина, Преподавател, Дата и Час, Зала, Факултет, Специалност, Курс, Поток, Група
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Invalid file format. Please upload an Excel file.")

    admin = db.query(Admin).filter(Admin.id == current_admin['sub']).first()
    
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found.")
        
    if not admin.is_verified:
        raise HTTPException(status_code=403, detail="Your admin account is not verified.")

    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        # Очаквани колони на български
        required_columns = {
            "Сесия", "Дисциплина", "Преподавател", "Дата", "Час", 
            "Зала", "Факултет", "Специалност", "Курс", "Поток", "Група"
        }
        
        if not required_columns.issubset(df.columns):
            raise HTTPException(
                status_code=400, 
                detail=f"Excel file must contain exactly the following columns: {list(required_columns)}"
            )
        
        exams_created = 0
        exams_updated = 0
        
        # 3. Обхождане на изпитите от Ексел
        for index, row in df.iterrows():
            try:
                row_dict = row.to_dict()
                validated_data = ExamUploadValidationSchema(**row_dict)
            except ValidationError as val_err:
                # Взимаме първата грешка и я връщаме с точния ред от Excel
                error_msg = val_err.errors()[0]['msg']
                raise HTTPException(
                    status_code=400,
                    detail=f"Грешка на ред {index + 2}: {error_msg}"
                )

            # Софтуерно обединяване на дата и час (след като знаем, че са чисти)
            raw_date = str(validated_data.date_raw).split()[0].strip()
            raw_time = validated_data.time_raw.strip()
            date_time_val = pd.to_datetime(f"{raw_date} {raw_time}")
            if date_time_val.tzinfo is None:
                date_time_val = date_time_val.tz_localize(timezone)
            else:
                date_time_val = date_time_val.tz_convert(timezone)
            date_time_val = date_time_val.to_pydatetime()

            # Проверка за уникалност
            existing_exam = db.query(Exam).filter(
                Exam.subject == validated_data.subject.strip(),
                Exam.date_time == date_time_val,
                Exam.room_number == validated_data.room_number.strip(),
                Exam.specialty == validated_data.specialty.strip()
            ).first()
            
            if existing_exam:
                existing_exam.session_type = validated_data.session_type
                existing_exam.group = validated_data.group
                existing_exam.lecturer = validated_data.lecturer.strip()
                existing_exam.faculty = validated_data.faculty.strip()
                existing_exam.course = validated_data.course
                existing_exam.stream = validated_data.stream
                existing_exam.created_at = func.now()
                exams_updated += 1
            else:
                new_exam = Exam(
                    session_type=validated_data.session_type,
                    subject=validated_data.subject.strip(),
                    lecturer=validated_data.lecturer.strip(),
                    date_time=date_time_val,
                    room_number=validated_data.room_number.strip(),
                    faculty=validated_data.faculty.strip(),
                    specialty=validated_data.specialty.strip(),
                    course=validated_data.course,
                    stream=validated_data.stream,
                    group=validated_data.group
                )
                db.add(new_exam)
                exams_created += 1

        # 4. Запис в лога при промени
        log_id = None
        if exams_created > 0 or exams_updated > 0:
            new_log = AdminLog(
                admin_id=admin.id,
                action_type="EXAM_IMPORT",
                details=f"Импорт на изпити: Създадени {exams_created}, Обновени {exams_updated}.",
                notification_sent=True
            )
            db.add(new_log)
            db.commit()
            db.refresh(new_log)
            log_id = str(new_log.id)
        else:
            db.commit()
        
        return {
            "status": "success",
            "message": f"Обработката на Excel файла приключи успешно. Създадени: {exams_created}, Обновени: {exams_updated}",
            "created": exams_created,
            "updated": exams_updated,
            "admin_log_id": log_id
        }
    
    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Грешка при обработката на Excel файла: {str(e)}")

@app.post("/admins/examiners/register")
def create_examiner(examiner_data: ExaminerCreateSchema, db: Session = Depends(get_db), current_admin: dict = Depends(require_admin)):
    """
    Ендпоинт за добавяне на квестори.
    """
    # Проверяваме дали имейлът вече съществува
    admin = db.query(Admin).filter(Admin.id == current_admin['sub']).first()
    if not admin.is_verified:
        raise HTTPException(status_code=403, detail="Your admin account is pending verification. Unauthorized access.")
    existing_examiner = db.query(Examiner).filter(Examiner.email == examiner_data.email).first()
    if existing_examiner:
        raise HTTPException(status_code=400, detail="Този имейл вече е регистриран.")

    password_bytes = examiner_data.password.encode('utf-8')
    hashed_password = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode('utf-8')

    new_examiner = Examiner(
        full_name=examiner_data.full_name,
        email=examiner_data.email,
        hashed_password=hashed_password,
        role="EXAMINER" # По подразбиране
    )

    db.add(new_examiner)
    db.commit()
    db.refresh(new_examiner)

    return {
        "message": f"Examiner {new_examiner.full_name} registered successfully. Waiting for superadmin verification.",
        "examiner_id": str(new_examiner.id)
    }

@app.get("/login", response_class=HTMLResponse)
def get_login_page(request: fastapi.Request, role: Optional[str] = None):
    """ Връща унифицираната HTML страница за вход в системата """
    default_role = role if role in ("admin", "examiner") else "examiner"
    return templates.TemplateResponse(
        request=request, 
        name="login.html", 
        context={"default_role": default_role}
    )

@app.post("/login")
def unified_login(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    role: Optional[str] = Form("examiner"),
    room_number: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """ Унифициран вход за администратори и квестори """
    clean_email = email.strip().lower()
    clean_role = role.strip().lower() if role else "examiner"

    if clean_role == "admin":
        admin = db.query(Admin).filter(func.lower(Admin.email) == clean_email).first()
        if not admin:
            raise HTTPException(status_code=400, detail="Invalid email or password.")
        if not admin.is_verified:
            raise HTTPException(status_code=403, detail="Your admin account is pending verification. Please contact the superadmin.")
        if not verify_password(password, admin.hashed_password):
            raise HTTPException(status_code=400, detail="Invalid email or password.")

        access_token = create_access_token(data={
            "sub": str(admin.id),
            "role": "admin",
            "is_superadmin": bool(admin.is_superadmin)
        })
        response.set_cookie(
            key="admin_token",
            value=access_token,
            max_age=60 * 60 * 2,
            httponly=False,
            samesite="lax",
            secure=False,
            path="/"
        )
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": "admin",
            "is_superadmin": bool(admin.is_superadmin),
            "full_name": admin.full_name
        }

    elif clean_role == "examiner":
        examiner = db.query(Examiner).filter(func.lower(Examiner.email) == clean_email).first()
        if examiner:
            if not examiner.is_verified:
                raise HTTPException(status_code=403, detail="Вашият квесторски акаунт очаква потвърждение от администратор.")
            if not verify_password(password, examiner.hashed_password):
                raise HTTPException(status_code=400, detail="Invalid email or password.")

            access_token = create_access_token(data={"sub": str(examiner.id), "role": "examiner", "is_superadmin": False})
            response.set_cookie(
                key="examiner_token",
                value=access_token,
                max_age=60 * 60 * 2,
                httponly=False,
                samesite="lax",
                secure=False,
                path="/"
            )
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "role": "examiner",
                "full_name": examiner.full_name,
                "is_superadmin": False
            }

        # Fallback за Superadmin акаунт (Omni-Role достъп)
        admin = db.query(Admin).filter(func.lower(Admin.email) == clean_email, Admin.is_superadmin == True).first()
        if admin and verify_password(password, admin.hashed_password):
            access_token = create_access_token(data={"sub": str(admin.id), "role": "examiner", "is_superadmin": True})
            response.set_cookie(
                key="examiner_token",
                value=access_token,
                max_age=60 * 60 * 2,
                httponly=False,
                samesite="lax",
                secure=False,
                path="/"
            )
            return {
                "access_token": access_token,
                "token_type": "bearer",
                "role": "examiner",
                "full_name": f"{admin.full_name} (Superadmin)",
                "is_superadmin": True
            }

        raise HTTPException(status_code=400, detail="Invalid email or password.")
    else:
        raise HTTPException(status_code=400, detail="Невалидна роля. Изберете администратор или квестор.")

@app.post("/admins/login")
def admin_login_legacy(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    return unified_login(response=response, email=email, password=password, role="admin", db=db)

@app.post("/examiners/login")
def examiner_login_legacy(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    return unified_login(response=response, email=email, password=password, role="examiner", db=db)


# ==========================================
# SUPERADMIN VERIFICATIONS & SECURE KEY APIS
# ==========================================

@app.get("/admins/verifications/pending")
def get_pending_verifications(
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_superadmin)
):
    """ Връща списък с чакащи верификация администратори и квестори, сортирани хронологично (най-старите първи) """
    pending_admins = db.query(Admin).filter(
        Admin.is_verified == False,
        Admin.is_superadmin == False
    ).all()
    pending_examiners = db.query(Examiner).filter(
        Examiner.is_verified == False
    ).all()

    items = []
    for a in pending_admins:
        items.append({
            "id": str(a.id),
            "role": "admin",
            "role_display": "Администратор",
            "full_name": a.full_name,
            "email": a.email,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "created_at_dt": a.created_at or datetime.min
        })
    for e in pending_examiners:
        items.append({
            "id": str(e.id),
            "role": "examiner",
            "role_display": "Квестор",
            "full_name": e.full_name,
            "email": e.email,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "created_at_dt": e.created_at or datetime.min
        })

    # Сортиране най-старите първи
    items.sort(key=lambda x: x["created_at_dt"])
    for it in items:
        it.pop("created_at_dt", None)

    return {"pending_verifications": items, "count": len(items)}

@app.post("/admins/verifications/{account_type}/{account_id}/grant")
def grant_verification_access(
    account_type: str,
    account_id: str,
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_superadmin)
):
    """ Одобрява заявка за достъп (Grant Access - V) """
    clean_type = account_type.strip().lower()
    if clean_type == "admin":
        target = db.query(Admin).filter(Admin.id == account_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Admin account not found.")
        target.is_verified = True
        db.commit()
        return {"status": "success", "message": f"Достъпът за администратор {target.full_name} е одобрен."}
    elif clean_type == "examiner":
        target = db.query(Examiner).filter(Examiner.id == account_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Examiner account not found.")
        target.is_verified = True
        db.commit()
        return {"status": "success", "message": f"Достъпът за квестор {target.full_name} е одобрен."}
    else:
        raise HTTPException(status_code=400, detail="Invalid account type.")

@app.post("/admins/verifications/{account_type}/{account_id}/reject")
def reject_verification_access(
    account_type: str,
    account_id: str,
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_superadmin)
):
    """ Отхвърля заявка за достъп (Reject - X) """
    clean_type = account_type.strip().lower()
    if clean_type == "admin":
        target = db.query(Admin).filter(Admin.id == account_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Admin account not found.")
        name = target.full_name
        db.delete(target)
        db.commit()
        return {"status": "success", "message": f"Заявката за администратор {name} е отхвърлена и изтрита."}
    elif clean_type == "examiner":
        target = db.query(Examiner).filter(Examiner.id == account_id).first()
        if not target:
            raise HTTPException(status_code=404, detail="Examiner account not found.")
        name = target.full_name
        db.delete(target)
        db.commit()
        return {"status": "success", "message": f"Заявката за квестор {name} е отхвърлена и изтрита."}
    else:
        raise HTTPException(status_code=400, detail="Invalid account type.")

@app.get("/admins/secure-key/status")
def get_secure_key_status(
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_superadmin)
):
    """ Връща текущия статус на Secure Key (маскиран със звездички) """
    from datetime import timezone
    active_key = db.query(SecureKey).filter(SecureKey.is_active == True).order_by(SecureKey.created_at.desc()).first()
    if not active_key:
        return {
            "unattended_enabled": False,
            "has_active_key": False,
            "masked_key": None,
            "duration_type": None,
            "expires_at": None,
            "created_at": None
        }

    if active_key.expires_at is not None:
        expires_at = active_key.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            active_key.is_active = False
            db.commit()
            return {
                "unattended_enabled": False,
                "has_active_key": False,
                "masked_key": None,
                "duration_type": None,
                "expires_at": None,
                "created_at": None
            }

    return {
        "unattended_enabled": True,
        "has_active_key": True,
        "masked_key": "********",
        "duration_type": active_key.duration_type,
        "expires_at": active_key.expires_at.isoformat() if active_key.expires_at else None,
        "created_at": active_key.created_at.isoformat() if active_key.created_at else None
    }

@app.post("/admins/secure-key/generate")
def generate_secure_key_endpoint(
    payload: SecureKeyGenerateSchema,
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_superadmin)
):
    """ Генерира нов Secure Key за необслужвано създаване на акаунти """
    from app.auth import generate_secure_key_token
    # Деактивираме предишни активни ключове
    db.query(SecureKey).filter(SecureKey.is_active == True).update({
        "is_active": False,
        "revoked_at": func.now()
    })
    db.commit()

    duration_str = payload.duration.value if hasattr(payload.duration, "value") else str(payload.duration)
    raw_token, key_hash, expires_at = generate_secure_key_token(duration_str)

    new_key = SecureKey(
        key_hash=key_hash,
        duration_type=duration_str,
        expires_at=expires_at,
        is_active=True
    )
    db.add(new_key)
    db.commit()
    db.refresh(new_key)

    return {
        "status": "success",
        "secure_key": raw_token,
        "duration_type": duration_str,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "created_at": new_key.created_at.isoformat() if new_key.created_at else None
    }

@app.delete("/admins/secure-key")
def delete_secure_key_endpoint(
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_superadmin)
):
    """ Анулира и изтрива активния Secure Key """
    active_keys = db.query(SecureKey).filter(SecureKey.is_active == True).all()
    for key in active_keys:
        key.is_active = False
        key.revoked_at = func.now()
    db.commit()
    return {"status": "success", "message": "Secure Key deleted successfully."}


@app.post("/students/login", response_model=StudentLoginResponseSchema)
async def student_login(
    payload: StudentLoginSchema,
    db: Session = Depends(get_db)
):
    """
    Ендпоинт за вход на студенти в мобилното приложение.
    Поддържа вход и за Superadmin акаунт за лесно тестване.
    """
    input_id = payload.student_id_number.strip()
    student = db.query(Student).filter(Student.student_id_number == input_id).first()
    
    if not student:
        # Проверка дали се логва Superadmin акаунт през мобилното приложение
        superadmin = db.query(Admin).filter(
            Admin.is_superadmin == True,
            func.lower(Admin.email) == input_id.lower()
        ).first()
        if not superadmin and input_id.lower() in ["superadmin", "0", "000000000"]:
            superadmin = db.query(Admin).filter(Admin.is_superadmin == True).first()

        if superadmin and verify_password(payload.password, superadmin.hashed_password):
            token_data = {
                "sub": str(superadmin.id),
                "student_id_number": "000000000",
                "role": "student",
                "is_superadmin": True,
                "must_change": False,
                "student_status": "APPROVED",
            }
            token = create_access_token(data=token_data)
            return {
                "status": "success",
                "message": "Успешен вход в системата (Superadmin).",
                "access_token": token,
                "student_status": "APPROVED",
                "has_face_embedding": True,
                "must_change_password": False,
            }
        raise HTTPException(status_code=401, detail="Invalid student ID number or password.")

    # 2. Проверка дали акаунтът е заключен (Чакащ имейл) 
    if student.hashed_password == "LOCKED_UNTIL_EMAIL_SENT":
        raise HTTPException(
            status_code=403, 
            detail="Your account is locked until you receive the official email with a temporary password."
        )

    # 3. Проверка на паролата
    if not verify_password(payload.password, student.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid student ID number or password.")

    has_face = student.face_embedding is not None

    # 4. Генериране на JWT Данни (Payload)
    token_data = {
        "sub": str(student.id),
        "student_id_number": student.student_id_number,
        "role": "student",
        "is_superadmin": False,
        "must_change": student.must_change_password,
        "student_status": student.status,
    }
    token = create_access_token(data=token_data)

    # 5. Проверка за първо влизане (Смяна на парола)
    if student.must_change_password:
        return {
            "status": "force_password_change",
            "message": "Първоначален вход. Моля, сменете временната си парола.",
            "access_token": token,
            "student_status": student.status,
            "has_face_embedding": has_face,
            "must_change_password": True,
        }

    # 6. Нормален вход
    return {
        "status": "success",
        "message": "Успешен вход в системата.",
        "access_token": token,
        "student_status": student.status,
        "has_face_embedding": has_face,
        "must_change_password": False,
    }


@app.post("/students/change-password")
async def change_student_password(
    payload: ChangePasswordSchema,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Ендпоинт за първоначална или последваща смяна на студентската парола.
    След успешна смяна, флагът must_change_password се залага на False.
    """
    # 1. Стриктна софтуерна защита: Допускаме студенти или Superadmin
    if current_user.get("role") not in ("student", "superadmin") and not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Достъпът е отказан. Ендпоинтът е само за студенти.")

    student_id = current_user.get("sub")
    student = db.query(Student).filter(Student.id == student_id).first()
    
    # Обработка за Superadmin без отделен физически Student запис
    if not student and is_superadmin_user(current_user):
        admin = db.query(Admin).filter(Admin.id == student_id, Admin.is_superadmin == True).first()
        if not admin:
            admin = db.query(Admin).filter(Admin.is_superadmin == True).first()
        if not admin:
            raise HTTPException(status_code=404, detail="Superadmin профилът не е намерен в системата.")

        if payload.old_password and not verify_password(payload.old_password, admin.hashed_password):
            raise HTTPException(status_code=400, detail="Грешна текуща парола.")
        if payload.old_password == payload.new_password:
            raise HTTPException(status_code=400, detail="Новата парола трябва да бъде различна от текущата.")

        admin.hashed_password = get_password_hash(payload.new_password)
        db.commit()

        new_token = create_access_token(data={
            "sub": str(admin.id),
            "student_id_number": "000000000",
            "role": "student",
            "is_superadmin": True,
            "must_change": False,
            "student_status": "APPROVED",
        })

        return {
            "status": "success",
            "message": "Паролата беше обновена успешно.",
            "access_token": new_token
        }

    if not student:
        raise HTTPException(status_code=404, detail="Студентът не е намерен в системата.")

    # 3. Валидация на текущата парола при последваща смяна от потребителския профил
    if not student.must_change_password:
        if not payload.old_password:
            raise HTTPException(status_code=400, detail="Моля, въведете текущата си парола.")
        if not verify_password(payload.old_password, student.hashed_password):
            raise HTTPException(status_code=400, detail="Грешна текуща парола.")
        if payload.old_password == payload.new_password:
            raise HTTPException(status_code=400, detail="Новата парола трябва да бъде различна от текущата.")
    elif payload.old_password:
        if not verify_password(payload.old_password, student.hashed_password):
            raise HTTPException(status_code=400, detail="Грешна текуща парола.")

    # 4. Хеширане на новата парола и обновяване на базата данни
    hashed_new_pw = get_password_hash(payload.new_password)
    student.hashed_password = hashed_new_pw
    student.must_change_password = False

    # Запазваме промените в Postgres
    db.commit()

    # Генерираме нов токен с актуализиран must_change = False
    new_token = create_access_token(data={
        "sub": str(student.id),
        "student_id_number": student.student_id_number,
        "role": "student",
        "is_superadmin": False,
        "must_change": False,
        "student_status": student.status,
    })

    return {
        "status": "success",
        "message": "Паролата беше обновена успешно.",
        "access_token": new_token
    }

@app.get("/students/impersonate/list", response_model=list[StudentSummarySchema])
def get_students_impersonation_list(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Връща списък на реални студенти в системата за симулация/имперсониране от Superadmin.
    Достъпно САМО за Superadmin.
    """
    if not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Достъпът е разрешен само за Superadmin.")

    students = db.query(Student).order_by(
        Student.faculty.asc(),
        Student.course.asc(),
        Student.stream.asc(),
        Student.group.asc(),
        Student.student_id_number.asc()
    ).all()

    return [
        {
            "id": str(s.id),
            "full_name": s.full_name,
            "student_id_number": s.student_id_number,
            "faculty": s.faculty or "",
            "specialty": s.specialty or "",
            "course": s.course or 1,
            "stream": s.stream or 1,
            "group": s.group or 1,
            "status": s.status or "PENDING",
            "has_face_embedding": s.face_embedding is not None,
        }
        for s in students
    ]


@app.get("/students/profile", response_model=StudentProfileSchema)
@app.get("/students/me", response_model=StudentProfileSchema)
def get_student_profile(
    impersonate_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Извлича профила и текущия статус на валидация на студента.
    При статус REJECTED извлича причината за отхвърляне от admin_logs.
    При вход на Superadmin връща валидиран студентски профил или профил на имперсониран студент.
    """
    if current_user.get("role") not in ("student", "superadmin") and not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Достъпът е разрешен само за студенти.")

    # Проверка за имперсониране от Superadmin
    if impersonate_id:
        if not is_superadmin_user(current_user):
            raise HTTPException(status_code=403, detail="Само Superadmin може да преглежда чужди студентски профили.")
        target_student = db.query(Student).filter(Student.id == impersonate_id).first()
        if not target_student:
            raise HTTPException(status_code=404, detail="Студентът за симулация не е намерен.")

        rejection_reason = None
        if target_student.status == "REJECTED":
            reject_log = (
                db.query(AdminLog)
                .filter(
                    AdminLog.action_type == "STUDENT_REJECT",
                    AdminLog.details.like(f"%{target_student.student_id_number}%")
                )
                .order_by(AdminLog.created_at.desc())
                .first()
            )
            if reject_log and reject_log.details:
                if "Причина: " in reject_log.details:
                    rejection_reason = reject_log.details.split("Причина: ", 1)[1].strip()
                else:
                    rejection_reason = reject_log.details.strip()

        return {
            "id": str(target_student.id),
            "full_name": target_student.full_name,
            "student_id_number": target_student.student_id_number,
            "email": target_student.email,
            "faculty": target_student.faculty,
            "specialty": target_student.specialty,
            "course": target_student.course,
            "stream": target_student.stream,
            "group": target_student.group,
            "status": target_student.status or "PENDING",
            "has_face_embedding": target_student.face_embedding is not None,
            "rejection_reason": rejection_reason,
            "photo_url": _photo_url_for_student(target_student),
            "student_book_photo_url": _student_book_photo_url_for_student(target_student),
            "is_superadmin": True,
            "is_impersonating": True,
        }

    student_id = current_user.get("sub")
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        if is_superadmin_user(current_user):
            admin = db.query(Admin).filter(Admin.id == student_id, Admin.is_superadmin == True).first()
            if not admin:
                admin = db.query(Admin).filter(Admin.is_superadmin == True).first()
            return {
                "id": str(admin.id if admin else student_id),
                "full_name": f"{admin.full_name if admin else 'Super Administrator'} (Superadmin)",
                "student_id_number": "000000000",
                "email": admin.email if admin else "superadmin@tu-sofia.bg",
                "faculty": "ФКСТ",
                "specialty": "КСИ",
                "course": 4,
                "stream": 1,
                "group": 1,
                "status": "APPROVED",
                "has_face_embedding": True,
                "rejection_reason": None,
                "photo_url": None,
                "student_book_photo_url": None,
                "is_superadmin": True,
                "is_impersonating": False,
            }
        raise HTTPException(status_code=404, detail="Студентът не е намерен в системата.")

    rejection_reason = None
    if student.status == "REJECTED":
        reject_log = (
            db.query(AdminLog)
            .filter(
                AdminLog.action_type == "STUDENT_REJECT",
                AdminLog.details.like(f"%{student.student_id_number}%")
            )
            .order_by(AdminLog.created_at.desc())
            .first()
        )
        if reject_log and reject_log.details:
            if "Причина: " in reject_log.details:
                rejection_reason = reject_log.details.split("Причина: ", 1)[1].strip()
            else:
                rejection_reason = reject_log.details.strip()

    return {
        "id": str(student.id),
        "full_name": student.full_name,
        "student_id_number": student.student_id_number,
        "email": student.email,
        "faculty": student.faculty,
        "specialty": student.specialty,
        "course": student.course,
        "stream": student.stream,
        "group": student.group,
        "status": student.status or "PENDING",
        "has_face_embedding": student.face_embedding is not None,
        "rejection_reason": rejection_reason,
        "photo_url": _photo_url_for_student(student),
        "student_book_photo_url": _student_book_photo_url_for_student(student),
        "is_superadmin": is_superadmin_user(current_user),
        "is_impersonating": False,
    }

@app.get("/admins/allocation-preview")
def preview_student_allocation(
    exam_id: Optional[str] = Query(default=None),
    exam_ids: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_admin)
):
    """
    Преглед на очаквания резултат от разпределението преди неговото реално изпълнение.
    Анализира кои одобрени студенти ще получат регистрации, кои ще бъдат пропуснати
    поради липса на биометрично одобрение (PENDING), и връща списък за предварителен преглед.
    """
    admin = db.query(Admin).filter(Admin.id == current_admin['sub']).first()
    if not admin or not admin.is_verified:
        raise HTTPException(status_code=403, detail="Your admin account is pending verification. Cannot preview allocation.")

    if exam_id:
        all_exams = db.query(Exam).filter(Exam.id == exam_id).all()
        if not all_exams:
            raise HTTPException(status_code=404, detail="Exam not found for the provided ID.")
    elif exam_ids:
        raw_ids = [x.strip() for x in exam_ids.split(",") if x.strip()]
        all_exams = db.query(Exam).filter(Exam.id.in_(raw_ids)).all()
    else:
        all_exams = db.query(Exam).filter(Exam.session_type.in_([SessionType.SUMMER, SessionType.WINTER])).all()

    # Извличаме студентите и ги индексираме за светкавичен анализ в паметта
    students = db.query(Student).all()
    student_index = defaultdict(list)
    for s in students:
        key = (
            str(s.faculty or "").strip().upper(),
            str(s.specialty or "").strip().upper(),
            int(s.course) if s.course is not None else 0,
            str(s.stream or "").strip(),
            int(s.group) if s.group is not None else 0
        )
        student_index[key].append(s)

    exam_ids_set = {e.id for e in all_exams}
    existing_pairs = set(
        db.query(ExamRegistration.exam_id, ExamRegistration.student_id)
        .filter(ExamRegistration.exam_id.in_(exam_ids_set))
        .all()
    ) if exam_ids_set else set()

    ready_registrations_count = 0
    unique_ready_students = set()
    affected_exam_ids = set()
    skipped_pending_bio_students = set()
    skipped_pending_bio_registrations = 0
    preview_items = []

    for exam in all_exams:
        allowed_groups = [int(g.strip()) for g in (exam.group or "").split(",") if g.strip().isdigit()]
        for g in allowed_groups:
            key = (
                str(exam.faculty or "").strip().upper(),
                str(exam.specialty or "").strip().upper(),
                int(exam.course) if exam.course is not None else 0,
                str(exam.stream or "").strip(),
                g
            )
            candidates = student_index.get(key, [])
            for st in candidates:
                if (exam.id, st.id) in existing_pairs:
                    continue
                if st.status == "APPROVED":
                    ready_registrations_count += 1
                    unique_ready_students.add(st.id)
                    affected_exam_ids.add(exam.id)
                    if len(preview_items) < 100:
                        preview_items.append({
                            "student_name": st.full_name,
                            "student_fac_num": st.student_id_number,
                            "student_specialty": st.specialty,
                            "student_course": st.course,
                            "student_group": st.group,
                            "exam_id": str(exam.id),
                            "exam_subject": exam.subject,
                            "session_type": exam.session_type.value if exam.session_type else None,
                            "room_number": exam.room_number,
                            "date_time": exam.date_time.isoformat() if exam.date_time else None,
                        })
                else:
                    skipped_pending_bio_students.add(st.id)
                    skipped_pending_bio_registrations += 1

    return {
        "status": "success",
        "ready_registrations_count": ready_registrations_count,
        "unique_students_count": len(unique_ready_students),
        "affected_exams_count": len(affected_exam_ids),
        "total_exams_evaluated": len(all_exams),
        "skipped_pending_bio_count": len(skipped_pending_bio_students),
        "skipped_pending_bio_registrations": skipped_pending_bio_registrations,
        "can_allocate": ready_registrations_count > 0,
        "preview_items": preview_items,
    }


@app.post("/admins/execute-allocation")
def execute_student_allocation(
    payload: dict | None = Body(default=None),
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_admin)
):
    """
    Задействане на разпределението. 
    Обхожда всички изпити, разделя групите по запетайка и вкарва съответните студенти в exam_registrations.
    Ако няма нови регистрации, НЕ генерира празен лог в базата и връща статус noop.
    """

    admin = db.query(Admin).filter(Admin.id == current_admin['sub']).first()
    if not admin or not admin.is_verified:
        raise HTTPException(status_code=403, detail="Your admin account is pending verification. Cannot execute allocation.")

    exam_id = None
    exam_ids = None
    if isinstance(payload, dict):
        exam_id = payload.get("exam_id")
        exam_ids = payload.get("exam_ids")

    if exam_id:
        all_exams = db.query(Exam).filter(Exam.id == exam_id).all()
        if not all_exams:
            raise HTTPException(status_code=404, detail="Exam not found for the provided ID.")
    elif exam_ids and isinstance(exam_ids, list):
        all_exams = db.query(Exam).filter(Exam.id.in_(exam_ids)).all()
    else:
        all_exams = db.query(Exam).filter(Exam.session_type.in_([SessionType.SUMMER, SessionType.WINTER])).all()

    # Индексираме одобрените студенти за бързо разпределение
    approved_students = db.query(Student).filter(Student.status == "APPROVED").all()
    student_index = defaultdict(list)
    for s in approved_students:
        key = (
            str(s.faculty or "").strip().upper(),
            str(s.specialty or "").strip().upper(),
            int(s.course) if s.course is not None else 0,
            str(s.stream or "").strip(),
            int(s.group) if s.group is not None else 0
        )
        student_index[key].append(s)

    exam_ids_set = {e.id for e in all_exams}
    existing_pairs = set(
        db.query(ExamRegistration.exam_id, ExamRegistration.student_id)
        .filter(ExamRegistration.exam_id.in_(exam_ids_set))
        .all()
    ) if exam_ids_set else set()

    total_registrations_created = 0
    processed_exam_ids = []

    for exam in all_exams:
        allowed_groups = [int(g.strip()) for g in (exam.group or "").split(",") if g.strip().isdigit()]
        exam_has_new_reg = False
        for g in allowed_groups:
            key = (
                str(exam.faculty or "").strip().upper(),
                str(exam.specialty or "").strip().upper(),
                int(exam.course) if exam.course is not None else 0,
                str(exam.stream or "").strip(),
                g
            )
            candidates = student_index.get(key, [])
            for st in candidates:
                if (exam.id, st.id) not in existing_pairs:
                    new_reg = ExamRegistration(
                        student_id=st.id,
                        exam_id=exam.id
                    )
                    db.add(new_reg)
                    existing_pairs.add((exam.id, st.id))
                    total_registrations_created += 1
                    exam_has_new_reg = True
        if exam_has_new_reg or (not exam_ids and not exam_id):
            processed_exam_ids.append(str(exam.id))

    if total_registrations_created == 0:
        return {
            "status": "noop",
            "message": "Няма нови регистрации за изпити. Всички отговарящи студенти са вече разпределени или чакат биометрично одобрение.",
            "new_registrations_created": 0,
            "admin_log_id": None
        }

    action_type = "ALLOCATION_EXECUTION"
    updated_details = f"Успешно разпределение: Брой на новите регистрации: {total_registrations_created}."

    new_log = AdminLog(
        admin_id=admin.id,
        action_type=action_type,
        details=json.dumps({
            "summary": updated_details,
            "exam_ids": processed_exam_ids,
            "total_registrations_created": total_registrations_created,
            "mode": "single" if exam_id else ("batch" if exam_ids else "bulk"),
        }, ensure_ascii=False),
        notification_sent=False
    )
    db.add(new_log)
    db.commit()
    db.refresh(new_log)

    return {
        "status": "success",
        "message": f"Успешно разпределение: Брой на новите регистрации: {total_registrations_created}.",
        "new_registrations_created": total_registrations_created,
        "admin_log_id": str(new_log.id)
    }


@app.post("/hardware/check-door")
def check_door_access(room_number: str, db: Session = Depends(get_db)):
    """
    Хардуерен ендпоинт. Когато PIR зачете движение, FastAPI се закача към ESP32-CAM,
    извлича кадри от VGA стрийма, разпознава студента и проверява дали има изпит в тази зала СЕГА.
    """
    ESP32_IP = os.getenv("ESP32_IP")
    STREAM_URL = f"http://{ESP32_IP}:81/stream"
    STOP_URL = f"http://{ESP32_IP}:81/stop"
    
    print(f"📷 Отваряне на видео стрийма от залата {room_number}...")
    cap = cv2.VideoCapture(STREAM_URL)
    
    if not cap.isOpened():
        raise HTTPException(status_code=503, detail="Неуспешна връзка с ESP32-CAM стрийма.")
    
    start_time = time.time()
    SCAN_TIMEOUT = 10 # Колко секунди максимум ще се опитва да разпознае лице
    
    identified_student = None
    
    # 1. Стрийминг цикъл за улавяне на най-добрия чист кадър
    while (time.time() - start_time) < SCAN_TIMEOUT:
        ret, frame = cap.read()
        if not ret:
            break
            
        # Оптимизация на резолюцията: Намаляваме кадъра 4 пъти за бърз анализ от AI
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
        
        face_locations = face_recognition.face_locations(rgb_small_frame)
        
        if face_locations:
            # Извличаме вектора на намереното лице
            face_encoding = face_recognition.face_encodings(rgb_small_frame, face_locations)[0]
            
            # Търсим лице с разстояние под 0.05 (почти 100% идентичност)
            matched_student = db.query(Student).filter(
                Student.face_embedding.cosine_distance(face_encoding) < 0.05
            ).first()
            
            if matched_student:
                identified_student = matched_student
                break # Хванахме го! Спираме стрийма веднага, за да спестим време
                
    cap.release()
    try: requests.get(STOP_URL, timeout=1) # Спираме камерата хардуерно
    except: pass

    # --- ЛОГИКА ЗА ДОСТЪП ДО ИЗПИТА ---
    if not identified_student:
        return {"access": False, "reason": "Лицето не е разпознато в базата данни."}
        
    # Взимаме текущото време на сървъра в реално време (година 2026)
    current_now = datetime.now()
    
    # Търсим дали този студент е разпределен за изпит в ТАЗИ зала за ДНЕШНИЯ ден
    # Проверяваме през ExamRegistration връзката
    valid_registration = db.query(ExamRegistration).join(Exam).filter(
        ExamRegistration.student_id == identified_student.id,
        Exam.room_number == room_number
        # За защита на дипломната работа можеш да добавиш и филтър по дата:
        # func.date(Exam.date_time) == current_now.date()
    ).first()
    
    # Записваме опита в AccessLog таблицата за историята
    log_entry = AccessLog(
        student_id=identified_student.id,
        room_number=room_number,
        is_granted=True if valid_registration else False
    )
    db.add(log_entry)
    db.commit()
    
    if valid_registration:
        return {
            "access": True,
            "student_name": identified_student.full_name,
            "faculty_number": identified_student.student_id_number,
            "message": f"Достъпът е разрешен за зала {room_number}."
        }
    else:
        return {
            "access": False,
            "student_name": identified_student.full_name,
            "reason": f"Студентът няма активен изпит в зала {room_number} за този времеви прозорец."
        }

@app.get("/api/v1/exams/{room_number}/stream")
async def stream_exam_room(room_number: str, background_tasks: BackgroundTasks, token: str = Query(...)):
    """
    Ендпоинт за Квесторския панел. Приема номер на зала и IP на ESP32.
    Сервира MJPEG стрийм с биометрични резултати в реално време.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("role") not in ["examiner", "superadmin"] and not is_superadmin_user(payload):
            raise HTTPException(status_code=403, detail="Достъпът е отказан.")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")


    if room_number not in ACTIVE_CAMERAS:
        raise HTTPException(
            status_code=400, 
            detail=f"No active ESP32-CAM platform registered for room {room_number}."
        )
    
    esp32_ip = ACTIVE_CAMERAS[room_number]

    if room_number not in CAMERA_TASKS or CAMERA_TASKS[room_number].done():
        # Създаваме задачата в истинския асинхронен event loop на FastAPI за постоянно изпълнение
        task = asyncio.create_task(fetch_frames_from_esp32(room_number, esp32_ip))
        CAMERA_TASKS[room_number] = task
    
    # Връщаме стрийма към потребителя веднага от паметта!
    return StreamingResponse(
        generate_from_memory(room_number),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/api/v1/exams/{room_number}/raw-stream")
async def get_raw_esp32_stream(
    room_number: str,
    token: Optional[str] = Query(None)
):
    """
    Директен достъп до суровия MJPEG стрийм без изискване на токен.
    Използва съществуващия високоскоростен канал от паметта, предотвратявайки
    хардуерно блокиране на ESP32 DMA буферите при паралелни сокети.
    """
    if room_number not in ACTIVE_CAMERAS:
        raise HTTPException(
            status_code=404,
            detail=f"Няма регистрирана активна ESP32 камера за зала {room_number}."
        )

    esp32_ip = ACTIVE_CAMERAS[room_number]
    if room_number not in CAMERA_TASKS or CAMERA_TASKS[room_number].done():
        CAMERA_TASKS[room_number] = asyncio.create_task(fetch_frames_from_esp32(room_number, esp32_ip))

    return StreamingResponse(
        generate_from_memory(room_number),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/api/v1/exams/{room_number}/events")
async def stream_exam_room_events(
    room_number: str,
    request: fastapi.Request,
    token: Optional[str] = Query(None)
):
    """
    Server-Sent Events (SSE) канал за залата в реално време.
    Заменя постоянното HTTP запитване (polling) с push събития:
      - camera_status: промяна онлайн/офлайн на ESP32
      - biometric_status: разпознаване на лице и статус на допускане
      - roster_update: събитие за допуснат студент (презареждане на списъка)
    Изпраща ': ping' на всеки 15 секунди, за да държи връзката жива през ngrok и reverse proxies.
    """
    auth_token = token or request.cookies.get("examiner_token") or request.cookies.get("admin_token")
    if not auth_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            auth_token = auth_header[7:]

    if not auth_token:
        raise HTTPException(status_code=401, detail="Authentication token required.")

    try:
        payload = jwt.decode(auth_token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("role") not in ["examiner", "superadmin"] and not is_superadmin_user(payload):
            raise HTTPException(status_code=403, detail="Достъпът е отказан.")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    queue = subscribe_room_events(room_number)

    async def event_generator():
        try:
            # 1. Моментално начално състояние (Snapshot)
            esp32_ip = ACTIVE_CAMERAS.get(room_number)
            health = CAMERA_HEALTH.get(room_number, {})
            is_online = bool(
                esp32_ip and
                health.get("is_online", False) and
                (time.time() - health.get("last_frame_time", 0) < 8.0)
            )
            init_cam = {
                "room_number": room_number,
                "armed": is_online,
                "esp32_ip": esp32_ip,
                "is_online": is_online
            }
            yield f"event: camera_status\ndata: {json.dumps(init_cam)}\n\n"

            ai_state = AI_ROOM_STATES.get(room_number, {})
            init_bio = {
                "student_name": ai_state.get("student_name", ""),
                "faculty_number": ai_state.get("faculty_number", ""),
                "status_text": ai_state.get("status_text", "Очакване на студент..."),
                "status_type": ai_state.get("status_type", "idle")
            }
            yield f"event: biometric_status\ndata: {json.dumps(init_bio)}\n\n"

            # 2. Непрекъснато слушане на събития с 15s keep-alive пинг
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    evt_name = msg.get("event", "message")
                    evt_data = json.dumps(msg.get("data", {}))
                    yield f"event: {evt_name}\ndata: {evt_data}\n\n"
                except asyncio.TimeoutError:
                    # SSE Keep-alive коментар
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe_room_events(room_number, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )



# def get_room_live_stream(room_number: str):
#     """
#     Ендпоинт, който админ панелът (Frontend-а) може да зареди директно в един <img> таг!
#     Пример: <img src="http://localhost:8000/api/v1/exams/1151/stream" />
#     """
#     return StreamingResponse(
#         generate_live_frames(room_number),
#         media_type="multipart/x-mixed-replace; boundary=frame"
#     )

# ==========================================================
# EXAMINER LIVE HALL MONITOR & MULTI-ROOM ORCHESTRATION APIS
# ==========================================================

@app.get("/examiner/lobby", response_class=HTMLResponse)
def get_examiner_lobby_page(request: fastapi.Request, response: Response):
    """ Връща страницата за избор на активна изпитна зала от квестори """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return templates.TemplateResponse(
        request=request,
        name="examiner_lobby.html",
        context={"request": request}
    )

@app.get("/api/v1/examiner/rooms-overview")
def get_examiner_rooms_overview(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_examiner)
):
    """
    Връща списък с всички активни изпитни зали, състояние на камерата,
    брой допуснати и чакащи студенти, както и информация кой квестор наблюдава залата в реално време.
    """
    _cleanup_expired_assignments()

    # 1. Извличаме всички уникални зали от планираните изпити
    exam_rooms = db.query(Exam.room_number).distinct().all()
    all_rooms_set = {r[0] for r in exam_rooms if r[0]}

    # Добавяме и зали, регистрирани хардуерно от ESP32 камерите
    for r in ACTIVE_CAMERAS.keys():
        if r:
            all_rooms_set.add(r)

    # Подреждаме залите възходящо
    sorted_rooms = sorted(list(all_rooms_set))
    now = datetime.now()

    rooms_list = []
    total_all_students = 0
    total_all_admitted = 0
    total_cameras_online = 0

    for room_num in sorted_rooms:
        # Търсим днешен изпит или най-скоро планирания изпит за тази зала
        primary_exam = db.query(Exam).filter(
            Exam.room_number == room_num,
            func.date(Exam.date_time) == now.date()
        ).first()

        if not primary_exam:
            primary_exam = db.query(Exam).filter(
                Exam.room_number == room_num
            ).order_by(Exam.date_time.desc()).first()

        total_expected = 0
        admitted_count = 0
        subject = "Няма активен изпит"
        lecturer = "—"
        exam_date_time = "—"
        session_type = "—"

        if primary_exam:
            subject = primary_exam.subject
            lecturer = primary_exam.lecturer or "—"
            if primary_exam.date_time:
                exam_date_time = primary_exam.date_time.strftime("%d.%m.%Y %H:%M")
            if primary_exam.session_type:
                session_type = primary_exam.session_type.value if hasattr(primary_exam.session_type, 'value') else str(primary_exam.session_type)

            regs = db.query(ExamRegistration).filter(ExamRegistration.exam_id == primary_exam.id).all()
            total_expected = len(regs)
            admitted_count = sum(1 for r in regs if r.is_admitted)

        total_all_students += total_expected
        total_all_admitted += admitted_count

        # Проверка за камера
        esp32_ip = ACTIVE_CAMERAS.get(room_num)
        health = CAMERA_HEALTH.get(room_num, {})
        camera_online = bool(
            esp32_ip and
            health.get("is_online", False) and
            (time.time() - health.get("last_frame_time", 0) < 8.0)
        )
        if camera_online:
            total_cameras_online += 1

        # Квесторско заключване
        assignment = ACTIVE_EXAMINER_ASSIGNMENTS.get(room_num)
        is_occupied = assignment is not None
        my_id = str(current_user.get("sub"))
        is_occupied_by_me = is_occupied and assignment["examiner_id"] == my_id
        can_claim = (not is_occupied) or is_occupied_by_me

        admission_ratio_pct = round((admitted_count / total_expected * 100), 1) if total_expected > 0 else 0.0

        rooms_list.append({
            "room_number": room_num,
            "subject": subject,
            "lecturer": lecturer,
            "date_time": exam_date_time,
            "session_type": session_type,
            "total_expected": total_expected,
            "admitted_count": admitted_count,
            "waiting_count": max(0, total_expected - admitted_count),
            "admission_ratio_pct": admission_ratio_pct,
            "camera_online": camera_online,
            "esp32_ip": esp32_ip,
            "is_occupied": is_occupied,
            "is_occupied_by_me": is_occupied_by_me,
            "can_claim": can_claim,
            "assigned_examiner": assignment["examiner_name"] if is_occupied else None,
            "assigned_examiner_email": assignment.get("examiner_email") if is_occupied else None,
        })

    return {
        "rooms": rooms_list,
        "metrics": {
            "total_rooms": len(sorted_rooms),
            "active_rooms": len([r for r in rooms_list if r["total_expected"] > 0]),
            "total_students": total_all_students,
            "total_admitted": total_all_admitted,
            "cameras_online": total_cameras_online
        }
    }


@app.post("/api/v1/examiner/rooms/{room_number}/claim")
def claim_exam_room(
    room_number: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_examiner)
):
    """
    Заявява ексклузивно наблюдение на дадена зала от квестор (1-Examiner Lock).
    Ако залата вече се наблюдава от друг квестор, връща 409 Conflict.
    """
    _cleanup_expired_assignments()
    my_id = str(current_user.get("sub"))

    if room_number in ACTIVE_EXAMINER_ASSIGNMENTS:
        existing = ACTIVE_EXAMINER_ASSIGNMENTS[room_number]
        if existing["examiner_id"] != my_id:
            raise HTTPException(
                status_code=409,
                detail=f"Залата вече се наблюдава от квестор: {existing['examiner_name']}"
            )
        # Ако е същият квестор, просто обновяваме heartbeat
        existing["last_heartbeat"] = time.time()
        return {
            "status": "claimed",
            "room_number": room_number,
            "examiner_name": existing["examiner_name"],
            "claimed_at": existing["claimed_at"]
        }

    # Намираме името и имейла на квестора
    examiner_name = "Квестор"
    examiner_email = ""
    if is_superadmin_user(current_user):
        admin = db.query(Admin).filter(Admin.id == my_id).first()
        if admin:
            examiner_name = f"{admin.full_name} (Superadmin)"
            examiner_email = admin.email
    else:
        examiner = db.query(Examiner).filter(Examiner.id == my_id).first()
        if examiner:
            examiner_name = examiner.full_name
            examiner_email = examiner.email

    # Ако квесторът е държал друга зала, освобождаваме старата
    for other_room, data in list(ACTIVE_EXAMINER_ASSIGNMENTS.items()):
        if data["examiner_id"] == my_id and other_room != room_number:
            del ACTIVE_EXAMINER_ASSIGNMENTS[other_room]

    now_ts = time.time()
    ACTIVE_EXAMINER_ASSIGNMENTS[room_number] = {
        "examiner_id": my_id,
        "examiner_name": examiner_name,
        "examiner_email": examiner_email,
        "claimed_at": now_ts,
        "last_heartbeat": now_ts
    }

    return {
        "status": "claimed",
        "room_number": room_number,
        "examiner_name": examiner_name,
        "claimed_at": now_ts
    }


@app.post("/api/v1/examiner/rooms/{room_number}/heartbeat")
def heartbeat_exam_room(
    room_number: str,
    current_user: dict = Depends(get_current_examiner)
):
    """ Поддържа активно квесторското заключване за залата """
    _cleanup_expired_assignments()
    my_id = str(current_user.get("sub"))

    if room_number in ACTIVE_EXAMINER_ASSIGNMENTS:
        assigned = ACTIVE_EXAMINER_ASSIGNMENTS[room_number]
        if assigned["examiner_id"] == my_id:
            assigned["last_heartbeat"] = time.time()
            return {"status": "alive", "room_number": room_number}

    return {"status": "not_claimed", "room_number": room_number}


@app.post("/api/v1/examiner/rooms/{room_number}/release")
def release_exam_room(
    room_number: str,
    current_user: dict = Depends(get_current_examiner)
):
    """ Освобождава квесторското заключване за залата """
    my_id = str(current_user.get("sub"))

    if room_number in ACTIVE_EXAMINER_ASSIGNMENTS:
        assigned = ACTIVE_EXAMINER_ASSIGNMENTS[room_number]
        if assigned["examiner_id"] == my_id or is_superadmin_user(current_user):
            del ACTIVE_EXAMINER_ASSIGNMENTS[room_number]
            return {"status": "released", "room_number": room_number}

    return {"status": "noop", "room_number": room_number}


@app.get("/api/v1/exams/{room_number}/roster")
def get_exam_room_roster(
    room_number: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_examiner)
):
    """
    Връща пълния списък от очаквани/допуснати студенти за изпита в тази зала
    с техните 3 цветови състояния (Сив, Зелен, Червен), телеметрия и таймлайн.
    """
    _cleanup_expired_assignments()
    assigned_info = ACTIVE_EXAMINER_ASSIGNMENTS.get(room_number)

    now = datetime.now()
    exam = db.query(Exam).filter(
        Exam.room_number == room_number,
        func.date(Exam.date_time) == now.date()
    ).first()

    if not exam:
        exam = db.query(Exam).filter(
            Exam.room_number == room_number
        ).order_by(Exam.date_time.desc()).first()

    if not exam:
        return {
            "exam_info": {
                "id": None,
                "room_number": room_number,
                "subject": "Няма активен изпит",
                "lecturer": "—",
                "date_time": "—",
                "session_type": "—"
            },
            "assigned_examiner": assigned_info.get("examiner_name") if assigned_info else None,
            "metrics": {
                "total_expected": 0,
                "total_admitted": 0,
                "total_waiting": 0,
                "total_unpermitted": 0,
                "admission_ratio_pct": 0.0
            },
            "students": [],
            "recent_admissions": []
        }

    # Взимаме регистрациите за този изпит
    registrations = (
        db.query(ExamRegistration)
        .join(Student, ExamRegistration.student_id == Student.id)
        .filter(ExamRegistration.exam_id == exam.id)
        .order_by(Student.full_name.asc())
        .all()
    )

    students_payload = []
    admitted_list = []

    for reg in registrations:
        st = reg.student
        has_bio = bool(st.face_embedding is not None)
        is_approved = (st.status == "APPROVED")
        is_admitted = bool(reg.is_admitted)

        # Логика за 3-те живи цвята:
        # Green: Допуснат в залата
        # Red: Няма право / непълна биометрия / не е одобрен
        # Gray: Одобрен студент, чакащ на входа
        if is_admitted:
            color_state = "green"
        elif (not is_approved) or (not has_bio):
            color_state = "red"
        else:
            color_state = "gray"

        adm_time_str = reg.admitted_at.strftime("%H:%M:%S") if reg.admitted_at else None

        student_data = {
            "student_id": str(st.id),
            "registration_id": str(reg.id),
            "full_name": st.full_name,
            "student_id_number": st.student_id_number,
            "faculty_number": st.student_id_number,
            "email": st.email,
            "faculty": st.faculty or "ФКСУ",
            "specialty": st.specialty or "КСИ",
            "course": st.course or 1,
            "stream": st.stream or "1",
            "group": st.group or "1",
            "biometric_status": st.status,
            "has_face_embedding": has_bio,
            "is_admitted": is_admitted,
            "admitted_at": adm_time_str,
            "color_state": color_state
        }
        students_payload.append(student_data)

        if is_admitted:
            admitted_list.append(student_data)

    total_expected = len(students_payload)
    total_admitted = sum(1 for s in students_payload if s["is_admitted"])
    total_unpermitted = sum(1 for s in students_payload if s["color_state"] == "red")
    total_waiting = sum(1 for s in students_payload if s["color_state"] == "gray")
    admission_ratio_pct = round((total_admitted / total_expected * 100), 1) if total_expected > 0 else 0.0

    # Сортираме последните допуснати за хронологичния таймлайн
    recent_admissions = sorted(
        admitted_list,
        key=lambda s: s.get("admitted_at") or "",
        reverse=True
    )[:15]

    return {
        "exam_info": {
            "id": str(exam.id),
            "room_number": exam.room_number,
            "subject": exam.subject,
            "lecturer": exam.lecturer or "—",
            "date_time": exam.date_time.strftime("%d.%m.%Y %H:%M") if exam.date_time else "—",
            "session_type": exam.session_type.value if hasattr(exam.session_type, 'value') else str(exam.session_type)
        },
        "assigned_examiner": assigned_info.get("examiner_name") if assigned_info else None,
        "metrics": {
            "total_expected": total_expected,
            "total_admitted": total_admitted,
            "total_waiting": total_waiting,
            "total_unpermitted": total_unpermitted,
            "admission_ratio_pct": admission_ratio_pct
        },
        "students": students_payload,
        "recent_admissions": recent_admissions
    }


@app.post("/api/v1/exams/{room_number}/admit/{student_id}")
def admit_student_manual(
    room_number: str,
    student_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_examiner)
):
    """
    Ръчно допускане на студент от квестора (ин-ап модал или чип).
    Маркира is_admitted = True и записва GRANTED събитие в AccessLog.
    """
    # Намираме студента по UUID или фак. номер
    student = None
    try:
        student = db.query(Student).filter(Student.id == student_id).first()
    except Exception:
        pass
    if not student:
        student = db.query(Student).filter(Student.student_id_number == student_id.strip()).first()

    if not student:
        raise HTTPException(status_code=404, detail="Студентът не е намерен.")

    # 1. Първо проверяваме дали студентът вече има регистрация за изпит в тази зала
    reg = db.query(ExamRegistration).join(Exam).filter(
        ExamRegistration.student_id == student.id,
        Exam.room_number == room_number
    ).first()

    now_ts = datetime.now().astimezone()
    if reg:
        reg.is_admitted = True
        reg.admitted_at = now_ts
    else:
        # 2. Ако няма, намираме изпита за създаване на нова регистрация
        now = datetime.now()
        exam = db.query(Exam).filter(
            Exam.room_number == room_number,
            func.date(Exam.date_time) == now.date()
        ).first()

        if not exam:
            exam = db.query(Exam).filter(
                Exam.room_number == room_number
            ).order_by(Exam.date_time.desc()).first()

        if not exam:
            raise HTTPException(status_code=404, detail=f"Няма активен изпит в зала {room_number}.")

        reg = ExamRegistration(
            student_id=student.id,
            exam_id=exam.id,
            is_admitted=True,
            admitted_at=now_ts
        )
        db.add(reg)

    log_entry = AccessLog(
        student_id=student.id,
        location=room_number,
        status="GRANTED"
    )
    db.add(log_entry)
    db.commit()

    emit_room_event(room_number, "roster_update", {
        "room_number": room_number,
        "student_id": str(student.id),
        "student_name": student.full_name,
        "faculty_number": student.student_id_number,
        "action": "manual_admit"
    })

    return {
        "status": "admitted",
        "student_id": str(student.id),
        "student_name": student.full_name,
        "faculty_number": student.student_id_number,
        "admitted_at": now_ts.strftime("%H:%M:%S")
    }


@app.get("/api/v1/exams/{room_number}/monitor", response_class=HTMLResponse)
def get_monitor_page(room_number: str, request: fastapi.Request, response: Response):
    """ Връща страницата за жив мониторинг на залата """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"

    return templates.TemplateResponse(
        request=request, 
        name="monitor.html", 
        context={"request": request, "room_number": room_number}
    )


@app.post("/api/v1/exams/{room_number}/force-register")
def force_register_student_to_exam(
    room_number: str, 
    student_id_number: str = Form(...), 
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_examiner) # Позволява Bearer хедър, токен или куки
):
    """ Академичен модул: Принудително записване и допускане на студент за изпит в текущата зала """
    # 1. Търсим студента
    student = db.query(Student).filter(Student.student_id_number == student_id_number.strip()).first()
    if not student:
        raise HTTPException(status_code=404, detail="Студент с такъв факултетен номер не съществува.")

    # 2. Намираме изпита за тази зала, провеждащ се ДНЕС или най-скоро планирания
    current_date = datetime.now().date()
    current_exam = db.query(Exam).filter(
        Exam.room_number == room_number,
        func.date(Exam.date_time) == current_date
    ).first()

    if not current_exam:
        current_exam = db.query(Exam).filter(Exam.room_number == room_number).order_by(Exam.date_time.desc()).first()

    if not current_exam:
        raise HTTPException(status_code=404, detail=f"Няма планиран изпит в зала {room_number}.")

    now_ts = datetime.now().astimezone()

    # 3. Проверяваме дали вече няма регистрация
    already_registered = db.query(ExamRegistration).filter(
        ExamRegistration.student_id == student.id,
        ExamRegistration.exam_id == current_exam.id
    ).first()

    if already_registered:
        if not already_registered.is_admitted:
            already_registered.is_admitted = True
            already_registered.admitted_at = now_ts
            log_entry = AccessLog(student_id=student.id, location=room_number, status="GRANTED")
            db.add(log_entry)
            db.commit()
            emit_room_event(room_number, "roster_update", {
                "room_number": room_number,
                "student_id": str(student.id),
                "student_name": student.full_name,
                "faculty_number": student.student_id_number,
                "action": "force_register"
            })
            return {"status": "success", "message": f"Студентът {student.full_name} вече имаше регистрация и беше допуснат в зала {room_number}."}
        return {"status": "already_done", "message": "Студентът вече има валидна регистрация и е допуснат."}

    # 4. Създаваме принудителна нова регистрация с допуск
    new_registration = ExamRegistration(
        student_id=student.id,
        exam_id=current_exam.id,
        is_admitted=True,
        admitted_at=now_ts
    )
    db.add(new_registration)
    log_entry = AccessLog(student_id=student.id, location=room_number, status="GRANTED")
    db.add(log_entry)
    db.commit()

    emit_room_event(room_number, "roster_update", {
        "room_number": room_number,
        "student_id": str(student.id),
        "student_name": student.full_name,
        "faculty_number": student.student_id_number,
        "action": "force_register"
    })

    print(f"[Спешен Допуск] Квесторът записа студент {student.full_name} за изпит в зала {room_number}")
    return {"status": "success", "message": f"Успешно извънредно записване на {student.full_name} за дисциплина: {current_exam.subject}."}

@app.post("/students/validate")
async def student_submit_for_verification(
    status: str = Form(...),
    file: UploadFile = File(...),
    student_book_file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Мобилен ендпоинт: Приема снимката след Liveness проверка (и опционално студентска книжка),
    записва ги в MinIO и слага студента в опашката за одобрение от администратор.
    """

    ALLOWED_EXTENSIONS = ["image/jpeg", "image/png", "image/jpg", "image/webp"]

    if status != "LIVENESS_PASSED":
        raise HTTPException(status_code=400, detail="Liveness check failed. Cannot proceed with verification.")
    # 1. Защита на достъпа: студенти или Superadmin
    if current_user.get("role") not in ("student", "superadmin") and not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied.")

    if file.content_type not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type! Only images are allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    if student_book_file and student_book_file.content_type not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid student book image format! Only images are allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    student_id = current_user.get("sub")
    student = db.query(Student).filter(Student.id == student_id).first()
    
    if not student:
        if is_superadmin_user(current_user):
            contents = await file.read()
            photo_url = upload_photo_to_cloud(
                file_data=contents,
                object_name=f"superadmin_{int(time.time())}{os.path.splitext(file.filename)[1]}",
                content_type=file.content_type
            )
            admin_uuid = None
            try:
                admin_uuid = uuid.UUID(student_id) if student_id else None
            except Exception:
                pass
            db.add(AdminLog(
                admin_id=admin_uuid,
                action_type="SUPERADMIN_LIVENESS_VERIFIED",
                details=f"Superadmin submitted liveness photo: {photo_url}"
            ))
            db.commit()
            return {"status": "already_approved", "message": "Superadmin profile is permanently verified."}
        raise HTTPException(status_code=404, detail="Student not found.")

        
    if student.status == "APPROVED":
        return {"status": "already_approved", "message": "Profile is already approved and verified."}

    try:
        contents = await file.read()
        ts = int(time.time())
        photo_url = upload_photo_to_cloud(
            file_data=contents,
            object_name=f"{student.student_id_number}_{ts}{os.path.splitext(file.filename)[1]}",
            content_type=file.content_type
        )

        book_photo_url = None
        if student_book_file:
            book_contents = await student_book_file.read()
            book_photo_url = upload_photo_to_cloud(
                file_data=book_contents,
                object_name=f"{student.student_id_number}_book_{ts}{os.path.splitext(student_book_file.filename or '.jpg')[1]}",
                content_type=student_book_file.content_type or "image/jpeg"
            )
            student.student_book_photo_path = book_photo_url

        # 3. Обновяване на статуса в базата данни
        student.status = "PENDING_APPROVAL" 
        student.photo_path = photo_url
        db.commit()

        return {
            "status": "success",
            "message": "Image uploaded successfully. Your profile is now pending admin approval.",
            "photo_url": photo_url,
            "student_book_photo_url": book_photo_url
        }

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Грешка при запис в системата: {str(e)}")


@app.post("/students/upload-verification-docs")
async def student_upload_verification_docs(
    face_photo: UploadFile = File(...),
    student_book_photo: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Двуснимково качване на верификационни документи:
    1. Лицево биометрично селфи
    2. Първа страница от студентската книжка (официален документ с печат)
    """
    ALLOWED_EXTENSIONS = ["image/jpeg", "image/png", "image/jpg", "image/webp"]

    if current_user.get("role") not in ("student", "superadmin") and not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Access denied.")

    for uploaded_file, label in [(face_photo, "Биометрична лицева снимка"), (student_book_photo, "Студентска книжка")]:
        if uploaded_file.content_type not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Невалиден файлов формат за {label}! Разрешени формати: {', '.join(ALLOWED_EXTENSIONS)}"
            )

    student_id = current_user.get("sub")
    student = db.query(Student).filter(Student.id == student_id).first()

    if not student:
        if is_superadmin_user(current_user):
            return {"status": "already_approved", "message": "Superadmin profile is permanently verified."}
        raise HTTPException(status_code=404, detail="Student not found.")

    if student.status == "APPROVED":
        return {"status": "already_approved", "message": "Profile is already approved and verified."}

    try:
        ts = int(time.time())
        face_contents = await face_photo.read()
        book_contents = await student_book_photo.read()

        face_url = upload_photo_to_cloud(
            file_data=face_contents,
            object_name=f"{student.student_id_number}_face_{ts}{os.path.splitext(face_photo.filename or '.jpg')[1]}",
            content_type=face_photo.content_type or "image/jpeg"
        )
        book_url = upload_photo_to_cloud(
            file_data=book_contents,
            object_name=f"{student.student_id_number}_book_{ts}{os.path.splitext(student_book_photo.filename or '.jpg')[1]}",
            content_type=student_book_photo.content_type or "image/jpeg"
        )

        student.status = "PENDING_APPROVAL"
        student.photo_path = face_url
        student.student_book_photo_path = book_url
        db.commit()

        return {
            "status": "success",
            "message": "Документите са качени успешно и очакват преглед от администратор.",
            "photo_url": face_url,
            "student_book_photo_url": book_url
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Грешка при качване на документите: {str(e)}")


@app.post("/admins/approve-student/{student_id}")
async def approve_student_biometrics(
    student_id: str,
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_admin)
):
    """
    Администраторски ендпоинт: Взима снимката директно по записания път на студента,
    извлича 128-измерния вектор и го одобрява. Без местене на файлове!
    """
    # 1. Намираме студента
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Студентът не е намерен.")
    
    if student.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=400, detail="Този студент не чака одобрение на биометрия.")

    # 2. Извличаме чистия object name (Key) от записания URL
    # Пример: ако student.photo_url е "/access-control-bucket/121221001_1718872205.jpg"
    # махаме "/access-control-bucket/" отпред, за да получим само името на файла за S3
    prefix = f"/{BUCKET_NAME}/"
    if student.photo_path.startswith(prefix):
        object_name = student.photo_path[len(prefix):]
    else:
        # Застраховка, ако е записано само името на файла
        object_name = student.photo_path.lstrip("/")

    try:
        # 3. Сваляме байтовете от MinIO по точното име на файла
        file_data = get_photo_from_cloud(object_name)

        # 4. Зареждаме изображението и извличаме 128-измерния вектор
        image = face_recognition.load_image_file(io.BytesIO(file_data))
        face_encodings = face_recognition.face_encodings(image)
        
        if len(face_encodings) == 0:
            raise HTTPException(status_code=400, detail="No face detected in the image.")
        
        # Взимаме първото лице и го правим на списък за face_embedding
        student_embedding = face_encodings[0].tolist()

        # 5. Обновяваме студента в Postgres
        student.face_embedding = student_embedding
        student.status = "APPROVED"

        # 6. Лог за администратора
        new_log = AdminLog(
            admin_id=current_admin['sub'],
            action_type="STUDENT_APPROVE",
            details=f"Одобрен студент с фак. номер {student.student_id_number}. Генериран face_embedding.",
            notification_sent=False
        )
        db.add(new_log)
        db.commit()

        return {
            "status": "success",
            "message": f"Student {student.student_id_number} approved and face_embedding saved successfully."
        }

    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Approval failed: {str(e)}")


@app.post("/admins/reject-student/{student_id}")
def reject_student_biometrics(
    student_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_admin)
):
    admin = db.query(Admin).filter(Admin.id == current_admin['sub']).first()
    if not admin or not admin.is_verified:
        raise HTTPException(status_code=403, detail="Unauthorized access. Admin privileges required.")

    reason = (payload or {}).get("reason", "")
    if len(reason.strip()) < 3:
        raise HTTPException(status_code=400, detail="Reason is required.")

    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Студентът не е намерен.")
    if student.status != "PENDING_APPROVAL":
        raise HTTPException(status_code=400, detail="Този студент не чака одобрение на биометрия.")

    student.status = "REJECTED"
    student.face_embedding = None

    db.add(AdminLog(
        admin_id=admin.id,
        action_type="STUDENT_REJECT",
        details=f"Студент {student.student_id_number} е отхвърлен. Причина: {reason.strip()}",
        notification_sent=False,
    ))
    db.commit()

    return {"status": "success", "message": f"Student {student.student_id_number} rejected successfully."}

@app.post("/api/v1/exams/register-camera")
async def register_camera(data: CameraRegisterSchema):
    """
    Автоматичен ендпоинт за ESP32 устройствата.
    При включване платката казва в коя зала се намира и какво IP е взела.
    Поддържа и периодично сърцебиене (heartbeat) без прекъсване на активния стрийм.
    """
    current_ip = ACTIVE_CAMERAS.get(data.room_number)
    old_task = CAMERA_TASKS.get(data.room_number)
    task_alive = old_task and not old_task.done()

    # Ако камерата вече е регистрирана със същото IP и фоновата задача работи нормално,
    # не я рестартираме, а само обновяваме здравето и времето
    if current_ip == data.esp32_ip and task_alive:
        CAMERA_HEALTH[data.room_number]["last_frame_time"] = time.time()
        CAMERA_HEALTH[data.room_number]["is_online"] = True
        emit_room_event(data.room_number, "camera_status", {
            "room_number": data.room_number,
            "armed": True,
            "is_online": True,
            "esp32_ip": data.esp32_ip
        })
        return {
            "status": "already_active",
            "room_number": data.room_number,
            "esp32_ip": data.esp32_ip
        }

    # При промяна на IP или неактивна задача, прекратяваме старата задача
    if old_task and not old_task.done():
        old_task.cancel()

    ACTIVE_CAMERAS[data.room_number] = data.esp32_ip
    CAMERA_HEALTH[data.room_number] = {
        "last_frame_time": time.time(),
        "is_online": True,
        "esp32_ip": data.esp32_ip
    }
    CAMERA_TASKS[data.room_number] = asyncio.create_task(fetch_frames_from_esp32(data.room_number, data.esp32_ip))

    emit_room_event(data.room_number, "camera_status", {
        "room_number": data.room_number,
        "armed": True,
        "is_online": True,
        "esp32_ip": data.esp32_ip
    })

    print(f"[Hardware register] Room {data.room_number} is now linked with ESP32 at: {data.esp32_ip}")
    return {
        "status": "registered", 
        "room_number": data.room_number, 
        "esp32_ip": data.esp32_ip
    }


@app.get("/api/v1/exams/{room_number}/camera-status")
def get_exam_room_camera_status(room_number: str):
    """Връща дали залата има регистрирана и работеща в момента активна камера."""
    esp32_ip = ACTIVE_CAMERAS.get(room_number)
    health = CAMERA_HEALTH.get(room_number, {})
    is_online = bool(
        esp32_ip and 
        health.get("is_online", False) and 
        (time.time() - health.get("last_frame_time", 0) < 8.0)
    )
    return {
        "room_number": room_number,
        "armed": is_online,
        "esp32_ip": esp32_ip,
        "is_online": is_online
    }

@app.get("/api/v1/exams/{room_number}/status")
async def get_exam_room_biometric_status(
    room_number: str,
    current_user: dict = Depends(get_current_examiner)
):
    """
    Ендпоинт за Квесторския панел. 
    Връща JSON с името, факултетния номер и статуса на засичане извън видеото.
    """


    if room_number not in AI_ROOM_STATES:
        return {
            "student_name": "—",
            "faculty_number": "—",
            "status_text": "Няма активна връзка с терминала в залата",
            "status_type": "idle"
        }
    
    state = AI_ROOM_STATES[room_number]
    return {
        "student_name": state.get("student_name", ""),
        "faculty_number": state.get("faculty_number", ""),
        "status_text": state.get("status_text", "Очакване на обект..."),
        "status_type": state.get("status_type", "idle")
    }


@app.get("/students/my-registrations")
def get_my_exam_registrations(
    impersonate_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    1. Извлича всички текущи изпитни регистрации за логнатия студент или имперсонирания студент.
    За Superadmin (когато не е избран конкретен студент) връща наличните планирани изпити за лесно тестване на мобилния интерфейс.
    """
    if current_user.get("role") not in ("student", "superadmin") and not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Достъпът е разрешен само за студенти.")

    if impersonate_id:
        if not is_superadmin_user(current_user):
            raise HTTPException(status_code=403, detail="Само Superadmin може да преглежда изпити на друг студент.")
        student_id = impersonate_id
    else:
        student_id = current_user.get("sub")
    
    # Правим JOIN между ExamRegistration и Exam, за да изкараме пълните детайли
    registrations = db.query(ExamRegistration).join(Exam).filter(
        ExamRegistration.student_id == student_id
    ).order_by(Exam.date_time.asc()).all()

    if registrations:
        return [
            {
                "registration_id": str(reg.id),
                "exam_id": str(reg.exam.id),
                "subject": reg.exam.subject,
                "lecturer": reg.exam.lecturer,
                "room_number": reg.exam.room_number,
                "date_time": reg.exam.date_time.isoformat() if reg.exam.date_time else None,
                "session_type": reg.exam.session_type.value if reg.exam.session_type else None,
                "faculty": reg.exam.faculty or "",
                "specialty": reg.exam.specialty or "",
                "course": reg.exam.course or 1,
                "stream": str(reg.exam.stream or ""),
                "group": str(reg.exam.group or ""),
            }
            for reg in registrations
        ]

    # За Superadmin в глобален режим (без избран студент) връщаме ВСИЧКИ планирани изпити от системата
    if is_superadmin_user(current_user) and not impersonate_id:
        exams = db.query(Exam).order_by(Exam.date_time.asc()).all()
        return [
            {
                "registration_id": f"admin-{exam.id}",
                "exam_id": str(exam.id),
                "subject": exam.subject,
                "lecturer": exam.lecturer or "Не е указан",
                "room_number": exam.room_number,
                "date_time": exam.date_time.isoformat() if exam.date_time else None,
                "session_type": exam.session_type.value if exam.session_type else None,
                "faculty": exam.faculty or "",
                "specialty": exam.specialty or "",
                "course": exam.course or 1,
                "stream": str(exam.stream or ""),
                "group": str(exam.group or ""),
            }
            for exam in exams
        ]

    return []

@app.get("/students/upcoming-resits")
def get_upcoming_resits_and_liquidations(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    2. Извлича наличните поправителни и ликвидационни изпити в прозорец от 20 дни напред.
    """
    if current_user.get("role") not in ("student", "superadmin") and not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Достъпът е забранен.")

    now = datetime.now(timezone)
    end_window = now + timedelta(days=20)

    # Филтрираме изпитите, които са RESIT (поправителна) или LIQUIDATION (ликвидационна) в близките 20 дни
    upcoming_exams = db.query(Exam).filter(
        Exam.session_type.in_([SessionType.RESIT, SessionType.LIQUIDATION]),
        Exam.date_time >= now,
        Exam.date_time <= end_window
    ).order_by(Exam.date_time.asc()).all()

    return [
        {
            "id": str(exam.id),
            "subject": exam.subject,
            "lecturer": exam.lecturer,
            "room_number": exam.room_number,
            "date_time": exam.date_time.isoformat(),
            "course": exam.course,
            "group": exam.group,
            "session_type": exam.session_type.value
        }
        for exam in upcoming_exams
    ]


@app.post("/students/request-insert")
async def request_exam_insertion(
    exam_id: str = Form(...),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    3. Подаване на заявка за служебно записване на изпит.
    Ако курсът на изпита се разминава с курса на студента, системата изисква снимка на протокол.
    """
    if current_user.get("role") not in ("student", "superadmin") and not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Достъпът е забранен.")

    student_id = current_user.get("sub")
    student = db.query(Student).filter(Student.id == student_id).first()
    exam = db.query(Exam).filter(Exam.id == exam_id).first()

    if not exam:
        raise HTTPException(status_code=404, detail="Изпитът не беше намерен.")

    if not student:
        if is_superadmin_user(current_user):
            admin = db.query(Admin).filter(Admin.id == student_id, Admin.is_superadmin == True).first()
            admin_uuid = admin.id if admin else None
            db.add(AdminLog(
                admin_id=admin_uuid,
                action_type="SUPERADMIN_EXAM_INSERT",
                details=f"Superadmin requested exam insert for {exam.subject} in room {exam.room_number}."
            ))
            db.commit()
            return {"status": "success", "message": "Успешно записване за изпита (Superadmin)."}
        raise HTTPException(status_code=404, detail="Студентът не беше намерен.")

    # Проверка дали вече е регистриран за този изпит
    already_registered = db.query(ExamRegistration).filter(
        ExamRegistration.student_id == student_id,
        ExamRegistration.exam_id == exam_id
    ).first()
    if already_registered:
        raise HTTPException(status_code=400, detail="Вие вече сте регистриран за този изпит.")
        
    # Ако студентът е 4-ти курс, а изпитът е за 3-ти курс (невзет изпит от минала година)
    has_course_mismatch = (exam.course != student.course)
    protocol_cloud_path = None

    if has_course_mismatch:
        if not file:
            raise HTTPException(
                status_code=400, 
                detail="Разминаване в курсовете! Задължително трябва да прикачите снимка на индивидуален изпитен протокол."
            )
        
        # Валидация на типа файл за снимка
        if file.content_type not in ["image/jpeg", "image/png", "image/jpg"]:
            raise HTTPException(status_code=400, detail="Невалиден формат на документа. Качете JPEG или PNG снимка.")
        
        # Качваме снимката на протокола в MinIO кофата
        try:
            contents = await file.read()
            object_name = f"protocols/{student.student_id_number}_exam_{exam.id}_{int(time.time())}{os.path.splitext(file.filename)[1]}"
            protocol_cloud_path = upload_photo_to_cloud(
                file_data=contents,
                object_name=object_name,
                content_type=file.content_type
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Проблем при качване на документа в MinIO: {str(e)}")

    # Директно записваме студента в сесията (за PoC модела)
    new_registration = ExamRegistration(
        student_id=student.id,
        exam_id=exam.id
    )
    db.add(new_registration)

    # Записваме одит лог в системата, за да може администраторът да го проследи, ако има прикачен протокол
    log_details = f"Студент {student.student_id_number} се записа за изпит {exam.subject}."
    if protocol_cloud_path:
        log_details += f" Прикачен изпитен протокол: {protocol_cloud_path}"

    db.add(AdminLog(
        admin_id=None, # Системен лог, задействан от студент
        action_type="STUDENT_PROTOCOL_INSERT" if protocol_cloud_path else "STUDENT_SELF_INSERT",
        details=log_details,
        specialty=student.specialty,
        group=str(student.group)
    ))

    db.commit()
    
    return {
        "status": "success",
        "message": "Успешно записване за изпита." + (" Документът е прикачен за администраторска проверка." if protocol_cloud_path else "")
    }


@app.delete("/students/delete-account")
def delete_student_account(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    4. Изтриване на студентския акаунт от мобилното приложение.
    Поради CASCADE релациите в базата данни, автоматично се трият и изпитните му регистрации.
    """
    if is_superadmin_user(current_user):
        raise HTTPException(status_code=400, detail="Superadmin account cannot be deleted via mobile student app.")

    if current_user.get("role") not in ("student", "superadmin") and not is_superadmin_user(current_user):
        raise HTTPException(status_code=403, detail="Достъпът е забранен.")

    student_id = current_user.get("sub")
    student = db.query(Student).filter(Student.id == student_id).first()

    if not student:
        raise HTTPException(status_code=404, detail="Акаунтът не беше намерен.")

    db.delete(student)
    db.commit()
    return {"status": "success", "message": "Акаунтът и всички свързани данни бяха заличени успешно."}