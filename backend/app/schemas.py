from pydantic import BaseModel, EmailStr

class StudentCreate(BaseModel):
    full_name: str
    student_id_number: str
    email: EmailStr
    department: str