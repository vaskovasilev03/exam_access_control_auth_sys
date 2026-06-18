from pydantic import BaseModel, EmailStr

class StudentCreate(BaseModel):
    full_name: str
    student_id_number: str
    email: EmailStr
    department: str

    stream: str
    group: str
    password: str
    file: bytes

class AdminCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str

class ExamCreate(BaseModel):
    subject: str
    room_number: str
    date_time: str
    lecturer: str
    stream: str
    group: str

class ExamRegistrationCreate(BaseModel):
    student_id: int
    exam_id: int

class AccessLogCreate(BaseModel):
    student_id: int
    location: str
    status: str