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
CAMERA_HEALTH = {}
SUBSCRIBERS = {}
ROOM_EVENT_SUBSCRIBERS = {}

timezone = ZoneInfo("Europe/Sofia")

def subscribe_room_events(room_number: str) -> asyncio.Queue:
    if room_number not in ROOM_EVENT_SUBSCRIBERS:
        ROOM_EVENT_SUBSCRIBERS[room_number] = set()
    queue = asyncio.Queue(maxsize=50)
    ROOM_EVENT_SUBSCRIBERS[room_number].add(queue)
    return queue

def unsubscribe_room_events(room_number: str, queue: asyncio.Queue):
    if room_number in ROOM_EVENT_SUBSCRIBERS:
        ROOM_EVENT_SUBSCRIBERS[room_number].discard(queue)
        if not ROOM_EVENT_SUBSCRIBERS[room_number]:
            del ROOM_EVENT_SUBSCRIBERS[room_number]

def emit_room_event(room_number: str, event_name: str, data: dict):
    if room_number in ROOM_EVENT_SUBSCRIBERS:
        payload = {"event": event_name, "data": data}
        for q in list(ROOM_EVENT_SUBSCRIBERS[room_number]):
            if q.full():
                try:
                    q.get_nowait()
                except Exception:
                    pass
            try:
                q.put_nowait(payload)
            except Exception:
                pass


def subscribe_client(room_number: str) -> asyncio.Queue:
    if room_number not in SUBSCRIBERS:
        SUBSCRIBERS[room_number] = set()
    queue = asyncio.Queue(maxsize=1)
    SUBSCRIBERS[room_number].add(queue)
    return queue

def unsubscribe_client(room_number: str, queue: asyncio.Queue):
    if room_number in SUBSCRIBERS:
        SUBSCRIBERS[room_number].discard(queue)
        if not SUBSCRIBERS[room_number]:
            del SUBSCRIBERS[room_number]

def broadcast_frame(room_number: str, jpg_bytes: bytes):
    if room_number in SUBSCRIBERS:
        for queue in list(SUBSCRIBERS[room_number]):
            if queue.full():
                try:
                    queue.get_nowait()
                except Exception:
                    pass
            try:
                queue.put_nowait(jpg_bytes)
            except Exception:
                pass

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
        if current_time < state.get("green_state_end_time", 0):
            return

        # Стандартно ИИ сканиране за лица (намаляваме кадъра за бърз анализ)
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
                # Маркираме допуска в базата данни
                valid_registration.is_admitted = True
                valid_registration.admitted_at = current_now
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
                return {"admitted": True, "student_id": str(student_found.id), "student_name": student_found.full_name}
                
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

    return None


async def run_heavy_ai_async(jpg_bytes: bytes, room_number: str, known_face_encodings, known_face_names):
    state = AI_ROOM_STATES.get(room_number)
    if not state:
        return
    prev_sig = (state.get("status_type"), state.get("student_name"), state.get("status_text"))
    try:
        admission_info = await asyncio.to_thread(
            analyze_frame_outside_ui, jpg_bytes, room_number, known_face_encodings, known_face_names, state
        )
        new_sig = (state.get("status_type"), state.get("student_name"), state.get("status_text"))
        if new_sig != prev_sig:
            emit_room_event(room_number, "biometric_status", {
                "student_name": state.get("student_name", ""),
                "faculty_number": state.get("faculty_number", ""),
                "status_text": state.get("status_text", ""),
                "status_type": state.get("status_type", "idle")
            })
        if admission_info and admission_info.get("admitted"):
            emit_room_event(room_number, "roster_update", {
                "room_number": room_number,
                "student_id": admission_info.get("student_id"),
                "student_name": admission_info.get("student_name")
            })
    finally:
        state["ai_busy"] = False


def _load_known_faces():
    db = SessionLocal()
    try:
        students_in_db = db.query(Student).filter(Student.face_embedding != None).all()
        known_face_encodings = [np.array(s.face_embedding) for s in students_in_db]
        known_face_names = {s.full_name: s for s in students_in_db}
        return known_face_encodings, known_face_names
    finally:
        db.close()


def stop_camera_stream(room_number: str, reason: str = "manual") -> bool:
    """
    Прекратява фоновата задача за стрийминг, освобождава ресурсите и изчиства паметта за дадената зала.
    reason: "manual" (от квестор) или "timeout" (автоматичен таймаут при липса на хардуер).
    """
    removed_ip = ACTIVE_CAMERAS.pop(room_number, None)
    task = CAMERA_TASKS.pop(room_number, None)
    if task and not task.done():
        task.cancel()

    LATEST_FRAMES.pop(room_number, None)
    CAMERA_HEALTH[room_number] = {
        "last_frame_time": 0,
        "is_online": False,
        "esp32_ip": removed_ip,
        "stopped": True
    }

    status_text = "Верификацията е приключена" if reason == "manual" else "Камерата е деактивирана (таймаут)"
    if room_number in AI_ROOM_STATES:
        AI_ROOM_STATES[room_number]["student_name"] = "—"
        AI_ROOM_STATES[room_number]["faculty_number"] = "—"
        AI_ROOM_STATES[room_number]["status_text"] = status_text
        AI_ROOM_STATES[room_number]["status_type"] = "idle"
        AI_ROOM_STATES[room_number]["ai_busy"] = False
        AI_ROOM_STATES[room_number]["green_state_end_time"] = 0

    emit_room_event(room_number, "camera_status", {
        "room_number": room_number,
        "armed": False,
        "is_online": False,
        "stopped": True,
        "reason": reason,
        "esp32_ip": removed_ip
    })
    emit_room_event(room_number, "biometric_status", {
        "student_name": "—",
        "faculty_number": "—",
        "status_text": status_text,
        "status_type": "idle"
    })
    print(f"[Camera Stopped] Стриймингът за Зала {room_number} е прекратен ({reason}). Ресурсите са освободени.")
    return True

async def fetch_frames_from_esp32(room_number: str, esp32_ip: str):
    """
    Фонов таск за поемане на MJPEG стрийма от ESP32 (порт 81).
    Устойчив на мрежови прекъсвания с progressive backoff и автоматичен таймаут.
    """
    url = f"http://{esp32_ip}:81/stream"
    print(f"[Stream Worker] Стартиране на фоново четене от Зала {room_number} ({url})")
    
    known_face_encodings, known_face_names = _load_known_faces()
    last_db_refresh = time.time()
    
    AI_ROOM_STATES[room_number] = {
        "student_name": "—",
        "faculty_number": "—",
        "status_text": "Инициализиране на камерата...",
        "status_type": "idle",
        "ai_busy": False,
        "green_state_end_time": 0,
        "locked_student_name": "",
        "locked_fac_num": "",
        "last_ai_run_time": 0
    }
    state = AI_ROOM_STATES[room_number]
    
    CAMERA_HEALTH[room_number] = {
        "last_frame_time": time.time(),
        "is_online": False,
        "esp32_ip": esp32_ip,
        "stopped": False
    }

    # Задаваме таймаут за свързване и четене (15 сек за гладък Wi-Fi трансфер без фалшиви ресети)
    timeout = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=10.0)
    retry_count = 0
    disconnect_start_time = None
    
    while room_number in ACTIVE_CAMERAS:
        try:
            # Периодично обновяваме лицата от БД на всеки 60 сек
            if time.time() - last_db_refresh > 60:
                known_face_encodings, known_face_names = _load_known_faces()
                last_db_refresh = time.time()

            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        print(f"[Camera Warning] Сървърът на ESP32 в Зала {room_number} върна код {response.status_code}. Презареждане след 2 сек...")
                        was_on = CAMERA_HEALTH[room_number].get("is_online", False)
                        CAMERA_HEALTH[room_number]["is_online"] = False
                        if was_on:
                            emit_room_event(room_number, "camera_status", {
                                "room_number": room_number, "armed": False, "is_online": False, "esp32_ip": esp32_ip
                            })
                        await asyncio.sleep(2)
                        continue
                    
                    was_offline = not CAMERA_HEALTH[room_number].get("is_online", False)
                    CAMERA_HEALTH[room_number]["is_online"] = True
                    CAMERA_HEALTH[room_number]["last_frame_time"] = time.time()
                    state["status_text"] = "Очакване на обект пред камерата..."
                    state["status_type"] = "idle"
                    if was_offline:
                        print(f"[Camera Connected] Успешна връзка с ESP32 в Зала {room_number} ({esp32_ip})")
                        emit_room_event(room_number, "camera_status", {
                            "room_number": room_number, "armed": True, "is_online": True, "esp32_ip": esp32_ip
                        })
                        emit_room_event(room_number, "biometric_status", {
                            "student_name": "", "faculty_number": "", "status_text": state["status_text"], "status_type": "idle"
                        })
                    
                    # Нулиране на брояча при успешна връзка
                    retry_count = 0
                    disconnect_start_time = None

                    bytes_buffer = b""
                    async for chunk in response.aiter_bytes():
                        if room_number not in ACTIVE_CAMERAS:
                            break
                            
                        bytes_buffer += chunk

                        # Защита от препълване на буфера при изгубен байт на рамката по Wi-Fi
                        if len(bytes_buffer) > 500_000:
                            bytes_buffer = bytes_buffer[-100_000:]
                        
                        while True:
                            a = bytes_buffer.find(b'\xff\xd8')
                            if a == -1:
                                if len(bytes_buffer) > 2:
                                    bytes_buffer = bytes_buffer[-2:]
                                break
                                
                            b = bytes_buffer.find(b'\xff\xd9', a + 2)
                            if b != -1:
                                jpg_bytes = bytes_buffer[a:b+2]
                                bytes_buffer = bytes_buffer[b+2:]
                                
                                if len(jpg_bytes) > 200:
                                    current_time = time.time()
                                    LATEST_FRAMES[room_number] = jpg_bytes
                                    CAMERA_HEALTH[room_number]["last_frame_time"] = current_time
                                    CAMERA_HEALTH[room_number]["is_online"] = True
                                    
                                    # Моментално излъчване към всички активни браузъри през опашките
                                    broadcast_frame(room_number, jpg_bytes)
                                    
                                    # Ако сме в зелен лок, обновяваме статуса
                                    if current_time < state.get("green_state_end_time", 0):
                                        state["student_name"] = state.get("locked_student_name", "")
                                        state["faculty_number"] = state.get("locked_fac_num", "")
                                        state["status_text"] = "ДОСТЪПЪТ РАЗРЕШЕН!"
                                        state["status_type"] = "success"
                                    elif state.get("green_state_end_time", 0) > 0 and current_time >= state.get("green_state_end_time", 0):
                                        state["green_state_end_time"] = 0
                                        state["student_name"] = ""
                                        state["faculty_number"] = ""
                                        state["status_text"] = "Очакване на студент пред терминала..."
                                        state["status_type"] = "idle"
                                        emit_room_event(room_number, "biometric_status", {
                                            "student_name": "", "faculty_number": "", "status_text": state["status_text"], "status_type": "idle"
                                        })
                                    
                                    # Пускаме ИИ анализа на заден план с балансирана честота (~700ms)
                                    if not state.get("ai_busy", False) and (current_time - state.get("last_ai_run_time", 0) > 0.70):
                                        state["ai_busy"] = True
                                        state["last_ai_run_time"] = current_time
                                        asyncio.create_task(run_heavy_ai_async(jpg_bytes, room_number, known_face_encodings, known_face_names))
                            else:
                                if a > 0:
                                    bytes_buffer = bytes_buffer[a:]
                                break
                                
        except Exception as e:
            now_ts = time.time()
            if disconnect_start_time is None:
                disconnect_start_time = now_ts
                print(f"[Camera Disconnected] Загубена връзка с ESP32 в Зала {room_number}: {repr(e)}")

            was_online = CAMERA_HEALTH[room_number].get("is_online", False)
            CAMERA_HEALTH[room_number]["is_online"] = False
            LATEST_FRAMES.pop(room_number, None)  # Изчистваме стария замръзнал кадър
            state["student_name"] = "—"
            state["faculty_number"] = "—"
            state["status_text"] = "Камерата е офлайн (няма връзка)"
            state["status_type"] = "danger"

            if was_online:
                emit_room_event(room_number, "camera_status", {
                    "room_number": room_number, "armed": False, "is_online": False, "esp32_ip": esp32_ip
                })
                emit_room_event(room_number, "biometric_status", {
                    "student_name": "—", "faculty_number": "—", "status_text": state["status_text"], "status_type": "danger"
                })

            # Автоматично освобождаване на ресурсите след 120 сек без връзка
            if (now_ts - disconnect_start_time) > 120.0:
                print(f"[Auto-Deactivate] ESP32 в Зала {room_number} не отговаря над 2 минути. Освобождаване на ресурсите.")
                stop_camera_stream(room_number, reason="timeout")
                break

            # Progressive backoff за предотвратяване на спам в логовете и излишен мрежов трафик
            retry_count += 1
            if retry_count <= 3:
                sleep_sec = 2.0
            elif retry_count <= 6:
                sleep_sec = 5.0
            else:
                sleep_sec = 10.0

            await asyncio.sleep(sleep_sec)

async def generate_from_memory(room_number: str):
    """
    Queue-based генератор за уеб браузъра.
    Получава кадри моментално (0ms lag, перфектна плавност, 0 дубликати).
    """
    queue = subscribe_client(room_number)
    try:
        # Изпращаме веднага текущия кадър, ако вече има зареден
        init_frame = LATEST_FRAMES.get(room_number)
        if init_frame is not None:
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n'
                b'Content-Length: ' + str(len(init_frame)).encode() + b'\r\n\r\n' +
                init_frame + b'\r\n'
            )

        while room_number in ACTIVE_CAMERAS:
            try:
                frame = await asyncio.wait_for(queue.get(), timeout=2.0)
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n'
                    b'Content-Length: ' + str(len(frame)).encode() + b'\r\n\r\n' +
                    frame + b'\r\n'
                )
            except asyncio.TimeoutError:
                health = CAMERA_HEALTH.get(room_number, {})
                is_alive = health.get("is_online", False) and (time.time() - health.get("last_frame_time", 0) < 8.0)
                if not is_alive:
                    await asyncio.sleep(0.5)
                continue
    finally:
        unsubscribe_client(room_number, queue)