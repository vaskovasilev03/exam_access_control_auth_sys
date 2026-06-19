import re
from pydantic import BaseModel, EmailStr, field_validator

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
        if len(v) < 8:
            raise ValueError("Паролата трябва да бъде дълга поне 8 символа.")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Паролата трябва да съдържа поне една главна буква.")
        if not re.search(r"[a-z]", v):
            raise ValueError("Паролата трябва да съдържа поне една малка буква.")
        if not re.search(r"\d", v):
            raise ValueError("Паролата трябва да съдържа поне едно число.")
        return v

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