import uuid
import enum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, text, Enum, Index, event
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

Base = declarative_base()

class Admin(Base):
    """ Таблица за администраторите (служители в канцелария, разработчици) """
    __tablename__ = "admins"
    __table_args__ = (
        Index(
            "uq_single_superadmin",
            "is_superadmin",
            unique=True,
            postgresql_where=text("is_superadmin = true")
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    
    # Хеширана парола за уеб портала (НИКОГА не пазим чиста парола в базата!)
    hashed_password = Column(String, nullable=False)
    is_verified = Column(Boolean, nullable=False, default=False)
    is_superadmin = Column(Boolean, default=False) # За софтуерни разработчици/главни администратори
    created_at = Column(DateTime(timezone=True), server_default=func.now())


@event.listens_for(Admin, "before_insert")
def validate_single_superadmin_insert(mapper, connection, target):
    if target.is_superadmin:
        existing = connection.execute(
            text("SELECT id FROM admins WHERE is_superadmin = true")
        ).first()
        if existing:
            raise ValueError("A superadmin record already exists. Only one superadmin record is allowed in the database.")


@event.listens_for(Admin, "before_update")
def validate_single_superadmin_update(mapper, connection, target):
    if target.is_superadmin:
        existing = connection.execute(
            text("SELECT id FROM admins WHERE is_superadmin = true AND id != :id"),
            {"id": str(target.id)}
        ).first()
        if existing:
            raise ValueError("A superadmin record already exists. Only one superadmin record is allowed in the database.")



class Student(Base):
    """ Таблица за студентите (профил, парола за приложението и биометрия) """
    __tablename__ = "students"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    full_name = Column(String, nullable=False)
    student_id_number = Column(String, unique=True, index=True, nullable=False) # Факултетен номер
    email = Column(String, unique=True, nullable=False)
    faculty = Column(String, nullable=False)
    specialty = Column(String, nullable=False)
    course = Column(Integer, nullable=False)
    stream = Column(Integer, nullable=False)
    group = Column(Integer, nullable=False)
    
    # Хеширана парола за влизане в мобилното приложение (Flutter)
    hashed_password = Column(String, nullable=False)
    
    # 128-измерният биометричен вектор от face_recognition
    face_embedding = Column(Vector(128), nullable=True) 

    status = Column(String, default="PENDING") # PENDING, APPROVED, PENDING_APPROVAL, REJECTED
    must_change_password = Column(Boolean, default=True, nullable=False)
    photo_path = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)      # Активен/Прекъснал
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Релации
    logs = relationship("AccessLog", back_populates="student")
    registrations = relationship("ExamRegistration", back_populates="student")

class SessionType(str, enum.Enum):
    SUMMER = "лятна"
    WINTER = "зимна"
    RESIT = "поправителна" 
    LIQUIDATION = "ликвидационна"


class Examiner(Base):
    __tablename__ = "examiners"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)

    is_verified = Column(Boolean, nullable=False, default=False)
    role = Column(String, default="EXAMINER") 

    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Exam(Base):
    """ Таблица за изпитите, качени от администратора чрез Excel """
    __tablename__ = "exams"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    session_type = Column(Enum(SessionType), nullable=True, index=True)
    subject = Column(String, nullable=False)
    lecturer = Column(String, nullable=True)
    room_number = Column(String, nullable=False)
    date_time = Column(DateTime(timezone=True), nullable=False)
    faculty = Column(String, nullable=False, index=True)
    specialty = Column(String, nullable=False, index=True)
    course = Column(Integer, nullable=False)
    stream = Column(String, nullable=False)
    group = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    registrations = relationship("ExamRegistration", back_populates="exam")


class ExamRegistration(Base):
    """ Междинна таблица (Списък за изпита) """
    __tablename__ = "exam_registrations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False)
    exam_id = Column(UUID(as_uuid=True), ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)

    student = relationship("Student", back_populates="registrations")
    exam = relationship("Exam", back_populates="registrations")


class AccessLog(Base):
    """ Журнал за събитията от ESP32-CAM в реално време """
    __tablename__ = "access_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    student_id = Column(UUID(as_uuid=True), ForeignKey("students.id", ondelete="SET NULL"), nullable=True)
    location = Column(String, nullable=False)  # Зала
    status = Column(String, nullable=False)    # "GRANTED", "DENIED", "UNKNOWN"
    
    student = relationship("Student", back_populates="logs")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AdminLog(Base):
    __tablename__ = "admin_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    admin_id = Column(UUID(as_uuid=True), ForeignKey("admins.id", ondelete="SET NULL"), nullable=True)
    action_type = Column(String, nullable=False) # напр. "STUDENT_IMPORT" или "EXAM_IMPORT"
    details = Column(String, nullable=True)     # напр. "Импортирани 30 студенти за група 37"
    specialty = Column(String, nullable=True)
    group = Column(String, nullable=True) 
    notification_sent = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
