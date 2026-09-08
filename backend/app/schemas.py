import enum
import re
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, field_validator, ValidationError
from typing import Any, Union, Optional
from .models import SessionType

class UserBaseSchema(BaseModel):
    """ Базова схема, съдържаща строгите правила за сигурност за всички потребители """
    email: EmailStr
    password: str

    @field_validator("email")
    def validate_university_email(cls, v):
        # Ограничаваме регистрацията само до легитимни домейни
        if not v.endswith("@tu-sofia.bg"): 
            raise ValueError("Разрешени са само официални университетски имейли с домейни, завършващи на @tu-sofia.bg")
        return v

    @field_validator("password")
    def validate_password_strength(cls, v):
        # Минимум 8 знака, главна буква, малка буква и число
        if len(v.strip()) < 8:
            raise ValueError("Паролата трябва да бъде дълга поне 8 символа.")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Паролата трябва да съдържа поне една главна буква.")
        if not re.search(r"[a-z]", v):
            raise ValueError("Паролата трябва да съдържа поне една малка буква.")
        if not re.search(r"\d", v):
            raise ValueError("Паролата трябва да съдържа поне едно число.")
        return v.strip()

class AdminCreateSchema(UserBaseSchema):
    full_name: str

class ExaminerCreateSchema(UserBaseSchema):
    full_name: str

class StudentEnrollSchema(UserBaseSchema):
    full_name: str
    student_id_number: str
    faculty: str
    specialty: str
    course: int
    stream: int
    group: int


class ExamUploadValidationSchema(BaseModel):
    session_type: str = Field(..., alias="Сесия")
    subject: str = Field(..., alias="Дисциплина")
    lecturer: str = Field(..., alias="Преподавател")
    date_raw: Any = Field(..., alias="Дата")
    time_raw: Any = Field(..., alias="Час")
    room_number: Any = Field(..., alias="Зала")
    faculty: str = Field(..., alias="Факултет")
    specialty: str = Field(..., alias="Специалност")
    course: int = Field(..., alias="Курс")
    stream: int = Field(..., alias="Поток")
    group: Any = Field(..., alias="Група")

    @field_validator("session_type")
    @classmethod
    def validate_session(cls, v: Any) -> str:
        clean_v = str(v).strip().lower()
        from .models import SessionType
        allowed = [e.value for e in SessionType]
        if clean_v not in allowed:
            raise ValueError(f"Невалидна сесия.")
        return clean_v

    @field_validator("group")
    @classmethod
    def validate_groups(cls, v: Any) -> str:
        # Превръщаме обекта/числото в чист изчистен низ (напр. 37.0 -> "37")
        clean_v = str(v).split('.')[0].strip() if '.' in str(v) else str(v).strip()
        parts = [p.strip() for p in clean_v.split(",")]
        for p in parts:
            if not p.isdigit():
                raise ValueError(f"Невалиден формат за група: '{p}'. Трябва да е число или списък от числа.")
        return clean_v

    @field_validator("room_number")
    @classmethod
    def validate_room(cls, v: Any) -> str:
        # Ако е число от сорта на 1151.0, махаме десетичната запетая
        return str(v).split('.')[0].strip() if '.' in str(v) else str(v).strip()

    @field_validator("time_raw")
    @classmethod
    def validate_time(cls, v: Any) -> str:
        # Ако Pandas го е прочел като datetime.time обект, взимаме само HH:MM формата
        if hasattr(v, "strftime"):
            return v.strftime("%H:%M")
        return str(v).strip()
        
    class Config:
        populate_by_name = True

class CameraRegisterSchema(BaseModel):
    room_number: str
    esp32_ip: str

class StudentLoginSchema(BaseModel):
    student_id_number: str
    password: str

class StudentLoginResponseSchema(BaseModel):
    status: str
    message: str
    access_token: str
    token_type: str = "bearer"
    student_status: Optional[str] = None
    has_face_embedding: Optional[bool] = None
    must_change_password: Optional[bool] = None

class ChangePasswordSchema(BaseModel):
    new_password: str = Field(..., description="Новата парола на студента")

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v.strip()) < 8:
            raise ValueError("Паролата трябва да бъде дълга поне 8 символа.")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Паролата трябва да съдържа поне една главна буква.")
        if not re.search(r"[a-z]", v):
            raise ValueError("Паролата трябва да съдържа поне една малка буква.")
        if not re.search(r"\d", v):
            raise ValueError("Паролата трябва да съдържа поне едно число.")
        return v.strip()