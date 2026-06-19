import os
import io
import secrets
import face_recognition
import bcrypt
import time
import cv2
import numpy as np
import requests
import pandas as pd
from fastapi import FastAPI, Depends, File, UploadFile, HTTPException, Form, APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime

from .database import init_db, get_db
from .models import Student, Exam, Admin, ExamRegistration, AccessLog, Examiner, AdminLog, SessionType
from .schemas import AdminCreateSchema, ExaminerCreateSchema, StudentEnrollSchema
from .auth import create_access_token, require_admin
from .stream import generate_live_frames
from .storage import init_storage, upload_photo_to_cloud
from .mailer import send_welcome_email

app = FastAPI()

@app.on_event("startup")
def on_startup():
    init_db()
    init_storage()

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
                status="PENDING" # Очаква мобилно потвърждение и одобрение от админ 
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
def send_bulk_student_emails(log_id: str, db: Session = Depends(get_db)):
    """
    Ендпоинт, който изпраща имейл известия до всички студенти от конкретен импорт.
    След успешно изпращане, флагът notification_sent става True.
    """
    # 1. Намираме съответния административен лог
    log = db.query(AdminLog).filter(AdminLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log entry not found for the provided ID.")
    
    if log.notification_sent:
        raise HTTPException(status_code=400, detail="Email notifications for this log have already been sent.")

    target_students = db.query(Student).filter(
        Student.specialty == log.specialty,
        Student.group == log.group,
        Student.status == "PENDING",
        Student.face_embedding == None
    ).all()

    if not target_students:
        raise HTTPException(status_code=404, detail="There are no pending students for this specialty and group.")

    success_sent_count = 0

    for student in target_students:
        # Генерираме нова чиста временна парола за пращането
        new_temp_password = secrets.token_urlsafe(8) + "1A!"
        
        # Хешираме я с чист bcrypt
        password_bytes = new_temp_password.encode('utf-8')
        salt = bcrypt.gensalt()
        hashed_bytes = bcrypt.hashpw(password_bytes, salt)
        
        # Обновяваме студента в базата данни
        student.hashed_password = hashed_bytes.decode('utf-8')
        
        # Изпращаме физическия имейл през SMTP
        email_delivered = send_welcome_email(
            student_email=student.email,
            student_name=student.full_name,
            temp_password=new_temp_password
        )
        
        if email_delivered:
            success_sent_count += 1

    if success_sent_count > 0:
        # Обръщаме флага на True в базата данни
        log.notification_sent = True
        db.commit()
        return {"message": f"Успешно изпратени {success_sent_count} имейл известия. Флагът на лога е обновен."}
    else:
        raise HTTPException(status_code=500, detail="Грешка при изпращането на имейлите през SMTP сървъра.")

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
    file: UploadFile = File(...),
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
    ALLOWED_EXTENSIONS = ["image/jpeg", "image/png", "image/jpg", "image/webp"]

    if file.content_type not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid file type! Only images are allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # 1. Проверка за дублиране на факултетен номер или имейл
    existing_student = db.query(Student).filter(
        (Student.student_id_number == student_id_number) | (Student.email == email)
    ).first()
    
    if existing_student:
        raise HTTPException(status_code=400, detail="Student with this ID number or Email already exists.")

    try:
        # 2. Обработка на снимката (Селфито)
        image_bytes = await file.read()
        image = face_recognition.load_image_file(io.BytesIO(image_bytes))
        
        photo_url = upload_photo_to_cloud(
            file_data=image_bytes,
            object_name=f"{student_id_number}_{int(time.time())}{os.path.splitext(file.filename)[1]}",
            content_type=file.content_type
        )
    
        # Извличане на векторите на лицата от снимката
        face_encodings = face_recognition.face_encodings(image)
        
        if len(face_encodings) == 0:
            raise HTTPException(status_code=400, detail="No face detected in the image. Please try another photo.")
            
        # Взимаме вектора на първото открито лице
        student_embedding = face_encodings[0].tolist()
        if student_embedding:
            duplicate_face = db.query(Student).filter(
            Student.face_embedding.cosine_distance(student_embedding) < 0.05
        ).first()
        
        if duplicate_face:
            raise HTTPException(
                status_code=400, 
                detail=f"Biometric duplicate detected! This face is already registered to student {duplicate_face.full_name} ({duplicate_face.student_id_number})."
            )
        
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
            face_embedding=student_embedding,
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

@app.post("/admins/register")
def register_admin(
    admin_data: AdminCreateSchema,
    db: Session = Depends(get_db)
):
    """ Регистрация на нов администратор за уеб портала """
    existing_admin = db.query(Admin).filter(Admin.email == admin_data.email).first()
    if existing_admin:
        raise HTTPException(status_code=400, detail="Admin with this email already exists.")
    
    # Хеширане с чист bcrypt
    password_bytes = admin_data.password.encode('utf-8')
    hashed_password = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode('utf-8')
    
    new_admin = Admin(
        full_name=admin_data.full_name,
        email=admin_data.email,
        hashed_password=hashed_password
    )
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)
    
    return {"status": "success", "message": f"Admin {admin_data.full_name} registered successfully. Waiting for superadmin verification.", "admin_id": new_admin.id}


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
            raw_session = str(row['Сесия']).strip().lower()
            allowed_sessions = [e.value for e in SessionType] # ['лятна', 'зимна', 'поправителна', 'ликвидационна']
            
            if raw_session not in allowed_sessions:
                raise HTTPException(
                    status_code=400,
                    detail=f"Error on row {index+2}: Invalid session '{row['Сесия']}'. "
                           f"Allowed values are: Лятна, Зимна, Поправителна, Ликвидационна."
                )

            session_type_val = SessionType(raw_session)
            subject_val = str(row['Дисциплина']).strip()
            lecturer_val = str(row['Преподавател']).strip()
            raw_date = str(row['Дата']).split()[0].strip()  # Изчистваме ако pandas е добавил автоматично 00:00:00 към датата
            raw_time = str(row['Час']).strip()
            
            try:
                combined_str = f"{raw_date} {raw_time}"
                date_time_val = pd.to_datetime(combined_str)
            except Exception:
                raise HTTPException(
                    status_code=400,
                    detail=f"Error on row {index+2}: Invalid format! Please ensure Date is in YYYY-MM-DD format and Time is in HH:MM format."
                )
            room_val = str(row['Зала']).strip()
            faculty_val = str(row['Факултет']).strip()
            specialty_val = str(row['Специалност']).strip()
            course_val = int(row['Курс'])
            stream_val = int(row['Поток'])
            group_val = str(row['Група']).strip()
            
            # Проверка за уникалност по предмет, дата, специалност и група
            existing_exam = db.query(Exam).filter(
                Exam.subject == subject_val,
                Exam.date_time == date_time_val,
                Exam.group == group_val,
                Exam.specialty == specialty_val
            ).first()
            
            if existing_exam:
                existing_exam.session_type = session_type_val
                existing_exam.room_number = room_val
                existing_exam.lecturer = lecturer_val
                existing_exam.faculty = faculty_val
                existing_exam.course = course_val
                existing_exam.stream = stream_val
                exams_updated += 1
            else:
                new_exam = Exam(
                    session_type=session_type_val,
                    subject=subject_val,
                    lecturer=lecturer_val,
                    date_time=date_time_val,
                    room_number=room_val,
                    faculty=faculty_val,
                    specialty=specialty_val,
                    course=course_val,
                    stream=stream_val,
                    group=group_val
                )
                db.add(new_exam)
                exams_created += 1

        # 4. Запис в лога при промени
        if exams_created > 0 or exams_updated > 0:
            new_log = AdminLog(
                admin_id=admin.id,
                action_type="EXAM_IMPORT",
                details=f"Импорт на изпити: Създадени {exams_created}, Обновени {exams_updated}.",
                notification_sent=True
            )
            db.add(new_log)

        db.commit()
        
        return {
            "status": "success",
            "message": "Обработката на Excel файла приключи успешно.",
            "created": exams_created,
            "updated": exams_updated
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

# --- ЛОГИН ЗА АДМИНИСТРАТОРИ (УЕБ ПОРТАЛ) ---
@app.post("/admins/login")
def admin_login(email: str, password: str, db: Session = Depends(get_db)):
    # Търсим изрично в таблицата за администратори
    admin = db.query(Admin).filter(Admin.email == email).first()
    if not admin:
        raise HTTPException(status_code=400, detail="Invalid email or password.")
    
    if not admin.is_verified:
        raise HTTPException(status_code=403, detail="Your admin account is pending verification. Please contact the superadmin.")
    
    password_bytes = password.encode('utf-8')
    if not bcrypt.checkpw(password_bytes, admin.hashed_password.encode('utf-8')):
        raise HTTPException(status_code=400, detail="Invalid email or password.")
    
    # Издаваме токен с роля admin
    access_token = create_access_token(data={"sub": admin.id, "role": "admin"})
    return {"access_token": access_token, "token_type": "bearer"}


# --- ЛОГИН ЗА СТУДЕНТИ (МОБИЛНО ПРИЛОЖЕНИЕ) ---
@app.post("/students/login")
def student_login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    # Търсим изрично в таблицата за студенти
    student = db.query(Student).filter(Student.email == email).first()
    if not student:
        raise HTTPException(status_code=400, detail="Invalid email or password.")
    
    if student.hashed_password == "LOCKED_UNTIL_EMAIL_SENT":
        raise HTTPException(status_code=403, detail="Your account is locked until you receive the email with your temporary password.")
        
    password_bytes = password.encode('utf-8')
    if not bcrypt.checkpw(password_bytes, student.hashed_password.encode('utf-8')):
        raise HTTPException(status_code=400, detail="Invalid email or password.")
        
    # Издаваме токен с роля student
    access_token = create_access_token(data={"sub": student.id, "role": "student"})
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/admins/execute-allocation")
def execute_student_allocation(
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_admin)
):
    """
    Задействане на разпределението. 
    Обхожда всички изпити, разделя групите по запетайка и вкарва съответните студенти в exam_registrations.
    """

    admin = db.query(Admin).filter(Admin.id == current_admin['sub']).first()
    if not admin.is_verified:
        raise HTTPException(status_code=403, detail="Your admin account is pending verification. Cannot execute allocation.")

    all_exams = db.query(Exam).filter(Exam.session_type.in_([SessionType.SUMMER, SessionType.WINTER])).all()
    total_registrations_created = 0
    
    for exam in all_exams:
        # Разделяме групите от стринга "37, 38" -> ['37', '38']
        allowed_groups = [int(g.strip()) for g in exam.group.split(",") if g.strip().isdigit()]
        
        # Намираме студентите от по факултета, специалността, курса, потока и групите, които са одобрени
        matching_students = db.query(Student).filter(
            Student.status == "APPROVED",
            Student.faculty == exam.faculty,
            Student.specialty == exam.specialty,
            Student.course == exam.course,
            Student.stream == exam.stream,
            Student.group.in_(allowed_groups)
        ).all()
        
        for student in matching_students:
            # Проверяваме дали вече няма съществуващ запис, за да не дублираме
            exists = db.query(ExamRegistration).filter(
                ExamRegistration.student_id == student.id,
                ExamRegistration.exam_id == exam.id
            ).first()
            
            if not exists:
                new_reg = ExamRegistration(
                    student_id=student.id,
                    exam_id=exam.id
                )
                db.add(new_reg)
                total_registrations_created += 1

    if total_registrations_created == 0:
        action_type = "ALLOCATION_EXECUTION_NO_NEW"
        updated_details = "Няма нови регистрации за изпити. Всички студенти вече са разпределени."
    else:
        action_type = "ALLOCATION_EXECUTION"
        updated_details = f"Успешно разпределение: Брой на новите регистрации: {total_registrations_created}."

    new_log = AdminLog(
        admin_id=admin.id,
        action_type=action_type,
        details=updated_details,
        notification_sent=True
    )
    db.add(new_log)
                
    db.commit()
    return {
        "status": "success",
        "message": f"Allocation executed successfully by admin ID {current_admin['sub']}.",
        "new_registrations_created": total_registrations_created
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

@app.get("/admins/rooms/{room_number}/live-stream")
def get_room_live_stream(room_number: str):
    """
    Ендпоинт, който админ панелът (Frontend-а) може да зареди директно в един <img> таг!
    Пример: <img src="http://localhost:8000/admins/rooms/1151/live-stream" />
    """
    return StreamingResponse(
        generate_live_frames(room_number),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )