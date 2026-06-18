from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

Base = declarative_base()

class Admin(Base):
    """ Таблица за администраторите (служители в канцелария, разработчици) """
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    
    # Хеширана парола за уеб портала (НИКОГА не пазим чиста парола в базата!)
    hashed_password = Column(String, nullable=False)
    
    is_superadmin = Column(Boolean, default=False) # За софтуерни разработчици/главни администратори
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Student(Base):
    """ Таблица за студентите (профил, парола за приложението и биометрия) """
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    student_id_number = Column(String, unique=True, index=True, nullable=False) # Факултетен номер
    email = Column(String, unique=True, nullable=False)
    department = Column(String) # Специалност
    stream = Column(String, nullable=False)
    group = Column(String, nullable=False)
    
    # Хеширана парола за влизане в мобилното приложение (Flutter)
    hashed_password = Column(String, nullable=False)
    
    # 128-измерният биометричен вектор от face_recognition
    face_embedding = Column(Vector(128), nullable=True) 
    
    # Администраторски контроли
    is_verified = Column(Boolean, default=False)  # Одобрен ли е от админа след селфито
    is_active = Column(Boolean, default=True)      # Активен/Прекъснал
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Релации
    logs = relationship("AccessLog", back_populates="student")
    registrations = relationship("ExamRegistration", back_populates="student")


class Exam(Base):
    """ Таблица за изпитите, качени от администратора чрез Excel """
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, index=True)
    subject = Column(String, nullable=False)
    room_number = Column(String, nullable=False)
    date_time = Column(DateTime(timezone=True), nullable=False)

    lecturer = Column(String, nullable=True)
    stream = Column(String, nullable=False)
    group = Column(String, nullable=False)

    registrations = relationship("ExamRegistration", back_populates="exam")


class ExamRegistration(Base):
    """ Междинна таблица (Списък за изпита) """
    __tablename__ = "exam_registrations"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    exam_id = Column(Integer, ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)

    student = relationship("Student", back_populates="registrations")
    exam = relationship("Exam", back_populates="registrations")


class AccessLog(Base):
    """ Журнал за събитията от ESP32-CAM в реално време """
    __tablename__ = "access_logs"

    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id", ondelete="SET NULL"), nullable=True)
    location = Column(String, nullable=False)  # Зала, където е застанал студента (напр. "Зала 210")
    status = Column(String, nullable=False)    # "GRANTED", "DENIED", "UNKNOWN"
    
    student = relationship("Student", back_populates="logs")
    created_at = Column(DateTime(timezone=True), server_default=func.now())