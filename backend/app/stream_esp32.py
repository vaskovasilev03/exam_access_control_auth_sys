import os
import io
import time
import uuid
import cv2
import httpx
import asyncio
import face_recognition
import numpy as np
import json
import hashlib
from typing import Optional, Dict, Any, Tuple, List
from datetime import datetime, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo
from .database import SessionLocal
from .models import Student, Exam, ExamRegistration, AccessLog
from .liveness.detector import get_liveness_detector

ACTIVE_CAMERAS = {}
LATEST_FRAMES = {}
CAMERA_TASKS = {}
AI_ROOM_STATES = {}
CAMERA_HEALTH = {}
SUBSCRIBERS = {}
ROOM_EVENT_SUBSCRIBERS = {}
DEBUG_TELEMETRY: Dict[str, Dict[str, Any]] = {}
CAMERA_SOURCES: Dict[str, str] = {}

timezone = ZoneInfo("Europe/Sofia")
QR_DETECTOR = cv2.QRCodeDetector()

# Времеви прозорец за автоматично допускане на студенти през терминала:
# Сканирането стартира 40 мин преди началото на изпита и приключва 5 мин преди началото
# (последните 5 мин са за раздаване на тестовете от квесторите).
ADMISSION_WINDOW_START_MINUTES = 40  # 40 мин преди часа на изпита
ADMISSION_WINDOW_END_MINUTES = 5     # 5 мин преди часа на изпита


def _transliterate_for_cv2(text: str) -> str:
    """Транслитерация на кирилица към латиница за коректно изписване с cv2.putText (OpenCV шрифтовете поддържат само ASCII)."""
    if not text:
        return ""
    table = {
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ж': 'Zh', 'З': 'Z',
        'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M', 'Н': 'N', 'О': 'O', 'П': 'P',
        'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U', 'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch',
        'Ш': 'Sh', 'Щ': 'Sht', 'Ъ': 'A', 'Ь': 'Y', 'Ю': 'Yu', 'Я': 'Ya',
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ж': 'zh', 'з': 'z',
        'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p',
        'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch',
        'ш': 'sh', 'щ': 'sht', 'ъ': 'a', 'ь': 'y', 'ю': 'yu', 'я': 'ya'
    }
    return "".join(table.get(ch, ch) for ch in text)


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

def set_room_qr_scan_mode(room_number: str, enabled: bool, duration_seconds: int = 120) -> dict:
    state = AI_ROOM_STATES.get(room_number)
    if not state:
        return {"success": False, "error": "Room state not found"}

    now = time.time()
    if enabled:
        state["qr_scan_mode"] = True
        dur = max(10, min(duration_seconds, 600))
        state["qr_scan_expiry"] = now + dur
        state["status_text"] = "Режим сканиране на QR код - Задръжте екрана на телефона пред камерата"
        state["status_type"] = "warning"
        emit_room_event(room_number, "qr_scan_mode_changed", {
            "room_number": room_number,
            "enabled": True,
            "expires_in_seconds": int(dur)
        })
        emit_room_event(room_number, "biometric_status", {
            "student_name": state.get("student_name", ""),
            "faculty_number": state.get("faculty_number", ""),
            "status_text": state["status_text"],
            "status_type": "warning"
        })
        return {"success": True, "enabled": True, "expires_in_seconds": int(dur)}
    else:
        state["qr_scan_mode"] = False
        state["qr_scan_expiry"] = 0.0
        state["status_text"] = "Очакване на студент пред терминала..."
        state["status_type"] = "idle"
        emit_room_event(room_number, "qr_scan_mode_changed", {
            "room_number": room_number,
            "enabled": False,
            "expires_in_seconds": 0
        })
        emit_room_event(room_number, "biometric_status", {
            "student_name": "",
            "faculty_number": "",
            "status_text": state["status_text"],
            "status_type": "idle"
        })
        return {"success": True, "enabled": False, "expires_in_seconds": 0}


def log_access_event(db: Session, student_id: uuid.UUID, location: str, status: str, deduplicate: bool = True) -> AccessLog:
    """
    Записва събитие в AccessLog. За отхвърлени или повтарящи се статуси
    проверява дали вече съществува запис със същите (student_id, location, status) за текущия ден,
    за да се избегне спам и натрупване на хиляди повтарящи се записи в базата данни.
    """
    if deduplicate:
        today = datetime.now(timezone).date()
        existing = db.query(AccessLog).filter(
            AccessLog.student_id == student_id,
            AccessLog.location == location,
            AccessLog.status == status,
            func.date(AccessLog.created_at) == today
        ).first()
        if existing:
            return existing

    new_log = AccessLog(student_id=student_id, location=location, status=status)
    db.add(new_log)
    db.commit()
    return new_log


def generate_twin_dynamic_code(student_id: str, student_id_number: str, dt: datetime = None) -> str:
    """
    Генерира 6-цифрен динамичен код за близнак (валиден за 5-минутен времеви прозорец).
    Алгоритъмът е детерминистичен и съвпада с мобилното приложение.
    """
    if dt is None:
        dt = datetime.now(ZoneInfo("UTC"))
    epoch_sec = int(dt.timestamp())
    bucket = epoch_sec // 300
    seed = f"TWIN_PASS:{str(student_id).strip()}:{str(student_id_number).strip()}:{bucket}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    code_num = int(digest[:8], 16) % 1000000
    return f"{code_num:06d}"


def decode_qr_from_frame(frame: np.ndarray) -> Optional[str]:
    """
    Разчитане на QR код от видео кадър чрез многостепенна високочувствителна обработка:
      1. PyZbar върху чист BGR кадър (най-бърз директен прочит)
      2. PyZbar върху Grayscale кадър
      3. PyZbar с адаптивен Gaussian threshold (за силна подсветка от екрана)
      4. PyZbar върху инвертиран кадър (за телефони в Dark Mode / Тъмен режим)
      5. PyZbar с CLAHE контрастно изравняване (за справяне с отблясъци)
      6. PyZbar върху изострен образ (Unsharp Masking срещу замъгляване при близко разстояние)
      7. PyZbar върху централен кроп (фокус върху екрана на телефона)
      8. OpenCV QRCodeDetectorAruco & стандартен QR_DETECTOR (резервни детектори)
    """
    if frame is None or frame.size == 0:
        return None

    def _extract(results):
        if results:
            for r in results:
                if r.data:
                    text = r.data.decode("utf-8", errors="ignore").strip()
                    if text:
                        return text
        return None

    # Опитваме с PyZbar (основен бърз и надежден декодер)
    try:
        import pyzbar.pyzbar as pyzbar

        # 1. PyZbar върху чист BGR кадър
        res = _extract(pyzbar.decode(frame))
        if res:
            return res

        # 2. PyZbar върху Grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        res = _extract(pyzbar.decode(gray))
        if res:
            return res

        # 3. Адаптивен Gaussian Threshold (елиминира локални отблясъци от телефонни екрани)
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5
        )
        res = _extract(pyzbar.decode(thresh))
        if res:
            return res

        # 4. Инвертиран образ за телефони в Dark Mode (бял код на черен фон)
        inverted = cv2.bitwise_not(gray)
        res = _extract(pyzbar.decode(inverted))
        if res:
            return res

        # 5. CLAHE адаптивно контрастно изравняване
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        res = _extract(pyzbar.decode(enhanced))
        if res:
            return res

        # 6. Изостряне (Unsharp Masking) срещу размазване при близко поднасяне на телефона
        gaussian = cv2.GaussianBlur(gray, (0, 0), 2.0)
        sharpened = cv2.addWeighted(gray, 1.5, gaussian, -0.5, 0)
        res = _extract(pyzbar.decode(sharpened))
        if res:
            return res

        # 7. Централен кроп (студентът центрира телефона в обсега на камерата)
        h, w = gray.shape
        cy1, cy2 = int(h * 0.10), int(h * 0.90)
        cx1, cx2 = int(w * 0.10), int(w * 0.90)
        center_crop = gray[cy1:cy2, cx1:cx2]
        res = _extract(pyzbar.decode(center_crop))
        if res:
            return res

        # 8. Централен кроп с 1.4x мащабиране за по-висока детайлност на малки QR кодове
        scaled = cv2.resize(center_crop, (0, 0), fx=1.4, fy=1.4, interpolation=cv2.INTER_CUBIC)
        res = _extract(pyzbar.decode(scaled))
        if res:
            return res

    except Exception:
        pass

    # 9. OpenCV ArUco detector (наличен в OpenCV 5.0)
    try:
        aruco_detector = cv2.QRCodeDetectorAruco()
        data, _, _ = aruco_detector.detectAndDecode(frame)
        if data and str(data).strip():
            return str(data).strip()
    except Exception:
        pass

    # 10. Резервен глобален QR_DETECTOR (поддържа тестови мокове)
    try:
        data, _, _ = QR_DETECTOR.detectAndDecode(frame)
        if data and str(data).strip():
            return str(data).strip()
    except Exception:
        pass

    return None


def process_twin_qr_admission(qr_data: str, room_number: str, db: Session = None, state: dict = None) -> dict:
    """
    Валидира дигиталния пропуск за близнак по три метода:
      1) Динамичен QR JSON payload (TWIN_EXAM_PASS)
      2) 6-цифрен динамичен код от мобилното приложение (валиден за 5 мин)
      3) Факултетен номер на близнака (за ръчно въвеждане от квестор)
    Проверява правото на достъп, изпитното разписание и допуска студента.
    """
    if not qr_data:
        return {"admitted": False, "error": "Липсва подаден код или пропуск за верификация"}

    raw_str = str(qr_data).strip()
    close_db_here = False
    if db is None:
        db = SessionLocal()
        close_db_here = True

    try:
        student = None
        current_now = datetime.now(timezone)
        now_utc = datetime.now(ZoneInfo("UTC"))

        # Вариант 1: JSON payload (директно сканиран QR код)
        if raw_str.startswith("{") and raw_str.endswith("}"):
            try:
                payload = json.loads(raw_str)
            except Exception:
                return {"admitted": False, "error": "Невалиден JSON формат на QR кода"}

            if not isinstance(payload, dict):
                return {"admitted": False, "error": "Невалидно съдържание на QR кода"}

            if payload.get("type") != "TWIN_EXAM_PASS":
                return {"admitted": False, "error": "Неразпознат тип на QR пропуск (очакван: TWIN_EXAM_PASS)"}

            student_id = payload.get("student_id")
            if not student_id:
                return {"admitted": False, "error": "Липсва студентски идентификатор в пропуска"}

            ts_str = payload.get("timestamp")
            if not ts_str:
                return {"admitted": False, "error": "Липсва времеви маркер в пропуска"}
            try:
                qr_time = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                time_diff = abs((now_utc - qr_time).total_seconds())
                if time_diff > 300:
                    return {"admitted": False, "error": "Изтекъл изпитен пропуск (над 5 минути). Моля, обновете кода в приложението"}
            except Exception as e:
                return {"admitted": False, "error": f"Невалиден времеви маркер: {e}"}

            student = db.query(Student).filter(Student.id == student_id).first()
            if not student:
                return {"admitted": False, "error": "Студентът не е намерен в системата"}

            payload_fac = str(payload.get("student_id_number", "")).strip()
            if payload_fac != str(student.student_id_number).strip():
                return {"admitted": False, "error": "Несъответствие във факултетния номер на пропуска"}

        # Вариант 2: 6-цифрен динамичен код (напр. '631728' или '631 728')
        elif raw_str.replace(" ", "").replace("-", "").isdigit() and len(raw_str.replace(" ", "").replace("-", "")) == 6:
            code_num = raw_str.replace(" ", "").replace("-", "")
            # Търсим сред всички близнаци с изпит днес в залата кой отговаря на този код
            candidate_twins = db.query(Student).join(ExamRegistration).join(Exam).filter(
                Student.is_twin_exception == True,
                Exam.room_number == room_number,
                func.date(Exam.date_time) == current_now.date()
            ).all()

            for cand in candidate_twins:
                c_now = generate_twin_dynamic_code(cand.id, cand.student_id_number, now_utc)
                c_prev = generate_twin_dynamic_code(cand.id, cand.student_id_number, now_utc - timedelta(seconds=300))
                c_next = generate_twin_dynamic_code(cand.id, cand.student_id_number, now_utc + timedelta(seconds=60))
                if code_num in (c_now, c_prev, c_next):
                    student = cand
                    break

            if not student:
                # Проверка за близнак в друга зала днес за по-информативна грешка
                all_twins_today = db.query(Student).join(ExamRegistration).join(Exam).filter(
                    Student.is_twin_exception == True,
                    func.date(Exam.date_time) == current_now.date()
                ).all()
                for cand in all_twins_today:
                    c_now = generate_twin_dynamic_code(cand.id, cand.student_id_number, now_utc)
                    c_prev = generate_twin_dynamic_code(cand.id, cand.student_id_number, now_utc - timedelta(seconds=300))
                    if code_num in (c_now, c_prev):
                        return {"admitted": False, "error": f"ГРЕШНА ЗАЛА! Студентът {cand.full_name} има изпит в друга зала днес"}

                # Ако не е динамичен код, проверяваме дали не е 6-цифрен факултетен номер
                student_by_fac = db.query(Student).filter(Student.student_id_number == raw_str).first()
                if student_by_fac and student_by_fac.is_twin_exception:
                    student = student_by_fac
                else:
                    return {"admitted": False, "error": "Невалиден или изтекъл 6-цифрен код за верификация"}

        # Вариант 3: Факултетен номер (ръчно въведен от квестора)
        else:
            student = db.query(Student).filter(Student.student_id_number == raw_str).first()
            if not student:
                return {"admitted": False, "error": f"Не е намерен студент с факултетен номер: {raw_str}"}

        # Общи проверки за намерения студент
        if not student:
            return {"admitted": False, "error": "Неуспешно идентифициране на студента"}

        if not student.is_twin_exception:
            return {"admitted": False, "error": f"Студентът {student.full_name} не е регистриран като изключение за близнак"}

        # 1. Вече допуснат ли е днес?
        already_in_room = db.query(AccessLog).filter(
            AccessLog.student_id == student.id,
            AccessLog.location == room_number,
            AccessLog.status.in_(["GRANTED", "GRANTED_TWIN_QR"]),
            func.date(AccessLog.created_at) == current_now.date()
        ).first()

        if already_in_room:
            return {"admitted": False, "error": f"Студентът {student.full_name} ВЕЧЕ е допуснат за този изпит"}

        # 2. Има ли изпит в тази зала днес?
        valid_registration = db.query(ExamRegistration).join(Exam).filter(
            ExamRegistration.student_id == student.id,
            Exam.room_number == room_number,
            func.date(Exam.date_time) == current_now.date(),
            Exam.date_time >= current_now - timedelta(minutes=15)
        ).order_by(Exam.date_time.asc()).first()

        if not valid_registration:
            valid_registration = db.query(ExamRegistration).join(Exam).filter(
                ExamRegistration.student_id == student.id,
                Exam.room_number == room_number,
                func.date(Exam.date_time) == current_now.date()
            ).order_by(Exam.date_time.desc()).first()

        if not valid_registration:
            anywhere_today = db.query(ExamRegistration).join(Exam).filter(
                ExamRegistration.student_id == student.id,
                func.date(Exam.date_time) == current_now.date()
            ).first()
            if anywhere_today:
                return {"admitted": False, "error": f"ГРЕШНА ЗАЛА! Студентът има изпит в Зала {anywhere_today.exam.room_number}"}
            else:
                return {"admitted": False, "error": f"Няма активен изпит за {student.full_name} днес в Зала {room_number}"}

        # 3. Времеви интервал за достъп (от 40 мин преди до 5 мин преди началото на изпита)
        exam_time = valid_registration.exam.date_time
        if exam_time.tzinfo is None:
            exam_time = exam_time.replace(tzinfo=timezone)
        else:
            exam_time = exam_time.astimezone(timezone)

        window_start = exam_time - timedelta(minutes=ADMISSION_WINDOW_START_MINUTES)
        window_end = exam_time - timedelta(minutes=ADMISSION_WINDOW_END_MINUTES)

        if not (window_start <= current_now <= window_end):
            if current_now < window_start:
                return {
                    "admitted": False,
                    "error": f"Твърде рано! Допускането за изпита започва в {window_start.strftime('%H:%M')} ч. (40 мин преди началото)."
                }
            elif current_now > exam_time + timedelta(hours=3):
                return {
                    "admitted": False,
                    "error": f"Приключил! Изпитът е приключил (насрочен за {exam_time.strftime('%H:%M')} ч.)."
                }
            else:
                return {
                    "admitted": False,
                    "error": f"Допускането през терминала приключи в {window_end.strftime('%H:%M')} ч. (5 мин преди изпита). Обърнете се към квестор."
                }

        # 4. Успешен допуск
        valid_registration.is_admitted = True
        valid_registration.admitted_at = current_now
        log_access_event(db, student.id, room_number, "GRANTED_TWIN_QR", deduplicate=True)

        if state is not None:
            state["qr_scan_mode"] = False
            state["qr_scan_expiry"] = 0.0
            state["green_state_end_time"] = time.time() + 5.0
            state["locked_student_name"] = student.full_name
            state["locked_fac_num"] = student.student_id_number
            state["status_text"] = f"ДОСТЪПЪТ РАЗРЕШЕН (Потвърден близнак: {student.full_name})!"
            state["status_type"] = "success"

        emit_room_event(room_number, "twin_qr_verified", {
            "room_number": room_number,
            "student_id": str(student.id),
            "student_name": student.full_name,
            "faculty_number": student.student_id_number
        })
        emit_room_event(room_number, "biometric_status", {
            "student_name": student.full_name,
            "faculty_number": student.student_id_number,
            "status_text": f"ДОСТЪПЪТ РАЗРЕШЕН (Потвърден близнак: {student.full_name})!",
            "status_type": "success"
        })
        emit_room_event(room_number, "roster_update", {
            "room_number": room_number,
            "student_id": str(student.id),
            "student_name": student.full_name,
            "faculty_number": student.student_id_number,
            "action": "twin_qr_admit"
        })

        return {
            "admitted": True,
            "student_id": str(student.id),
            "student_name": student.full_name,
            "faculty_number": student.student_id_number
        }
    finally:
        if close_db_here:
            db.close()


_YUNET_DETECTOR = None
_YUNET_PATH = os.path.join(os.path.dirname(__file__), "weights", "face_detection_yunet_2023mar.onnx")


def _get_yunet_detector(width: int = 320, height: int = 240):
    global _YUNET_DETECTOR
    if not os.path.exists(_YUNET_PATH):
        return None
    try:
        if _YUNET_DETECTOR is None:
            _YUNET_DETECTOR = cv2.FaceDetectorYN_create(_YUNET_PATH, "", (width, height), 0.55, 0.3, 5000)
        else:
            _YUNET_DETECTOR.setInputSize((width, height))
        return _YUNET_DETECTOR
    except Exception as e:
        print(f"[FaceDetector] YuNet init warning: {e}")
        return None


def detect_face_boxes(frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """
    Високонадеждно засичане на лица, устойчиво на сенки по лицето, слабо осветление и наклон:
      1. OpenCV DNN YuNet (FaceDetectorYN): дълбока невронна мрежа (~20ms CPU),
         обучена върху екстремни светлинни условия, силни сенки и широк диапазон от ъгли.
      2. Fallback: dlib HOG с адаптивно скалиране.
      3. Fallback: dlib HOG с 1 стъпка на upsampling.
      4. Fallback: dlib MMOD CNN за екстремни пози при отсъствие на YuNet.
    Връща координати във формат face_recognition: [(top, right, bottom, left)]
    """
    if frame is None or frame.size == 0:
        return []

    h, w = frame.shape[:2]

    # 1. Първи опит: YuNet (най-бърз и устойчив на сенки/неравномерна светлина)
    yunet = _get_yunet_detector(w, h)
    if yunet is not None:
        try:
            _, faces = yunet.detect(frame)
            if faces is not None and len(faces) > 0:
                boxes = []
                for f in faces:
                    x, y, fw, fh = int(f[0]), int(f[1]), int(f[2]), int(f[3])
                    # Разширяване на кутията с 12% марджин (за коректно откриване на ориентири от dlib върху брадичката и челото)
                    pad_w = int(fw * 0.12)
                    pad_h = int(fh * 0.12)
                    top = max(0, y - pad_h)
                    right = min(w, x + fw + pad_w)
                    bottom = min(h, y + fh + pad_h)
                    left = max(0, x - pad_w)
                    boxes.append((top, right, bottom, left))
                return boxes
        except Exception:
            pass

    # 2. Втори опит: dlib HOG
    scale = 0.5 if w <= 800 else 0.25
    inv_scale = 1.0 / scale
    small = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
    rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    locs = face_recognition.face_locations(rgb_small)

    # 3. Трети опит: dlib HOG с upsampling
    if not locs and scale <= 0.5:
        locs = face_recognition.face_locations(rgb_small, number_of_times_to_upsample=1)

    if locs:
        return [
            (
                max(0, int(t * inv_scale)),
                min(w, int(r * inv_scale)),
                min(h, int(b * inv_scale)),
                max(0, int(l * inv_scale))
            )
            for (t, r, b, l) in locs
        ]

    # 4. Четвърти опит: dlib CNN при отсъствие на YuNet
    try:
        cnn_scale = 0.25
        cnn_inv = 4.0
        cnn_small = cv2.resize(frame, (0, 0), fx=cnn_scale, fy=cnn_scale)
        cnn_rgb = cv2.cvtColor(cnn_small, cv2.COLOR_BGR2RGB)
        cnn_locs = face_recognition.face_locations(cnn_rgb, model="cnn")
        if cnn_locs:
            return [
                (
                    max(0, int(t * cnn_inv)),
                    min(w, int(r * cnn_inv)),
                    min(h, int(b * cnn_inv)),
                    max(0, int(l * cnn_inv))
                )
                for (t, r, b, l) in cnn_locs
            ]
    except Exception:
        pass

    return []


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

        # Проверка за активен режим на сканиране на QR код от камерата
        if state.get("qr_scan_mode", False):
            if current_time >= state.get("qr_scan_expiry", 0):
                # Автоматичен таймаут след зададения период (напр. 2 мин)
                state["qr_scan_mode"] = False
                state["qr_scan_expiry"] = 0.0
                state["status_text"] = "Времето за QR сканиране изтече. Възстановяване на лицево разпознаване."
                state["status_type"] = "idle"
                emit_room_event(room_number, "qr_scan_mode_changed", {
                    "room_number": room_number,
                    "enabled": False,
                    "reason": "timeout"
                })
                emit_room_event(room_number, "biometric_status", {
                    "student_name": "",
                    "faculty_number": "",
                    "status_text": state["status_text"],
                    "status_type": "idle"
                })
                return None

            # Опит за разчитане на QR код от кадъра чрез многостепенен алгоритъм (PyZbar + CLAHE + ArUco)
            try:
                qr_data = decode_qr_from_frame(frame)
                if qr_data:
                    res = process_twin_qr_admission(qr_data, room_number, state=state)
                    if res and res.get("admitted"):
                        return res
                    elif res and res.get("error"):
                        state["status_text"] = f"Грешка при QR: {res.get('error')}"
                        state["status_type"] = "danger"
                        emit_room_event(room_number, "biometric_status", {
                            "student_name": state.get("student_name", ""),
                            "faculty_number": state.get("faculty_number", ""),
                            "status_text": state["status_text"],
                            "status_type": "danger"
                        })
            except Exception as e:
                print(f"[QR Stream Scan Error] {e}")
            return None

        # Стандартно ИИ сканиране за лица (устойчиво на сенки, контраст и наклон)
        face_boxes = detect_face_boxes(frame)

        if not face_boxes:
            misses = state.get("consecutive_face_misses", 0) + 1
            state["consecutive_face_misses"] = misses
            last_seen = state.get("last_face_seen_time", 0.0)
            time_since_last = current_time - last_seen if last_seen > 0 else 999.0

            # Grace period: ако лице е било засечено преди по-малко от 1.8 сек и имаме под 3 последователни пропуска,
            # филтрираме временния шум (премигване, леко завъртане на глава, корекция на експозиция) и не нулираме интерфейса.
            if last_seen > 0 and time_since_last < 1.8 and misses < 3:
                return None

            state["student_name"] = ""
            state["faculty_number"] = ""
            state["status_text"] = "Няма зачетено лице пред камерата"
            state["status_type"] = "idle" # Сив/Бял цвят в UI
            state["liveness_scores"] = []
            state["liveness_student_id"] = None
            state["candidate_student_id"] = None
            return None

        # Координатите на първото лице в оригиналната резолюция на кадъра
        face_box_orig = face_boxes[0]
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Извличаме вектора от пълната резолюция за максимална прецизност
        orig_encodings = face_recognition.face_encodings(rgb_frame, [face_box_orig])
        if orig_encodings:
            face_encoding = orig_encodings[0]
        else:
            # Fallback с изравняване на контраста за екстремно засенчени лица
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            cl = clahe.apply(l)
            enhanced_rgb = cv2.cvtColor(cv2.merge((cl, a, b)), cv2.COLOR_LAB2RGB)
            enh_encs = face_recognition.face_encodings(enhanced_rgb, [face_box_orig])
            if enh_encs:
                face_encoding = enh_encs[0]
            else:
                misses = state.get("consecutive_face_misses", 0) + 1
                state["consecutive_face_misses"] = misses
                last_seen = state.get("last_face_seen_time", 0.0)
                time_since_last = current_time - last_seen if last_seen > 0 else 999.0
                if last_seen > 0 and time_since_last < 1.8 and misses < 3:
                    return None

                state["student_name"] = ""
                state["faculty_number"] = ""
                state["status_text"] = "Няма зачетено лице пред камерата"
                state["status_type"] = "idle"
                state["liveness_scores"] = []
                state["liveness_student_id"] = None
                state["candidate_student_id"] = None
                return None

        # Успешно засечено и векторизирано лице: нулираме брояча на пропуски
        state["consecutive_face_misses"] = 0
        state["last_face_seen_time"] = current_time

        student_found = None
        matching_students = []
        is_twin_case = False

        if known_face_encodings:
            try:
                TOLERANCE = float(os.getenv("FACE_RECOGNITION_TOLERANCE", "0.52"))
            except (ValueError, TypeError):
                TOLERANCE = 0.52
            distances = face_recognition.face_distance(known_face_encodings, face_encoding)
            matching_indices = [i for i, d in enumerate(distances) if d <= TOLERANCE]
            if matching_indices:
                best_match_index = int(np.argmin(distances))
                if isinstance(known_face_names, list):
                    student_found = known_face_names[best_match_index]
                    matching_students = [known_face_names[i] for i in matching_indices]
                else:
                    name_keys = list(known_face_names.keys())
                    full_name = name_keys[best_match_index]
                    student_found = known_face_names[full_name]
                    matching_students = [known_face_names[name_keys[i]] for i in matching_indices if i < len(name_keys)]

                is_twin_case = (
                    getattr(student_found, "is_twin_exception", False)
                    or any(getattr(s, "is_twin_exception", False) for s in matching_students)
                    or len(matching_students) > 1
                )

        if not student_found:
            state["student_name"] = "Непознат обект"
            state["faculty_number"] = "—"
            state["status_text"] = "ВНИМАНИЕ: Лицето липсва в базата данни!"
            state["status_type"] = "danger" # Червен цвят в UI
            return None

        # MiniFASNetV2 Anti-Spoofing проверка на лицето
        liveness_detector = get_liveness_detector()
        is_real_frame, real_score_frame = liveness_detector.check(frame, face_box_orig)

        try:
            score_num = float(real_score_frame)
        except (ValueError, TypeError):
            score_num = 1.0 if is_real_frame else 0.0

        detector_thresh = getattr(liveness_detector, 'threshold', None)
        if isinstance(detector_thresh, (int, float)):
            thresh_num = float(detector_thresh)
        else:
            try:
                thresh_num = float(os.getenv("LIVENESS_THRESHOLD", "0.60"))
            except (ValueError, TypeError):
                thresh_num = 0.60
        thresh_disp = f"{thresh_num:.2f}"

        # Буфер за времево изглаждане (2.0s прозорец за наблюдение)
        now = time.time()
        curr_student_id = str(student_found.id)
        if state.get("liveness_student_id") != curr_student_id or (now - state.get("liveness_last_seen", 0)) > 2.5:
            state["liveness_student_id"] = curr_student_id
            state["liveness_window_start"] = now
            state["liveness_scores"] = []

        state["liveness_last_seen"] = now
        state["liveness_scores"].append(score_num)

        highest_score = max(state["liveness_scores"]) if state["liveness_scores"] else score_num
        score_disp = f"{highest_score:.2f}"
        window_elapsed = now - state.get("liveness_window_start", now)
        buffer_duration = float(state.get("liveness_buffer_seconds", 0.0))

        is_real = bool(highest_score >= thresh_num)

        print(f"[Stream AI] Face: {student_found.full_name} | Liveness: {score_disp} (Frame: {score_num:.2f}, Thresh: {thresh_disp}) -> {'REAL' if is_real else 'BUFFER/SPOOF'}")

        if not is_real:
            if window_elapsed < buffer_duration:
                state["student_name"] = "Засечен близнак" if is_twin_case else student_found.full_name
                state["faculty_number"] = "—" if is_twin_case else student_found.student_id_number
                state["status_text"] = "Проверка на автентичност..."
                state["status_type"] = "idle"
                emit_room_event(room_number, "biometric_status", {
                    "student_name": state["student_name"],
                    "faculty_number": state["faculty_number"],
                    "status_text": state["status_text"],
                    "status_type": "idle"
                })
                return None

            db_spoof = SessionLocal()
            try:
                log_access_event(
                    db=db_spoof,
                    student_id=student_found.id,
                    location=room_number,
                    status="REJECTED_SPOOF",
                    deduplicate=True
                )
            finally:
                db_spoof.close()

            state["student_name"] = "Засечен близнак" if is_twin_case else student_found.full_name
            state["faculty_number"] = "—" if is_twin_case else student_found.student_id_number
            state["status_text"] = f"ОТКАЗАН ДОСТЪП: Засечена симулация (Liveness: {score_disp} < {thresh_disp})!"
            state["status_type"] = "danger"
            emit_room_event(room_number, "biometric_status", {
                "student_name": state["student_name"],
                "faculty_number": state["faculty_number"],
                "status_text": state["status_text"],
                "status_type": "danger"
            })
            return {"admitted": False, "reason": "spoof", "student_id": str(student_found.id), "student_name": student_found.full_name, "liveness_score": highest_score}

        # Проверка за случай на близнак (is_twin_exception == True или двусмислено биометрично съвпадение)
        # Поради генетично идентичната морфология се изисква динамичен QR пропуск
        if is_twin_case:
            state["student_name"] = "Засечен близнак"
            state["faculty_number"] = "—"
            state["status_text"] = "ВНИМАНИЕ: БЛИЗНАК - Изисква се сканиране на дигитален QR от приложението"
            state["status_type"] = "warning"
            emit_room_event(room_number, "twin_disambiguation_required", {
                "room_number": room_number,
                "student_id": str(student_found.id),
                "student_name": "Засечен близнак",
                "faculty_number": "—",
                "matching_students": [
                    {"student_id": str(s.id), "student_name": s.full_name, "faculty_number": s.student_id_number}
                    for s in matching_students
                ],
                "message": "ВНИМАНИЕ: БЛИЗНАК - Изисква се сканиране на дигитален QR от приложението"
            })
            emit_room_event(room_number, "biometric_status", {
                "student_name": "Засечен близнак",
                "faculty_number": "—",
                "status_text": state["status_text"],
                "status_type": "warning"
            })
            return {"admitted": False, "reason": "twin_qr_required", "student_id": str(student_found.id), "student_name": student_found.full_name}


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
                func.date(Exam.date_time) == current_now.date(),
                Exam.date_time >= current_now - timedelta(minutes=15)
            ).order_by(Exam.date_time.asc()).first()

            if not valid_registration:
                valid_registration = db.query(ExamRegistration).join(Exam).filter(
                    ExamRegistration.student_id == student_found.id,
                    Exam.room_number == room_number,
                    func.date(Exam.date_time) == current_now.date()
                ).order_by(Exam.date_time.desc()).first()
            
            is_time_valid = False
            window_start = None
            window_end = None
            if valid_registration:
                exam_time = valid_registration.exam.date_time
                if exam_time.tzinfo is None:
                    exam_time = exam_time.replace(tzinfo=timezone)
                else:
                    exam_time = exam_time.astimezone(timezone)
                window_start = exam_time - timedelta(minutes=ADMISSION_WINDOW_START_MINUTES)
                window_end = exam_time - timedelta(minutes=ADMISSION_WINDOW_END_MINUTES)
                print(f'Текущо време: {current_now}, Прозорец за допуск: [{window_start.strftime("%H:%M")} - {window_end.strftime("%H:%M")}], Изпит: {exam_time.strftime("%H:%M")}')
                if window_start <= current_now <= window_end:
                    is_time_valid = True

            # 3. Крайно решение
            state["student_name"] = student_found.full_name
            state["faculty_number"] = student_found.student_id_number

            if valid_registration and is_time_valid:
                # Маркираме допуска в базата данни
                valid_registration.is_admitted = True
                valid_registration.admitted_at = current_now
                # Записваме лога в базата
                log_access_event(db, student_found.id, room_number, "GRANTED", deduplicate=True)
                
                # Заключваме зеления статус на екрана за 5 секунди
                state["green_state_end_time"] = time.time() + 5.0  
                state["locked_student_name"] = student_found.full_name
                state["locked_fac_num"] = student_found.student_id_number
                state["status_text"] = "ДОСТЪПЪТ РАЗРЕШЕН!"
                state["status_type"] = "success" # Зелен цвят в UI
                return {"admitted": True, "student_id": str(student_found.id), "student_name": student_found.full_name}
                
            elif valid_registration and not is_time_valid:
                if window_start and current_now < window_start:
                    state["status_text"] = f"Твърде рано! Допускането започва в {window_start.strftime('%H:%M')} ч."
                    state["status_type"] = "warning"
                elif exam_time and current_now > exam_time + timedelta(hours=3):
                    state["status_text"] = f"Приключил (насрочен за {exam_time.strftime('%H:%M')} ч.)"
                    state["status_type"] = "danger"
                elif window_end:
                    state["status_text"] = f"Допускането през терминала приключи в {window_end.strftime('%H:%M')} ч. (Към квестор)"
                    state["status_type"] = "warning"
                else:
                    state["status_text"] = f"Интервал за достъп нарушен, изпитът започва в {valid_registration.exam.date_time.strftime('%H:%M')}."
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


_KNOWN_FACES_CACHE = {
    "encodings": None,
    "students": None,
    "last_loaded": 0.0
}


def _load_known_faces(ttl_seconds: float = 30.0):
    global _KNOWN_FACES_CACHE
    now = time.time()
    if (
        _KNOWN_FACES_CACHE["encodings"] is not None
        and _KNOWN_FACES_CACHE["students"] is not None
        and (now - _KNOWN_FACES_CACHE["last_loaded"] < ttl_seconds)
    ):
        return _KNOWN_FACES_CACHE["encodings"], _KNOWN_FACES_CACHE["students"]

    db = SessionLocal()
    try:
        students_in_db = db.query(Student).filter(
            Student.face_embedding != None,
            Student.status == "APPROVED"
        ).all()
        known_face_encodings = [np.array(s.face_embedding) for s in students_in_db]
        known_students = students_in_db
        _KNOWN_FACES_CACHE["encodings"] = known_face_encodings
        _KNOWN_FACES_CACHE["students"] = known_students
        _KNOWN_FACES_CACHE["last_loaded"] = now
        return known_face_encodings, known_students
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
        AI_ROOM_STATES[room_number]["qr_scan_mode"] = False
        AI_ROOM_STATES[room_number]["qr_scan_expiry"] = 0.0
        AI_ROOM_STATES[room_number]["consecutive_face_misses"] = 0
        AI_ROOM_STATES[room_number]["last_face_seen_time"] = 0.0
        AI_ROOM_STATES[room_number]["candidate_student_id"] = None

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


def get_room_camera_source(room_number: str) -> str:
    """Връща активния източник на видео за залата ('esp32' или 'webcam')."""
    return CAMERA_SOURCES.get(room_number, "esp32")


def set_room_camera_source(room_number: str, source: str) -> dict:
    """Превключва източника на видео за залата между 'esp32' и 'webcam'."""
    source = source.lower().strip()
    if source not in ("esp32", "webcam"):
        return {"success": False, "error": "Невалиден източник на камера. Допустими: 'esp32' или 'webcam'."}

    CAMERA_SOURCES[room_number] = source
    if room_number not in CAMERA_HEALTH:
        CAMERA_HEALTH[room_number] = {
            "last_frame_time": time.time(),
            "is_online": False,
            "esp32_ip": ACTIVE_CAMERAS.get(room_number),
            "stopped": False,
            "source": source
        }
    else:
        CAMERA_HEALTH[room_number]["source"] = source

    if source == "webcam":
        is_online = (time.time() - CAMERA_HEALTH[room_number].get("last_frame_time", 0) < 6.0)
        emit_room_event(room_number, "camera_status", {
            "room_number": room_number,
            "armed": is_online,
            "is_online": is_online,
            "source": "webcam",
            "stopped": False
        })
    else:
        is_online = room_number in ACTIVE_CAMERAS and CAMERA_HEALTH[room_number].get("is_online", False)
        emit_room_event(room_number, "camera_status", {
            "room_number": room_number,
            "armed": is_online,
            "is_online": is_online,
            "source": "esp32",
            "esp32_ip": ACTIVE_CAMERAS.get(room_number),
            "stopped": False
        })
    return {"success": True, "room_number": room_number, "source": source}


async def ingest_webcam_frame(room_number: str, jpg_bytes: bytes) -> dict:
    """
    Приемане на видео кадър от локалната уебкамера / USB камера на квестора.
    Обновява паметта, излъчва към абонатите и задейства лицевото разпознаване,
    жизнеността и QR сканирането в реален режим.
    """
    if not jpg_bytes or len(jpg_bytes) < 100:
        return {"success": False, "error": "Invalid frame data"}

    current_time = time.time()
    active_source = CAMERA_SOURCES.get(room_number, "esp32")
    if active_source == "esp32" and room_number in ACTIVE_CAMERAS:
        return {"success": False, "error": "Room camera source is set to esp32"}

    CAMERA_SOURCES[room_number] = "webcam"

    if room_number not in AI_ROOM_STATES:
        AI_ROOM_STATES[room_number] = {
            "student_name": "—",
            "faculty_number": "—",
            "status_text": "Очакване на обект пред камерата...",
            "status_type": "idle",
            "ai_busy": False,
            "green_state_end_time": 0,
            "locked_student_name": "",
            "locked_fac_num": "",
            "last_ai_run_time": 0,
            "qr_scan_mode": False,
            "qr_scan_expiry": 0.0,
            "liveness_buffer_seconds": 2.0,
            "consecutive_face_misses": 0,
            "last_face_seen_time": 0.0,
            "candidate_student_id": None,
        }
    state = AI_ROOM_STATES[room_number]

    if room_number not in CAMERA_HEALTH:
        CAMERA_HEALTH[room_number] = {
            "last_frame_time": current_time,
            "is_online": True,
            "esp32_ip": None,
            "stopped": False,
            "source": "webcam"
        }
        emit_room_event(room_number, "camera_status", {
            "room_number": room_number,
            "armed": True,
            "is_online": True,
            "source": "webcam",
            "stopped": False
        })
    else:
        was_online = CAMERA_HEALTH[room_number].get("is_online", False)
        CAMERA_HEALTH[room_number]["last_frame_time"] = current_time
        CAMERA_HEALTH[room_number]["is_online"] = True
        CAMERA_HEALTH[room_number]["source"] = "webcam"
        CAMERA_HEALTH[room_number]["stopped"] = False
        if not was_online:
            emit_room_event(room_number, "camera_status", {
                "room_number": room_number,
                "armed": True,
                "is_online": True,
                "source": "webcam",
                "stopped": False
            })

    LATEST_FRAMES[room_number] = jpg_bytes
    broadcast_frame(room_number, jpg_bytes)

    # Зелен екран (успешно допуснат студент)
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
        known_face_encodings, known_face_names = _load_known_faces()
        asyncio.create_task(run_heavy_ai_async(jpg_bytes, room_number, known_face_encodings, known_face_names))

    return {"success": True, "room_number": room_number, "source": "webcam"}


async def fetch_frames_from_esp32(room_number: str, esp32_ip: str):
    """
    Фонов таск за поемане на MJPEG стрийма от ESP32 (порт 81).
    Устойчив на мрежови прекъсвания с progressive backoff и автоматичен таймаут.
    """
    url = f"http://{esp32_ip}:81/stream"
    print(f"[Stream Worker] Стартиране на фоново четене от Зала {room_number} ({url})")
    
    # Кратко забавяне (300ms), за да позволим на ESP32 чиста обработка на отговора от регистрацията
    await asyncio.sleep(0.3)
    
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
        "last_ai_run_time": 0,
        "qr_scan_mode": False,
        "qr_scan_expiry": 0.0,
        "liveness_buffer_seconds": 2.0,
        "consecutive_face_misses": 0,
        "last_face_seen_time": 0.0,
        "candidate_student_id": None,
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
    offline_event_sent = False
    
    while room_number in ACTIVE_CAMERAS:
        try:
            # Периодично обновяваме лицата от БД на всеки 60 сек
            if time.time() - last_db_refresh > 60:
                known_face_encodings, known_face_names = _load_known_faces()
                last_db_refresh = time.time()

            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        now_ts = time.time()
                        if disconnect_start_time is None:
                            disconnect_start_time = now_ts
                        disconnected_duration = now_ts - disconnect_start_time
                        print(f"[Camera Warning] Сървърът на ESP32 в Зала {room_number} върна код {response.status_code} (прекъсване: {disconnected_duration:.1f}s)")
                        if disconnected_duration >= 4.0 and not offline_event_sent:
                            CAMERA_HEALTH[room_number]["is_online"] = False
                            offline_event_sent = True
                            emit_room_event(room_number, "camera_status", {
                                "room_number": room_number, "armed": False, "is_online": False, "esp32_ip": esp32_ip
                            })
                        await asyncio.sleep(0.5)
                        continue
                    
                    was_offline = offline_event_sent or not CAMERA_HEALTH[room_number].get("is_online", False)
                    CAMERA_HEALTH[room_number]["is_online"] = True
                    CAMERA_HEALTH[room_number]["last_frame_time"] = time.time()
                    if CAMERA_SOURCES.get(room_number, "esp32") == "esp32":
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
                    
                    # Нулиране на брояча и състоянието при успешна връзка
                    retry_count = 0
                    disconnect_start_time = None
                    offline_event_sent = False

                    bytes_buffer = b""
                    fps_count = 0
                    fps_bytes_total = 0
                    fps_last_time = time.time()
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
                                    fps_count += 1
                                    fps_bytes_total += len(jpg_bytes)
                                    if current_time - fps_last_time >= 5.0:
                                        elapsed = current_time - fps_last_time
                                        actual_fps = fps_count / elapsed
                                        avg_frame_kb = (fps_bytes_total / fps_count) / 1024.0 if fps_count > 0 else 0
                                        bandwidth_kbps = (fps_bytes_total / 1024.0) / elapsed if elapsed > 0 else 0
                                        print(f"[Stream FPS] Ingesting {actual_fps:.2f} FPS | Avg Frame: {avg_frame_kb:.1f} KB | Bandwidth: {bandwidth_kbps:.1f} KB/s for Room {room_number}")
                                        fps_count = 0
                                        fps_bytes_total = 0
                                        fps_last_time = current_time

                                    # Ако квесторът е активирал локална уебкамера ('webcam'),
                                    # поддържаме TCP потока на ESP32 чист, но НЕ презаписваме кадри и НЕ стартираме ИИ
                                    if CAMERA_SOURCES.get(room_number, "esp32") != "esp32":
                                        continue

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

            disconnected_duration = now_ts - disconnect_start_time

            # Grace Period (4.0 секунди):
            # Не излъчваме веднага офлайн статус и пазим последния кадър (freeze-frame),
            # за да не премигва интерфейсът при кратковременни микро-смущения на Wi-Fi връзката.
            if disconnected_duration >= 4.0:
                CAMERA_HEALTH[room_number]["is_online"] = False
                state["student_name"] = "—"
                state["faculty_number"] = "—"
                state["status_text"] = "Камерата е офлайн (няма връзка)"
                state["status_type"] = "danger"

                if not offline_event_sent:
                    offline_event_sent = True
                    emit_room_event(room_number, "camera_status", {
                        "room_number": room_number, "armed": False, "is_online": False, "esp32_ip": esp32_ip
                    })
                    emit_room_event(room_number, "biometric_status", {
                        "student_name": "—", "faculty_number": "—", "status_text": state["status_text"], "status_type": "danger"
                    })

            # Изчистваме стария кадър само след продължителна липса на връзка (над 10 сек)
            if disconnected_duration >= 10.0:
                LATEST_FRAMES.pop(room_number, None)

            # Автоматично освобождаване на ресурсите след 120 сек без връзка
            if disconnected_duration > 120.0:
                print(f"[Auto-Deactivate] ESP32 в Зала {room_number} не отговаря над 2 минути. Освобождаване на ресурсите.")
                stop_camera_stream(room_number, reason="timeout")
                break

            # Instant Reconnect при първите 2 опита, последван от плавен progressive backoff
            retry_count += 1
            if retry_count <= 2:
                sleep_sec = 0.2
            elif retry_count <= 5:
                sleep_sec = 1.0
            elif retry_count <= 8:
                sleep_sec = 2.0
            else:
                sleep_sec = 5.0

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

        while room_number in ACTIVE_CAMERAS or CAMERA_SOURCES.get(room_number) == "webcam":
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


async def generate_debug_stream(room_number: str, target_student_id: str, tolerance: float = 0.52):
    """
    Интерактивен MJPEG стрийм за дебъгване и визуален анализ на биометричното разпознаване.
    Сравнява в реално време всяко засечено лице в кадъра с 128-мерния вектор на целевия студент.
    Изчертава на кадъра:
      - Bounding box около лицето (зелен при съвпадение <= tolerance, оранжев/червен при разминаване)
      - Евклидово разстояние (напр. 'Dist: 0.485 (Limit: 0.520)')
      - Косинусово сходство (напр. 'Similarity: 92.4%')
      - Целеви студент (Име и факултетен номер)
      - Статус: 'MATCH' или 'NO MATCH'
    НЕ блокира за liveness / анти-спуфинг, за да се изолира и тества чистото разпознаване на лицето.
    """
    db = SessionLocal()
    try:
        target_student = db.query(Student).filter(Student.id == target_student_id).first()
        if not target_student or target_student.face_embedding is None:
            target_name = target_student.full_name if target_student else "Неизвестен"
            target_fac = target_student.student_id_number if target_student else "—"
            target_embedding = None
        else:
            target_name = target_student.full_name
            target_fac = target_student.student_id_number
            target_embedding = np.array(target_student.face_embedding, dtype=np.float64)
    finally:
        db.close()

    target_name_ascii = _transliterate_for_cv2(target_name)
    queue = subscribe_client(room_number)
    try:
        while room_number in ACTIVE_CAMERAS or CAMERA_SOURCES.get(room_number) == "webcam":
            try:
                frame_bytes = await asyncio.wait_for(queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                health = CAMERA_HEALTH.get(room_number, {})
                if not (health.get("is_online", False) and (time.time() - health.get("last_frame_time", 0) < 8.0)):
                    await asyncio.sleep(0.5)
                continue

            nparr = np.frombuffer(frame_bytes, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if frame is None:
                continue

            h_orig, w_orig = frame.shape[:2]

            boxes = detect_face_boxes(frame)

            face_detected = False
            euclidean_dist = None
            cosine_sim = None
            is_match = False
            box_orig = None

            if boxes and target_embedding is not None:
                face_detected = True
                box_orig = boxes[0]
                rgb_full = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                encs = face_recognition.face_encodings(rgb_full, [box_orig])
                if encs:
                    live_enc = np.array(encs[0], dtype=np.float64)
                    euclidean_dist = float(np.linalg.norm(target_embedding - live_enc))
                    norm_t = np.linalg.norm(target_embedding)
                    norm_l = np.linalg.norm(live_enc)
                    if norm_t > 0 and norm_l > 0:
                        raw_cos = float(np.dot(target_embedding, live_enc) / (norm_t * norm_l))
                        cosine_sim = float(max(0.0, min(100.0, raw_cos * 100.0)))
                    else:
                        cosine_sim = 0.0
                    is_match = bool(euclidean_dist <= tolerance)

            # Записваме телеметрията за реално време в речника
            DEBUG_TELEMETRY[room_number] = {
                "has_frame": True,
                "face_detected": face_detected,
                "target_student_id": target_student_id,
                "target_name": target_name,
                "target_fac": target_fac,
                "euclidean_distance": round(euclidean_dist, 4) if euclidean_dist is not None else None,
                "cosine_similarity": round(cosine_sim, 2) if cosine_sim is not None else None,
                "tolerance": float(tolerance),
                "is_match": is_match,
                "timestamp": time.time()
            }

            # Рисуване на визуален HUD овърлей (БЕЗ емоджита!)
            # 1. Горен информационен панел
            header_h = 62
            overlay = frame.copy()
            cv2.rectangle(overlay, (0, 0), (w_orig, header_h), (15, 23, 42), -1)
            cv2.addWeighted(overlay, 0.85, frame, 0.15, 0, frame)

            target_label = f"TARGET: {target_name_ascii} ({target_fac})"
            cv2.putText(frame, target_label, (16, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

            if target_embedding is None:
                cv2.putText(frame, "STATUS: No embedding stored for this student", (16, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1, cv2.LINE_AA)
            elif face_detected and euclidean_dist is not None:
                color = (0, 200, 80) if is_match else (0, 80, 240)
                status_str = "MATCH" if is_match else "NO MATCH"
                
                # Изчертаваме кутия около лицето
                b_top, b_right, b_bottom, b_left = box_orig
                cv2.rectangle(frame, (b_left, b_top), (b_right, b_bottom), color, 2)

                dist_tag = f"Dist: {euclidean_dist:.3f}"
                cv2.rectangle(frame, (b_left, max(0, b_top - 24)), (b_left + 120, b_top), color, -1)
                cv2.putText(frame, dist_tag, (b_left + 6, max(14, b_top - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

                metrics_label = f"DIST: {euclidean_dist:.3f} (Limit: {tolerance:.3f}) | SIMILARITY: {cosine_sim:.1f}% | [{status_str}]"
                cv2.putText(frame, metrics_label, (16, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
            else:
                cv2.putText(frame, "STATUS: Looking for face in stream...", (16, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (148, 163, 184), 1, cv2.LINE_AA)

            # Долен статус бар
            footer_h = 28
            overlay_footer = frame.copy()
            cv2.rectangle(overlay_footer, (0, h_orig - footer_h), (w_orig, h_orig), (15, 23, 42), -1)
            cv2.addWeighted(overlay_footer, 0.85, frame, 0.15, 0, frame)
            footer_text = f"ESP32-CAM ROOM {room_number} | BIOMETRIC COMPARATOR (NO LIVENESS BLOCK)"
            cv2.putText(frame, footer_text, (16, h_orig - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (148, 163, 184), 1, cv2.LINE_AA)

            # Енкодване към JPEG
            ret, jpeg_buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ret:
                continue

            out_bytes = jpeg_buf.tobytes()
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n'
                b'Content-Length: ' + str(len(out_bytes)).encode() + b'\r\n\r\n' +
                out_bytes + b'\r\n'
            )
    finally:
        unsubscribe_client(room_number, queue)