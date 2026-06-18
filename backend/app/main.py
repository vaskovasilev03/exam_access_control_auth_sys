import io
from fastapi import FastAPI, Depends, File, UploadFile, HTTPException, Form
from sqlalchemy.orm import Session
import face_recognition
import bcrypt
import pandas as pd

from .database import init_db, get_db
from .models import Student, Exam, Admin, ExamRegistration, AccessLog, Room
from .schemas import StudentCreate, ExamCreate, ExamRegistrationCreate, AccessLogCreate, RoomCreate, RoomUpdate

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
    department: str = Form(...),
    course: int = Form(...),
    stream: str = Form(...),
    group: str = Form(...),
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
            department=department,
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

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

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
    db: Session = Depends(get_db)
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
        
        required_columns = {"subject", "room_number", "date_time"}
        if not required_columns.issubset(df.columns):
            raise HTTPException(
                status_code=400, 
                detail=f"Excel file must contain these exact columns: {required_columns}"
            )
        
        exams_added = 0
        exams_skipped = 0
        
        for index, row in df.iterrows():
            subject_val = str(row['subject']).strip()
            room_val = str(row['room_number']).strip()
            date_time_val = pd.to_datetime(row['date_time'])
            lecturer_val = str(row['lecturer']).strip()
            stream_val = str(row['stream']).strip()
            group_val = str(row['group']).strip()
            
            # Проверяваме дали този изпит ВЕЧЕ съществува
            duplicate_exists = db.query(Exam).filter(
                Exam.subject == subject_val,
                Exam.room_number == room_val,
                Exam.date_time == date_time_val
            ).first()
            
            if duplicate_exists:
                exams_skipped += 1
                continue # Прескачаме този ред и отиваме на следващия
            
            # Ако не е дубликат, го създаваме (поддържа изпити по един предмет в различни зали!)
            new_exam = Exam(
                subject=subject_val,
                room_number=room_val,
                date_time=date_time_val,
                lecturer=lecturer_val,
                stream=stream_val,
                group=group_val
            )
            db.add(new_exam)
            exams_added += 1
            
        db.commit()
        return {
            "status": "success",
            "message": f"Excel processing complete.",
            "imported": exams_added,
            "skipped_duplicates": exams_skipped
        }
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to process Excel file: {str(e)}")


@app.post("/rooms", status_code=201)
def create_room(room_data: RoomCreate, db: Session = Depends(get_db)):
    """
    Бърз ендпоинт за добавяне на университетски зали и техния капацитет.
    Приема JSON: {"room_number": "Зала 1151", "capacity": 40}
    """
    clean_room_number = room_data.room_number.strip()
    
    # Проверка дали залата вече съществува
    existing_room = db.query(Room).filter(Room.room_number == clean_room_number).first()
    if existing_room:
        raise HTTPException(status_code=400, detail=f"Room '{clean_room_number}' already exists.")
    
    new_room = Room(
        room_number=clean_room_number,
        capacity=room_data.capacity
    )
    db.add(new_room)
    db.commit()
    db.refresh(new_room)
    
    return {
        "status": "success",
        "message": f"Room {new_room.room_number} with capacity {new_room.capacity} added successfully.",
        "room_id": new_room.id
    }