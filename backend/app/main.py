import io
from fastapi import FastAPI, Depends, File, UploadFile, HTTPException, Form
from sqlalchemy.orm import Session
import face_recognition
import bcrypt
import pandas as pd

from .database import init_db, get_db
from .models import Student, Exam, Admin, ExamRegistration, AccessLog
from .schemas import StudentCreate, ExamCreate, ExamRegistrationCreate, AccessLogCreate
from .auth import create_access_token, require_admin

app = FastAPI()

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/")
def read_root():
    return {"status": "AACAS API is running", "database": "Initialized and Connected"}


@app.post("/students/enroll")
async def enroll_student(
    full_name: str = Form(...),
    student_id_number: str = Form(...),
    email: str = Form(...),
    faculty: str = Form(...),
    specialty: str = Form(...),
    course: int = Form(...),
    stream: int = Form(...),
    group: int = Form(...),
    password: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Ендпоинт за регистрация на студенти чрез мобилното приложение.
    Хешира паролата, извлича 128-измерен вектор от лицето и записва в Postgres.
    """
    
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
            stream=stream.strip(),
            group=group.strip(),
            hashed_password=hashed_password, # Записваме сигурния хеш, НЕ чистата парола
            face_embedding=student_embedding,
            is_verified=False, # Студентът чака одобрение от администратор
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
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """ Регистрация на нов администратор за уеб портала """
    existing_admin = db.query(Admin).filter(Admin.email == email).first()
    if existing_admin:
        raise HTTPException(status_code=400, detail="Admin with this email already exists.")
    
    # Хеширане с чист bcrypt
    password_bytes = password.encode('utf-8')
    hashed_password = bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode('utf-8')
    
    new_admin = Admin(
        full_name=full_name,
        email=email,
        hashed_password=hashed_password
    )
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)
    
    return {"status": "success", "message": f"Admin {full_name} registered successfully."}


@app.post("/admins/upload-exams")
async def upload_exams_excel(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_admin: dict = Depends(require_admin)
):
    """
    Приема Excel файл (.xlsx) с колони: subject, room_number, date_time
    Защитен срещу дублиране на записи при повторно качване.
    """
    if not file.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Invalid file format. Please upload an Excel file.")
    
    try:
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        required_columns = {"subject", "room_number", "date_time", "lecturer", "stream", "group"}
        if not required_columns.issubset(df.columns):
            raise HTTPException(
                status_code=400, 
                detail=f"Excel file must contain these exact columns: {required_columns}"
            )
        
        exams_created = 0
        exams_updated = 0
        
        for index, row in df.iterrows():
            subject_val = str(row['subject']).strip()
            room_val = str(row['room_number']).strip()
            date_time_val = pd.to_datetime(row['date_time'])
            lecturer_val = str(row['lecturer']).strip()
            stream_val = str(row['stream']).strip()
            raw_groups = str(row['group']).strip()
            
            # Проверяваме дали този изпит ВЕЧЕ съществува
            existing_exam = db.query(Exam).filter(
                Exam.subject == subject_val,
                Exam.room_number == room_val,
                Exam.date_time == date_time_val
            ).first()
            
            if existing_exam:
                existing_exam.group = raw_groups
                existing_exam.lecturer = lecturer_val
                existing_exam.stream = stream_val
                exams_updated += 1
            else:
                new_exam = Exam(
                    subject=subject_val,
                    room_number=room_val,
                    date_time=date_time_val,
                    lecturer=lecturer_val,
                    stream=stream_val,
                    group=raw_groups
                )
                db.add(new_exam)
                exams_created += 1

        db.commit()
        return {
            "status": "success",
            "message": "Excel processing complete.",
            "crated": exams_created,
            "updated": exams_updated
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to process Excel file: {str(e)}")


# --- ЛОГИН ЗА АДМИНИСТРАТОРИ (УЕБ ПОРТАЛ) ---
@app.post("/admins/login")
def admin_login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    # Търсим изрично в таблицата за администратори
    admin = db.query(Admin).filter(Admin.email == email).first()
    if not admin:
        raise HTTPException(status_code=400, detail="Invalid email or password.")
    
    password_bytes = password.encode('utf-8')
    if not bcrypt.checkpw(password_bytes, admin.hashed_password.encode('utf-8')):
        raise HTTPException(status_code=400, detail="Invalid email or password.")
    
    # Издаваме токен с роля admin
    access_token = create_access_token(data={"user_id": admin.id, "role": "admin"})
    return {"access_token": access_token, "token_type": "bearer"}


# --- ЛОГИН ЗА СТУДЕНТИ (МОБИЛНО ПРИЛОЖЕНИЕ) ---
@app.post("/students/login")
def student_login(email: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    # Търсим изрично в таблицата за студенти
    student = db.query(Student).filter(Student.email == email).first()
    if not student:
        raise HTTPException(status_code=400, detail="Invalid email or password.")
    
    password_bytes = password.encode('utf-8')
    if not bcrypt.checkpw(password_bytes, student.hashed_password.encode('utf-8')):
        raise HTTPException(status_code=400, detail="Invalid email or password.")
    
    # Изключително важно за Спринт 3 (Хардуера): Студентът трябва да е верифициран от админ, за да влезе!
    if not student.is_verified:
        raise HTTPException(status_code=403, detail="Your account is pending admin verification.")
        
    # Издаваме токен с роля student
    access_token = create_access_token(data={"user_id": student.id, "role": "student"})
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
    all_exams = db.query(Exam).all()
    total_registrations_created = 0
    
    for exam in all_exams:
        # Разделяме групите от стринга "37, 38" -> ['37', '38']
        allowed_groups = [g.strip() for g in exam.group.split(",") if g.strip()]
        
        # Намираме студентите от този поток и тези групи
        matching_students = db.query(Student).filter(
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
                
    db.commit()
    return {
        "status": "success",
        "message": f"Allocation executed successfully by admin ID {current_admin['user_id']}.",
        "new_registrations_created": total_registrations_created
    }