import os
import io
import time
import cv2
import httpx
import asyncio
import face_recognition
import numpy as np
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo
from .database import SessionLocal
from .models import Student, Exam, ExamRegistration, AccessLog

ACTIVE_CAMERAS = {}
LATEST_FRAMES = {}
CAMERA_TASKS = {}
AI_ROOM_STATES = {}

timezone = ZoneInfo("Europe/Sofia")

def analyze_frame_outside_ui(jpg_bytes: bytes, room_number: str, known_face_encodings, known_face_names, state: dict):
    """
    Чиста ИИ функция. НЕ рисува нищо върху кадъра.
    Само анализира и обновява текстовото състояние на залата в паметта.
    """
    try:
        nparr = np.frombuffer(jpg_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None or frame.size == 0:
            return

        current_time = time.time()
        
        # Ако сме в заключено зелено състояние (успешен достъп), пазим данните за квестора
        if current_time < state["green_state_end_time"]:
            return

        # Стандартно ИИ сканиране за лица
        small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
        rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
        face_locations = face_recognition.face_locations(rgb_small_frame)

        if not face_locations:
            state["student_name"] = ""
            state["faculty_number"] = ""
            state["status_text"] = "Няма зачетено лице пред камерата"
            state["status_type"] = "idle" # Сив/Бял цвят в UI
            return

        # Има лице, започваме разпознаване
        face_encoding = face_recognition.face_encodings(rgb_small_frame, face_locations)[0]
        student_found = None
        
        if known_face_encodings:
            TOLERANCE = 0.48
            matches = face_recognition.compare_faces(known_face_encodings, face_encoding, TOLERANCE)
            if any(matches):
                best_match_index = np.argmin(face_recognition.face_distance(known_face_encodings, face_encoding))
                full_name = list(known_face_names.keys())[best_match_index]
                student_found = known_face_names[full_name]

        if not student_found:
            state["student_name"] = "Непознат обект"
            state["faculty_number"] = "—"
            state["status_text"] = "ВНИМАНИЕ: Лицето липсва в базата данни!"
            state["status_type"] = "danger" # Червен цвят в UI
            return

        # Проверка на графиците в Postgres
        db: Session = SessionLocal()
        try:
            current_now = datetime.now(timezone)
            
            # 1. Вече влязъл ли е днес?
            already_in_room = db.query(AccessLog).filter(
                AccessLog.student_id == student_found.id,
                AccessLog.location == room_number,
                AccessLog.status == "GRANTED",
                func.date(AccessLog.created_at) == current_now.date()
            ).first()

            if already_in_room:
                state["student_name"] = student_found.full_name
                state["faculty_number"] = student_found.student_id_number
                state["status_text"] = "Студентът ВЕЧЕ е допуснат за този изпит."
                state["status_type"] = "warning" # Жълт цвят в UI
                return
            
            # 2. Има ли изпит в тази зала днес?
            valid_registration = db.query(ExamRegistration).join(Exam).filter(
                ExamRegistration.student_id == student_found.id,
                Exam.room_number == room_number,
                func.date(Exam.date_time) == current_now.date()
            ).first()
            
            is_time_valid = False
            if valid_registration:
                exam_time = valid_registration.exam.date_time
                if exam_time.tzinfo is None:
                    exam_time = exam_time.replace(tzinfo=timezone)
                else:
                    exam_time = exam_time.astimezone(timezone)
                print(f'Текущо време: {current_now}, Време на изпита: {exam_time}')
                if (exam_time - timedelta(minutes=30)) <= current_now <= (exam_time + timedelta(minutes=15)):
                    is_time_valid = True

            # 3. Крайно решение
            state["student_name"] = student_found.full_name
            state["faculty_number"] = student_found.student_id_number

            if valid_registration and is_time_valid:
                # Записваме лога в базата
                new_log = AccessLog(student_id=student_found.id, location=room_number, status="GRANTED")
                db.add(new_log)
                db.commit()
                
                # Заключваме зеления статус на екрана за 5 секунди
                state["green_state_end_time"] = time.time() + 5.0  
                state["locked_student_name"] = student_found.full_name
                state["locked_fac_num"] = student_found.student_id_number
                state["status_text"] = "ДОСТЪПЪТ РАЗРЕШЕН!"
                state["status_type"] = "success" # Зелен цвят в UI
                
            elif valid_registration and not is_time_valid:
                state["status_text"] = f"Интервал за достъп нарушен, изпита започва в {valid_registration.exam.date_time.strftime('%H:%M')}."
                state["status_type"] = "warning"
            else:
                anywhere_today = db.query(ExamRegistration).join(Exam).filter(
                    ExamRegistration.student_id == student_found.id,
                    func.date(Exam.date_time) == current_now.date()
                ).first()
                
                if anywhere_today:
                    state["status_text"] = f"ГРЕШНА ЗАЛА! Студентът трябва да отиде в Зала {anywhere_today.exam.room_number}."
                else:
                    state["status_text"] = "НЯМА ИЗПИТ ДНЕС за този студент."
                state["status_type"] = "danger"

        except Exception as e:
            print(f"Грешка при база данни: {e}")
        finally:
            db.close()
            
    except Exception as e:
        print(f"Грешка ИИ: {e}")


async def run_heavy_ai_async(jpg_bytes: bytes, room_number: str, known_face_encodings, known_face_names):
    state = AI_ROOM_STATES[room_number]
    try:
        await asyncio.to_thread(
            analyze_frame_outside_ui, jpg_bytes, room_number, known_face_encodings, known_face_names, state
        )
    finally:
        state["ai_busy"] = False


async def fetch_frames_from_esp32(room_number: str, esp32_ip: str):
    url = f"http://{esp32_ip}:81/stream"
    print(f"[Mjpeg Stream Task] Стартиране на СУРОВ поток за Зала {room_number}...")
    
    db = SessionLocal()
    students_in_db = db.query(Student).filter(Student.face_embedding != None).all()
    known_face_encodings = [np.array(s.face_embedding) for s in students_in_db]
    known_face_names = {s.full_name: s for s in students_in_db}
    db.close()

    AI_ROOM_STATES[room_number] = {
        "student_name": "",
        "faculty_number": "",
        "status_text": "Камерата стартира...",
        "status_type": "idle",
        "ai_busy": False,
        "green_state_end_time": 0,
        "locked_student_name": "",
        "locked_fac_num": "",
        "last_ai_run_time": 0
    }
    state = AI_ROOM_STATES[room_number]
    timeout = httpx.Timeout(None)
    
    while room_number in ACTIVE_CAMERAS:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        await asyncio.sleep(2)
                        continue
                    
                    bytes_buffer = b""
                    async for chunk in response.aiter_bytes():
                        bytes_buffer += chunk
                        
                        while True:
                            a = bytes_buffer.find(b'\xff\xd8')
                            b = bytes_buffer.find(b'\xff\xd9')
                            
                            if a != -1 and b != -1:
                                if a < b:
                                    jpg_bytes = bytes_buffer[a:b+2]
                                    bytes_buffer = bytes_buffer[b+2:]
                                    
                                    LATEST_FRAMES[room_number] = jpg_bytes
                                    
                                    # Пускаме ИИ анализа на заден план на всеки 200ms
                                    current_time = time.time()
                                    if current_time < state["green_state_end_time"]:
                                        # Ако сме в зелен лок, пренаписваме статуса динамично
                                        state["student_name"] = state["locked_student_name"]
                                        state["faculty_number"] = state["locked_fac_num"]
                                        state["status_text"] = "ДОСТЪПЪТ РАЗРЕШЕН!"
                                        state["status_type"] = "success"
                                    
                                    if not state["ai_busy"] and (current_time - state["last_ai_run_time"] > 0.20):
                                        state["ai_busy"] = True
                                        state["last_ai_run_time"] = current_time
                                        asyncio.create_task(run_heavy_ai_async(jpg_bytes, room_number, known_face_encodings, known_face_names))
                                else:
                                    bytes_buffer = bytes_buffer[a:]
                            else:
                                break
                        await asyncio.sleep(0.001)
        except Exception as e:
            await asyncio.sleep(3)

async def generate_from_memory(room_number: str):
    while True:
        if room_number not in LATEST_FRAMES:
            await asyncio.sleep(0.1)
            continue
        yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + LATEST_FRAMES[room_number] + b'\r\n')
        await asyncio.sleep(0.033)