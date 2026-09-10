import os
import io
import time
import cv2
import httpx
import asyncio
import face_recognition
import numpy as np
import requests
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from .database import SessionLocal
from .models import Student, Exam, ExamRegistration, AccessLog

esp32_ip = os.getenv("ESP32_IP")
ACTIVE_CAMERAS = {}
LATEST_FRAMES = {}
CAMERA_TASKS = {}

def generate_live_frames(room_number: str, esp32_ip: str):
    """ 
    Свързва се към реалния MJPEG стрийм на ESP32-CAM на порт 81
    и изпълнява биометричната и академична проверка за конкретна зала.
    """
    esp32_url = f"http://{esp32_ip}:81/stream"
    stream_response = None

    try:
        stream_response = requests.get(esp32_url, stream=True, timeout=5)
        if stream_response.status_code != 200:
            print(f"Unsuccessful connection to {esp32_url}")
            return
    except Exception as e:
        print(f"Error when connecting to {esp32_url}: {e}")
        # За застраховка опитваме да изпратим стоп, ако е имало забила предишна връзка
        try: requests.get(stop_url, timeout=2)
        except: pass
        return

    db: Session = SessionLocal()
    students_in_db = db.query(Student).filter(Student.face_embedding != None).all()
    known_face_encodings = [np.array(s.face_embedding) for s in students_in_db]
    known_face_names = {s.full_name: s for s in students_in_db}

    TOLERANCE = 0.5
    stream_start_time = time.time()
    green_state_end_time = 0  
    locked_student_name = ""  
    bytes_buffer = bytes()

    for chunk in stream_response.iter_content(chunk_size=1024):
        bytes_buffer += chunk
        
        a = bytes_buffer.find(b'\xff\xd8')
        b = bytes_buffer.find(b'\xff\xd9')
        
        if a != -1 and b != -1:
            jpg_bytes = bytes_buffer[a:b+2]
            bytes_buffer = bytes_buffer[b+2:]

            if not jpg_bytes or len(jpg_bytes) < 100: 
                continue

            try:
                nparr = np.frombuffer(jpg_bytes, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                if frame is None or frame.size == 0:
                    continue
            except:
                continue

            current_time = time.time()
            elapsed_time = current_time - stream_start_time
            
            box_color = (0, 0, 255) 
            status_text = "SCANNING / UNKNOWN"
            face_to_draw = None

            # --- ФАЗА 1: ТОПЪЛ СТАРТ ---
            if elapsed_time < 5.0:
                box_color = (255, 255, 255)
                status_text = f"ESP32 LINK ACTIVE... ({int(5 - elapsed_time)}s)"
                cv2.putText(frame, status_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, box_color, 2)
                
            # --- ФАЗА 2: ЗАКЛЮЧЕНО ЗЕЛЕНО СЪСТОЯНИЕ ---
            elif current_time < green_state_end_time:
                box_color = (0, 255, 0)
                status_text = f"ACCESS GRANTED: {locked_student_name}"
                
                small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
                rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
                face_locations = face_recognition.face_locations(rgb_small_frame)
                if face_locations:
                    face_to_draw = face_locations[0]

            # --- ФАЗА 3: СТАНДАРТНО АКТИВНО ИИ РАЗПОЗНАВАНЕ ---
            else:
                small_frame = cv2.resize(frame, (0, 0), fx=0.25, fy=0.25)
                rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
                face_locations = face_recognition.face_locations(rgb_small_frame)

                if face_locations:
                    face_to_draw = face_locations[0]
                    face_encoding = face_recognition.face_encodings(rgb_small_frame, face_locations)[0]
                    student_found = None
                    
                    if known_face_encodings:
                        matches = face_recognition.compare_faces(known_face_encodings, face_encoding, TOLERANCE)
                        if any(matches):
                            best_match_index = np.argmin(face_recognition.face_distance(known_face_encodings, face_encoding))
                            full_name = list(known_face_names.keys())[best_match_index]
                            student_found = known_face_names[full_name]

                    if student_found:
                        current_now = datetime.now().astimezone()
                        
                        # 1. Вече вътре ли е?
                        already_in_room = db.query(AccessLog).filter(
                            AccessLog.student_id == student_found.id,
                            AccessLog.location == room_number,
                            AccessLog.status == "GRANTED",
                            func.date(AccessLog.created_at) == current_now.date()
                        ).first()

                        if already_in_room:
                            box_color = (255, 191, 0)
                            status_text = f"ALREADY GRANTED: {student_found.full_name}"
                        else:
                            # 2. График проверка
                            valid_registration = db.query(ExamRegistration).join(Exam).filter(
                                ExamRegistration.student_id == student_found.id,
                                Exam.room_number == room_number,
                                func.date(Exam.date_time) == current_now.date()
                            ).first()
                            
                            is_time_valid = False
                            if valid_registration:
                                exam_time = valid_registration.exam.date_time
                                if (exam_time - timedelta(minutes=30)) <= current_now <= (exam_time + timedelta(minutes=15)):
                                    is_time_valid = True

                            # 3. ДОПУСКАНЕ
                            if valid_registration and is_time_valid:
                                valid_registration.is_admitted = True
                                valid_registration.admitted_at = current_now
                                box_color = (0, 255, 0)
                                status_text = f"ACCESS GRANTED: {student_found.full_name}"
                                
                                new_log = AccessLog(student_id=student_found.id, location=room_number, status="GRANTED")
                                db.add(new_log)
                                db.commit()
                                
                                green_state_end_time = time.time() + 3.0  
                                locked_student_name = student_found.full_name
                                
                            elif valid_registration and not is_time_valid:
                                box_color = (0, 165, 255)
                                status_text = "WRONG TIME"
                            else:
                                anywhere_today = db.query(ExamRegistration).join(Exam).filter(
                                    ExamRegistration.student_id == student_found.id,
                                    func.date(Exam.date_time) == current_now.date()
                                ).first()
                                
                                if anywhere_today:
                                    correct_room = anywhere_today.exam.room_number
                                    box_color = (0, 0, 255)
                                    status_text = f"WRONG ROOM! GO TO ROOM {correct_room}"
                                else:
                                    box_color = (0, 0, 255)
                                    status_text = "NO EXAM TODAY"
                else:
                    cv2.putText(frame, "WAITING FOR FACE...", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            if face_to_draw:
                top, right, bottom, left = face_to_draw
                top *= 4; right *= 4; bottom *= 4; left *= 4
                cv2.rectangle(frame, (left, top), (right, bottom), box_color, 3)
                cv2.putText(frame, status_text, (left, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, box_color, 2)

            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret: continue
                
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
  
        db.close()


async def fetch_frames_from_esp32(room_number: str, esp32_ip: str):
    """
    Независима асинхронна задача. Връзва се към HTTP MJPEG потока на ESP32
    и обновява глобалния речник LATEST_FRAMES.
    """
    url = f"http://{esp32_ip}:81/stream"
    print(f"🚀 [Background Task] Стартиране на постоянен стрийм от Зала {room_number} ({url})...")
    
    # Използваме httpx с изключен таймаут за постоянен стрийм
    timeout = httpx.Timeout(None)
    
    while room_number in ACTIVE_CAMERAS:  # Върти, докато камерата е регистрирана
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        print(f"⚠️ Сървърът на ESP32 върна код {response.status_code}. Презареждане след 2 сек...")
                        await asyncio.sleep(2)
                        continue
                    
                    buffer = b""
                    # Четем суровия стрийм на парчета (chunks)
                    async for chunk in response.aiter_bytes():
                        buffer += chunk
                        
                        # Търсим границите на JPEG кадъра (Старт: \xff\xd8, Край: \xff\xd9)
                        a = buffer.find(b'\xff\xd8')
                        b = buffer.find(b'\xff\xd9')
                        
                        if a != -1 and b != -1 and a < b:
                            jpg = buffer[a:b+2]
                            buffer = buffer[b+2:]
                            
                            # 🔥 ЗАПИСВАМЕ В ПАМЕТТА: Пъхаме кадъра и стартираме ИИ биометрията тук!
                            LATEST_FRAMES[room_number] = jpg
                            
                            # Лека софтуерна пауза за съгласуване на нишките (~30 FPS максимум)
                            await asyncio.sleep(0.01)
                            
        except Exception as e:
            print(f"❌ [Background Task Error] Изгубена връзка с ESP32 в Зала {room_number}: {e}")
            print("🔄 Опит за реконнект след 3 секунди...")
            await asyncio.sleep(3)


# Генератор за уеб браузъра (Взима наготово от паметта)
async def generate_from_memory(room_number: str):
    print(f"🎬 Потребител се закачи към видеото за Зала {room_number}")
    while True:
        # Ако фоновата задача все още не е записала първия кадър, изчакваме малко
        if room_number not in LATEST_FRAMES:
            await asyncio.sleep(0.1)
            continue
            
        frame = LATEST_FRAMES[room_number]
        
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n'
               b'Content-Length: ' + str(len(frame)).encode() + b'\r\n\r\n' + 
               frame + b'\r\n')
        
        # Ограничаваме кадрите към уеб браузъра до ~25 FPS, за да не точим излишен трафик
        await asyncio.sleep(0.04)