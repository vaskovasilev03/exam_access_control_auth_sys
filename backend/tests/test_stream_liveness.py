import os
import unittest
import json
import uuid
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import numpy as np
import cv2
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

os.environ["SUPERADMIN_EMAIL"] = "superadmin@tu-sofia.bg"
os.environ["SUPERADMIN_PASSWORD"] = "SuperAdmin123!"
os.environ["SUPERADMIN_NAME"] = "Super Administrator"

from app.main import app, AI_ROOM_STATES
from app.database import get_db, SessionLocal, init_db
from app.models import Student, Examiner, Exam, ExamRegistration, AccessLog, SessionType
from app.seed import seed_superadmin
from app.auth import get_password_hash, create_access_token
from app.stream_esp32 import (
    analyze_frame_outside_ui,
    set_room_qr_scan_mode,
    process_twin_qr_admission,
    generate_twin_dynamic_code,
    decode_qr_from_frame,
    detect_face_boxes,
    set_room_camera_source,
    get_room_camera_source,
    CAMERA_SOURCES
)
from tests.test_data_isolation import TestDataSnapshot, clean_known_test_data

ROOM = "TEST_ROOM_STREAM_4"
TIMEZONE = ZoneInfo("Europe/Sofia")


class StreamLivenessTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        db = SessionLocal()
        try:
            clean_known_test_data(db)
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        db = SessionLocal()
        try:
            clean_known_test_data(db)
        finally:
            db.close()

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.clear()
        self.db: Session = SessionLocal()
        clean_known_test_data(self.db)
        self.snapshot = TestDataSnapshot(self.db)
        seed_superadmin(self.db)

        # 1. Create Examiner
        self.examiner = self.db.query(Examiner).filter(Examiner.email == "examiner_stream@tu-sofia.bg").first()
        if not self.examiner:
            self.examiner = Examiner(
                full_name="Квестор Стрийм",
                email="examiner_stream@tu-sofia.bg",
                hashed_password=get_password_hash("ExaminerPass123!"),
                is_verified=True
            )
            self.db.add(self.examiner)

        # 2. Create Standard Approved Student
        self.dummy_embedding = [0.05] * 128
        self.student = Student(
            full_name="Тестов Студент Нормален",
            student_id_number="12128801",
            email="normal_student@tu-sofia.bg",
            hashed_password=get_password_hash("StudentPass123!"),
            faculty="ФКСУ",
            specialty="КСИ",
            course=3,
            stream=1,
            group=45,
            status="APPROVED",
            face_embedding=self.dummy_embedding,
            is_twin_exception=False,
            gdpr_consent_given=True
        )
        self.db.add(self.student)

        # 3. Create Twin Student
        self.twin_student = Student(
            full_name="Тестов Близнак Студент",
            student_id_number="12128802",
            email="twin_student@tu-sofia.bg",
            hashed_password=get_password_hash("TwinPass123!"),
            faculty="ФКСУ",
            specialty="КСИ",
            course=3,
            stream=1,
            group=45,
            status="APPROVED",
            face_embedding=self.dummy_embedding,
            is_twin_exception=True,
            gdpr_consent_given=True
        )
        self.db.add(self.twin_student)

        # 4. Create Active Exam in ROOM today
        now = datetime.now(TIMEZONE)
        self.exam = Exam(
            subject="Биометрични системи и сигурност",
            date_time=now + timedelta(minutes=20),
            room_number=ROOM,
            lecturer="Проф. Димитров",
            session_type=SessionType.SUMMER,
            faculty="ФКСУ",
            specialty="КСИ",
            course=3,
            stream="1",
            group="1"
        )
        self.db.add(self.exam)
        self.db.commit()
        self.db.refresh(self.examiner)
        self.db.refresh(self.student)
        self.db.refresh(self.twin_student)
        self.db.refresh(self.exam)

        # 5. Register students for the exam
        self.reg_normal = ExamRegistration(
            student_id=self.student.id,
            exam_id=self.exam.id,
            is_admitted=False
        )
        self.reg_twin = ExamRegistration(
            student_id=self.twin_student.id,
            exam_id=self.exam.id,
            is_admitted=False
        )
        self.db.add(self.reg_normal)
        self.db.add(self.reg_twin)
        self.db.commit()

        self.examiner_token = create_access_token({
            "sub": str(self.examiner.id),
            "role": "examiner",
            "is_superadmin": False
        })
        self.superadmin_token = create_access_token({
            "sub": "superadmin@tu-sofia.bg",
            "role": "superadmin",
            "is_superadmin": True
        })

        # Initialize AI_ROOM_STATES for the test room
        AI_ROOM_STATES[ROOM] = {
            "student_name": "—",
            "faculty_number": "—",
            "status_text": "Очакване на студент...",
            "status_type": "idle",
            "ai_busy": False,
            "green_state_end_time": 0,
            "locked_student_name": "",
            "locked_fac_num": "",
            "last_ai_run_time": 0,
            "qr_scan_mode": False,
            "qr_scan_expiry": 0.0
        }

        # Mock frame bytes (simple black JPEG image)
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        _, encoded = cv2.imencode(".jpg", img)
        self.dummy_jpg = encoded.tobytes()

    def tearDown(self):
        try:
            AI_ROOM_STATES.pop(ROOM, None)
            self.snapshot.cleanup()
            clean_known_test_data(self.db)
        finally:
            self.db.close()

    @patch("app.stream_esp32.face_recognition.face_locations")
    @patch("app.stream_esp32.face_recognition.face_encodings")
    @patch("app.stream_esp32.get_liveness_detector")
    def test_01_stream_anti_spoof_detection_rejects_photo(self, mock_get_detector, mock_encodings, mock_locations):
        """ Stream rejects spoof attack (real_score < 0.85), logs REJECTED_SPOOF, and denies entry """
        mock_locations.return_value = [(20, 80, 80, 20)]
        mock_encodings.return_value = [np.array(self.dummy_embedding)]

        mock_detector_inst = MagicMock()
        mock_detector_inst.check.return_value = (False, 0.12)
        mock_get_detector.return_value = mock_detector_inst

        known_encodings = [np.array(self.dummy_embedding)]
        known_names = {self.student.full_name: self.student}
        state = AI_ROOM_STATES[ROOM]

        result = analyze_frame_outside_ui(self.dummy_jpg, ROOM, known_encodings, known_names, state)

        self.assertIsNotNone(result)
        self.assertFalse(result.get("admitted"))
        self.assertEqual(result.get("reason"), "spoof")
        self.assertEqual(state["status_type"], "danger")
        self.assertIn("Засечена симулация", state["status_text"])

        # Verify AccessLog has REJECTED_SPOOF
        log = self.db.query(AccessLog).filter(
            AccessLog.student_id == self.student.id,
            AccessLog.location == ROOM,
            AccessLog.status == "REJECTED_SPOOF"
        ).first()
        self.assertIsNotNone(log)

        # Verify student was NOT admitted
        self.db.refresh(self.reg_normal)
        self.assertFalse(self.reg_normal.is_admitted)

    @patch("app.stream_esp32.face_recognition.face_locations")
    @patch("app.stream_esp32.face_recognition.face_encodings")
    @patch("app.stream_esp32.get_liveness_detector")
    def test_02_stream_liveness_passed_admits_student(self, mock_get_detector, mock_encodings, mock_locations):
        """ Stream accepts live student (real_score >= 0.85), admits them and logs GRANTED """
        mock_locations.return_value = [(20, 80, 80, 20)]
        mock_encodings.return_value = [np.array(self.dummy_embedding)]

        mock_detector_inst = MagicMock()
        mock_detector_inst.check.return_value = (True, 0.96)
        mock_get_detector.return_value = mock_detector_inst

        known_encodings = [np.array(self.dummy_embedding)]
        known_names = {self.student.full_name: self.student}
        state = AI_ROOM_STATES[ROOM]

        result = analyze_frame_outside_ui(self.dummy_jpg, ROOM, known_encodings, known_names, state)

        self.assertIsNotNone(result)
        self.assertTrue(result.get("admitted"))
        self.assertEqual(state["status_type"], "success")
        self.assertIn("ДОСТЪПЪТ РАЗРЕШЕН", state["status_text"])

        # Verify AccessLog has GRANTED
        log = self.db.query(AccessLog).filter(
            AccessLog.student_id == self.student.id,
            AccessLog.location == ROOM,
            AccessLog.status == "GRANTED"
        ).first()
        self.assertIsNotNone(log)

        # Verify registration admitted
        self.db.refresh(self.reg_normal)
        self.assertTrue(self.reg_normal.is_admitted)

    @patch("app.stream_esp32.face_recognition.face_locations")
    @patch("app.stream_esp32.face_recognition.face_encodings")
    @patch("app.stream_esp32.get_liveness_detector")
    def test_03_stream_twin_detection_requires_qr(self, mock_get_detector, mock_encodings, mock_locations):
        """ Stream identifies twin student and halts auto-admission requiring dynamic QR pass """
        mock_locations.return_value = [(20, 80, 80, 20)]
        mock_encodings.return_value = [np.array(self.dummy_embedding)]

        mock_detector_inst = MagicMock()
        mock_detector_inst.check.return_value = (True, 0.95)
        mock_get_detector.return_value = mock_detector_inst

        known_encodings = [np.array(self.dummy_embedding)]
        known_names = {self.twin_student.full_name: self.twin_student}
        state = AI_ROOM_STATES[ROOM]

        result = analyze_frame_outside_ui(self.dummy_jpg, ROOM, known_encodings, known_names, state)

        self.assertIsNotNone(result)
        self.assertFalse(result.get("admitted"))
        self.assertEqual(result.get("reason"), "twin_qr_required")
        self.assertEqual(state["status_type"], "warning")
        self.assertIn("БЛИЗНАК", state["status_text"])
        self.assertEqual(state["student_name"], "Засечен близнак")
        self.assertEqual(state["faculty_number"], "—")

        # Verify twin was NOT auto-admitted
        self.db.refresh(self.reg_twin)
        self.assertFalse(self.reg_twin.is_admitted)

    def test_04_toggle_qr_scan_mode_api(self):
        """ Examiner endpoint toggles temporary stream QR scanning mode on and off """
        # Enable QR mode
        res = self.client.post(
            f"/api/v1/exams/{ROOM}/toggle-qr-scan-mode",
            headers={"Authorization": f"Bearer {self.examiner_token}"},
            json={"enabled": True, "duration_seconds": 120}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("enabled"))
        self.assertGreater(data.get("expires_in_seconds"), 100)
        self.assertTrue(AI_ROOM_STATES[ROOM]["qr_scan_mode"])

        # Disable QR mode
        res2 = self.client.post(
            f"/api/v1/exams/{ROOM}/toggle-qr-scan-mode",
            headers={"Authorization": f"Bearer {self.examiner_token}"},
            json={"enabled": False}
        )
        self.assertEqual(res2.status_code, 200)
        self.assertFalse(res2.json().get("enabled"))
        self.assertFalse(AI_ROOM_STATES[ROOM]["qr_scan_mode"])

    @patch("app.stream_esp32.QR_DETECTOR")
    def test_05_stream_camera_qr_scan_auto_admits_twin(self, mock_qr_detector):
        """ In QR scan mode, camera decodes twin dynamic QR pass, admits student, and exits QR mode """
        state = AI_ROOM_STATES[ROOM]
        set_room_qr_scan_mode(ROOM, enabled=True, duration_seconds=120)
        self.assertTrue(state["qr_scan_mode"])

        now_utc = datetime.now(ZoneInfo("UTC"))
        qr_payload = {
            "type": "TWIN_EXAM_PASS",
            "student_id": str(self.twin_student.id),
            "student_id_number": self.twin_student.student_id_number,
            "full_name": self.twin_student.full_name,
            "faculty": self.twin_student.faculty,
            "specialty": self.twin_student.specialty,
            "is_twin_exception": True,
            "timestamp": now_utc.isoformat()
        }
        mock_qr_detector.detectAndDecode.return_value = (json.dumps(qr_payload), None, None)

        result = analyze_frame_outside_ui(self.dummy_jpg, ROOM, [], {}, state)

        self.assertIsNotNone(result)
        self.assertTrue(result.get("admitted"))
        self.assertEqual(result.get("student_id"), str(self.twin_student.id))

        # Check DB admission and log
        self.db.refresh(self.reg_twin)
        self.assertTrue(self.reg_twin.is_admitted)

        log = self.db.query(AccessLog).filter(
            AccessLog.student_id == self.twin_student.id,
            AccessLog.location == ROOM,
            AccessLog.status == "GRANTED_TWIN_QR"
        ).first()
        self.assertIsNotNone(log)

        # Check state: qr_scan_mode automatically disabled, green lock active
        self.assertFalse(state["qr_scan_mode"])
        self.assertEqual(state["status_type"], "success")

    def test_06_verify_twin_qr_manual_api_success(self):
        """ Examiner manually submits valid dynamic QR payload and successfully admits twin """
        now_utc = datetime.now(ZoneInfo("UTC"))
        qr_payload = {
            "type": "TWIN_EXAM_PASS",
            "student_id": str(self.twin_student.id),
            "student_id_number": self.twin_student.student_id_number,
            "full_name": self.twin_student.full_name,
            "faculty": self.twin_student.faculty,
            "specialty": self.twin_student.specialty,
            "is_twin_exception": True,
            "timestamp": now_utc.isoformat()
        }

        res = self.client.post(
            f"/api/v1/exams/{ROOM}/verify-twin-qr",
            headers={"Authorization": f"Bearer {self.examiner_token}"},
            json={"qr_payload": json.dumps(qr_payload)}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("admitted"))
        self.assertEqual(data.get("student_name"), self.twin_student.full_name)

        self.db.refresh(self.reg_twin)
        self.assertTrue(self.reg_twin.is_admitted)

        log = self.db.query(AccessLog).filter(
            AccessLog.student_id == self.twin_student.id,
            AccessLog.location == ROOM,
            AccessLog.status == "GRANTED_TWIN_QR"
        ).first()
        self.assertIsNotNone(log)

    def test_07_verify_twin_qr_expired_rejected(self):
        """ Expired QR pass (> 5 minutes) is rejected with HTTP 400 """
        expired_utc = datetime.now(ZoneInfo("UTC")) - timedelta(minutes=15)
        qr_payload = {
            "type": "TWIN_EXAM_PASS",
            "student_id": str(self.twin_student.id),
            "student_id_number": self.twin_student.student_id_number,
            "full_name": self.twin_student.full_name,
            "is_twin_exception": True,
            "timestamp": expired_utc.isoformat()
        }

        res = self.client.post(
            f"/api/v1/exams/{ROOM}/verify-twin-qr",
            headers={"Authorization": f"Bearer {self.examiner_token}"},
            json={"qr_payload": json.dumps(qr_payload)}
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Изтекъл изпитен пропуск", res.json().get("detail", ""))

    def test_08_verify_twin_qr_non_twin_rejected(self):
        """ Standard student without is_twin_exception cannot use twin QR pass """
        now_utc = datetime.now(ZoneInfo("UTC"))
        qr_payload = {
            "type": "TWIN_EXAM_PASS",
            "student_id": str(self.student.id),
            "student_id_number": self.student.student_id_number,
            "full_name": self.student.full_name,
            "is_twin_exception": False,
            "timestamp": now_utc.isoformat()
        }

        res = self.client.post(
            f"/api/v1/exams/{ROOM}/verify-twin-qr",
            headers={"Authorization": f"Bearer {self.examiner_token}"},
            json={"qr_payload": json.dumps(qr_payload)}
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("не е регистриран като изключение за близнак", res.json().get("detail", ""))

    def test_09_verify_twin_qr_wrong_room(self):
        """ Twin QR verification fails if student has an exam in another room """
        WRONG_ROOM = "ROOM_DIFFERENT_999"
        now_utc = datetime.now(ZoneInfo("UTC"))
        qr_payload = {
            "type": "TWIN_EXAM_PASS",
            "student_id": str(self.twin_student.id),
            "student_id_number": self.twin_student.student_id_number,
            "full_name": self.twin_student.full_name,
            "is_twin_exception": True,
            "timestamp": now_utc.isoformat()
        }

        res = self.client.post(
            f"/api/v1/exams/{WRONG_ROOM}/verify-twin-qr",
            headers={"Authorization": f"Bearer {self.examiner_token}"},
            json={"qr_payload": json.dumps(qr_payload)}
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn(f"ГРЕШНА ЗАЛА! Студентът има изпит в Зала {ROOM}", res.json().get("detail", ""))

    def test_10_verify_twin_manual_dynamic_code_success(self):
        """ Examiner enters 6-digit dynamic passcode from mobile app and admits twin """
        now_utc = datetime.now(ZoneInfo("UTC"))
        code = generate_twin_dynamic_code(self.twin_student.id, self.twin_student.student_id_number, now_utc)

        res = self.client.post(
            f"/api/v1/exams/{ROOM}/verify-twin-qr",
            headers={"Authorization": f"Bearer {self.examiner_token}"},
            json={"qr_payload": code}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("admitted"))
        self.assertEqual(data.get("student_name"), self.twin_student.full_name)

        self.db.refresh(self.reg_twin)
        self.assertTrue(self.reg_twin.is_admitted)

        log = self.db.query(AccessLog).filter(
            AccessLog.student_id == self.twin_student.id,
            AccessLog.location == ROOM,
            AccessLog.status == "GRANTED_TWIN_QR"
        ).first()
        self.assertIsNotNone(log)

    def test_11_verify_twin_manual_faculty_number_rejected(self):
        """ Faculty number is strictly disallowed as a passcode for twins """
        res = self.client.post(
            f"/api/v1/exams/{ROOM}/verify-twin-qr",
            headers={"Authorization": f"Bearer {self.examiner_token}"},
            json={"qr_payload": self.twin_student.student_id_number}
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Невалиден", res.json().get("detail", ""))

    def test_12_verify_twin_manual_invalid_code_fails(self):
        """ Entering an invalid 6-digit code returns HTTP 400 """
        res = self.client.post(
            f"/api/v1/exams/{ROOM}/verify-twin-qr",
            headers={"Authorization": f"Bearer {self.examiner_token}"},
            json={"qr_payload": "000000"}
        )
        self.assertEqual(res.status_code, 400)
    def test_13_biometric_debugger_endpoints(self):
        """ Test debug students list, cameras, standalone page and compare telemetry endpoints """
        # 1. Non-superadmin examiner is forbidden from accessing the standalone debugger page
        examiner_page_res = self.client.get(
            "/examiner/biometric-debugger",
            headers={"Authorization": f"Bearer {self.examiner_token}"}
        )
        self.assertEqual(examiner_page_res.status_code, 403)

        # 2. Superadmin successfully accesses the standalone debugger page
        sa_page_res = self.client.get(
            "/examiner/biometric-debugger",
            headers={"Authorization": f"Bearer {self.superadmin_token}"}
        )
        self.assertEqual(sa_page_res.status_code, 200)
        self.assertIn("Биометричен Дебъгер", sa_page_res.text)

        # 3. Non-superadmin is forbidden from debugger cameras API
        cam_forbidden = self.client.get(
            "/api/v1/examiner/debugger/cameras",
            headers={"Authorization": f"Bearer {self.examiner_token}"}
        )
        self.assertEqual(cam_forbidden.status_code, 403)

        # 4. Superadmin accesses debugger cameras API
        cam_res = self.client.get(
            "/api/v1/examiner/debugger/cameras",
            headers={"Authorization": f"Bearer {self.superadmin_token}"}
        )
        self.assertEqual(cam_res.status_code, 200)
        cameras = cam_res.json()
        self.assertIsInstance(cameras, list)

        # 5. Superadmin accesses debugger students list API
        stu_res = self.client.get(
            f"/api/v1/examiner/debugger/students?room_number={ROOM}",
            headers={"Authorization": f"Bearer {self.superadmin_token}"}
        )
        self.assertEqual(stu_res.status_code, 200)
        students = stu_res.json()
        self.assertIsInstance(students, list)
        self.assertGreater(len(students), 0)

        s0 = students[0]
        self.assertIn("id", s0)
        self.assertIn("full_name", s0)
        self.assertIn("student_id_number", s0)
        self.assertIn("is_registered_in_room", s0)

        # 6. Compare telemetry endpoint requires superadmin
        tel_forbidden = self.client.get(
            f"/api/v1/exams/{ROOM}/debug/compare-telemetry",
            headers={"Authorization": f"Bearer {self.examiner_token}"}
        )
        self.assertEqual(tel_forbidden.status_code, 403)

        tel_res = self.client.get(
            f"/api/v1/exams/{ROOM}/debug/compare-telemetry",
            headers={"Authorization": f"Bearer {self.superadmin_token}"}
        )
        self.assertEqual(tel_res.status_code, 200)
        tel_data = tel_res.json()
        self.assertIn("has_frame", tel_data)
        self.assertIn("face_detected", tel_data)
        self.assertIn("tolerance", tel_data)

    def test_decode_qr_from_frame_modes(self):
        """Verify multi-pass QR decoder handles normal, inverted (Dark Mode), and central crop frames."""
        enc = cv2.QRCodeEncoder.create()
        test_payload = "EXAM_ROOM_TOKEN_987654"
        qr_mat = enc.encode(test_payload)
        self.assertIsNotNone(qr_mat)

        # Scale up to simulate real camera resolution
        qr_img = cv2.resize(qr_mat, (320, 320), interpolation=cv2.INTER_NEAREST)
        qr_bgr = cv2.cvtColor(qr_img, cv2.COLOR_GRAY2BGR)

        # 1. Standard BGR
        decoded = decode_qr_from_frame(qr_bgr)
        self.assertEqual(decoded, test_payload)

        # 2. Inverted (Dark Mode phone screen)
        inv_bgr = cv2.bitwise_not(qr_bgr)
        decoded_inv = decode_qr_from_frame(inv_bgr)
        self.assertEqual(decoded_inv, test_payload)

        # 3. Embedded in larger frame with padding (simulating camera pointing at phone)
        canvas = np.zeros((480, 640, 3), dtype=np.uint8)
        canvas[80:400, 160:480] = qr_bgr
        decoded_canvas = decode_qr_from_frame(canvas)
        self.assertEqual(decoded_canvas, test_payload)

        # 4. Empty / None frame
        self.assertIsNone(decode_qr_from_frame(None))
        self.assertIsNone(decode_qr_from_frame(np.zeros((0, 0, 3), dtype=np.uint8)))

    def test_15_face_detection_temporal_debouncing(self):
        """
        Тества темпоралното филтриране и хистерезис при засичане на лица:
        - Преходни единични пропуски (1-2 кадъра < 1.8s) не нулират състоянието и не изтриват liveness_scores.
        - Продължителна липса на лице (>=3 кадъра или >=1.8s) коректно преминава в idle 'Няма зачетено лице'.
        """
        room = "TEST_DEBOUNCE_ROOM"
        state = {
            "student_name": "Тестов Студент Нормален",
            "faculty_number": "12128801",
            "status_text": "Проверка на автентичност...",
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
            "last_face_seen_time": time.time(),
            "liveness_scores": [0.95],
            "liveness_student_id": str(self.student.id),
        }

        empty_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        _, empty_bytes = cv2.imencode('.jpg', empty_frame)
        empty_bytes = empty_bytes.tobytes()

        known_encs = [np.array(self.dummy_embedding)]
        known_names = [self.student]

        # 1-ви пропуск: в рамките на grace period (<1.8s, misses < 3)
        res1 = analyze_frame_outside_ui(empty_bytes, room, known_encs, known_names, state)
        self.assertIsNone(res1)
        self.assertEqual(state["consecutive_face_misses"], 1)
        self.assertEqual(state["student_name"], "Тестов Студент Нормален")
        self.assertEqual(state["status_text"], "Проверка на автентичност...")
        self.assertEqual(len(state["liveness_scores"]), 1)
        self.assertEqual(state["liveness_student_id"], str(self.student.id))

        # 2-ри пропуск: все още в рамките на grace period
        res2 = analyze_frame_outside_ui(empty_bytes, room, known_encs, known_names, state)
        self.assertIsNone(res2)
        self.assertEqual(state["consecutive_face_misses"], 2)
        self.assertEqual(state["student_name"], "Тестов Студент Нормален")
        self.assertEqual(len(state["liveness_scores"]), 1)

        # 3-ти пропуск: броячът достига лимита (misses >= 3)
        res3 = analyze_frame_outside_ui(empty_bytes, room, known_encs, known_names, state)
        self.assertIsNone(res3)
        self.assertGreaterEqual(state["consecutive_face_misses"], 3)
        self.assertEqual(state["student_name"], "")
        self.assertEqual(state["status_text"], "Няма зачетено лице пред камерата")
        self.assertEqual(state["status_type"], "idle")
        self.assertEqual(state["liveness_scores"], [])
        self.assertIsNone(state["liveness_student_id"])

    def test_16_yunet_box_padding_applied(self):
        """
        Тества дали detect_face_boxes коректно прилага разширяване на кутията с марджин
        без да надхвърля границите на изображението [0, w] и [0, h].
        """
        with patch("app.stream_esp32._get_yunet_detector") as mock_get_yunet:
            mock_detector = MagicMock()
            mock_detector.detect.return_value = (1, np.array([[50, 60, 100, 120, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.95]]))
            mock_get_yunet.return_value = mock_detector

            dummy_img = np.zeros((480, 640, 3), dtype=np.uint8)
            boxes = detect_face_boxes(dummy_img)
            self.assertEqual(len(boxes), 1)
            top, right, bottom, left = boxes[0]

            # fw=100 -> pad_w = 12, fh=120 -> pad_h = 14
            self.assertEqual(top, 46)
            self.assertEqual(bottom, 194)
            self.assertEqual(left, 38)
            self.assertEqual(right, 162)


if __name__ == "__main__":
    unittest.main()
