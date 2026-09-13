import os
import unittest
import uuid
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ["SUPERADMIN_EMAIL"] = "superadmin@tu-sofia.bg"
os.environ["SUPERADMIN_PASSWORD"] = "SuperAdmin123!"
os.environ["SUPERADMIN_NAME"] = "Super Administrator"

from app.main import app, ACTIVE_EXAMINER_ASSIGNMENTS
from app.database import get_db, SessionLocal, init_db
from app.models import Admin, Student, Examiner, Exam, ExamRegistration, AccessLog, SessionType
from app.seed import seed_superadmin
from app.auth import get_password_hash, create_access_token

from tests.test_data_isolation import TestDataSnapshot, clean_known_test_data

class ExaminerMonitoringTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        db = SessionLocal()
        try:
            ACTIVE_EXAMINER_ASSIGNMENTS.clear()
            clean_known_test_data(db)
        finally:
            db.close()

    @classmethod
    def tearDownClass(cls):
        db = SessionLocal()
        try:
            ACTIVE_EXAMINER_ASSIGNMENTS.clear()
            clean_known_test_data(db)
        finally:
            db.close()

    def setUp(self):
        self.client = TestClient(app)
        self.client.cookies.clear()
        self.db: Session = SessionLocal()
        ACTIVE_EXAMINER_ASSIGNMENTS.clear()
        clean_known_test_data(self.db)
        self.snapshot = TestDataSnapshot(self.db)
        seed_superadmin(self.db)

        # Create Examiner 1
        self.examiner1 = self.db.query(Examiner).filter(Examiner.email == "examiner1_test@tu-sofia.bg").first()
        if not self.examiner1:
            self.examiner1 = Examiner(
                full_name="Квестор Тест 1",
                email="examiner1_test@tu-sofia.bg",
                hashed_password=get_password_hash("ExaminerPass123!"),
                is_verified=True
            )
            self.db.add(self.examiner1)

        # Create Examiner 2
        self.examiner2 = self.db.query(Examiner).filter(Examiner.email == "examiner2_test@tu-sofia.bg").first()
        if not self.examiner2:
            self.examiner2 = Examiner(
                full_name="Квестор Тест 2",
                email="examiner2_test@tu-sofia.bg",
                hashed_password=get_password_hash("ExaminerPass123!"),
                is_verified=True
            )
            self.db.add(self.examiner2)

        self.db.commit()
        self.db.refresh(self.examiner1)
        self.db.refresh(self.examiner2)

        self.token_ex1 = create_access_token({"sub": str(self.examiner1.id), "role": "examiner", "is_superadmin": False})
        self.token_ex2 = create_access_token({"sub": str(self.examiner2.id), "role": "examiner", "is_superadmin": False})

    def tearDown(self):
        try:
            ACTIVE_EXAMINER_ASSIGNMENTS.clear()
            self.snapshot.cleanup()
            clean_known_test_data(self.db)
        finally:
            self.db.close()

    def test_01_examiner_login_without_room(self):
        """ Verify examiner logs in with email and password alone without requiring room number """
        res = self.client.post(
            "/login",
            data={
                "email": "examiner1_test@tu-sofia.bg",
                "password": "ExaminerPass123!",
                "role": "examiner"
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["role"], "examiner")
        self.assertEqual(data["full_name"], "Квестор Тест 1")
        # Check examiner_token cookie was set
        self.assertIn("examiner_token", res.cookies)

    def test_02_examiner_lobby_and_rooms_overview(self):
        """ Verify GET /examiner/lobby HTML and GET /api/v1/examiner/rooms-overview """
        # Test Lobby HTML Page
        lobby_res = self.client.get("/examiner/lobby")
        self.assertEqual(lobby_res.status_code, 200)
        self.assertIn("text/html", lobby_res.headers.get("content-type", ""))

        # Setup test exam in room TEST_ROOM_1
        now = datetime.now()
        exam = Exam(
            subject="Тестов Изпит 1",
            lecturer="проф. Тестов",
            date_time=now + timedelta(hours=2),
            room_number="TEST_ROOM_1",
            session_type=SessionType.SUMMER,
            faculty="ФКСУ",
            specialty="КСИ",
            course=3,
            stream="1",
            group="1"
        )
        self.db.add(exam)
        self.db.commit()

        # Overview query
        res = self.client.get(
            "/api/v1/examiner/rooms-overview",
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("rooms", data)
        self.assertIn("metrics", data)
        
        target_room = next((r for r in data["rooms"] if r["room_number"] == "TEST_ROOM_1"), None)
        self.assertIsNotNone(target_room)
        self.assertEqual(target_room["subject"], "Тестов Изпит 1")
        self.assertFalse(target_room["is_occupied"])
        self.assertTrue(target_room["can_claim"])

    def test_03_room_claim_and_single_examiner_lock(self):
        """ Test 1-Examiner Exclusive Locking and 409 Conflict rejection """
        # Examiner 1 claims TEST_ROOM_1
        res_claim1 = self.client.post(
            "/api/v1/examiner/rooms/TEST_ROOM_1/claim",
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )
        self.assertEqual(res_claim1.status_code, 200)
        self.assertEqual(res_claim1.json()["status"], "claimed")
        self.assertEqual(res_claim1.json()["examiner_name"], "Квестор Тест 1")

        # Examiner 2 attempts to claim TEST_ROOM_1 -> 409 Conflict
        res_claim2 = self.client.post(
            "/api/v1/examiner/rooms/TEST_ROOM_1/claim",
            headers={"Authorization": f"Bearer {self.token_ex2}"}
        )
        self.assertEqual(res_claim2.status_code, 409)
        self.assertIn("Залата вече се наблюдава от квестор", res_claim2.json()["detail"])

        # Examiner 1 sends heartbeat -> 200 alive
        res_hb = self.client.post(
            "/api/v1/examiner/rooms/TEST_ROOM_1/heartbeat",
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )
        self.assertEqual(res_hb.status_code, 200)
        self.assertEqual(res_hb.json()["status"], "alive")

    def test_04_room_release_and_reclaim(self):
        """ Test releasing room assignment and allowing another examiner to claim it """
        # Claim with Examiner 1
        self.client.post(
            "/api/v1/examiner/rooms/TEST_ROOM_1/claim",
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )

        # Release with Examiner 1
        res_rel = self.client.post(
            "/api/v1/examiner/rooms/TEST_ROOM_1/release",
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )
        self.assertEqual(res_rel.status_code, 200)
        self.assertEqual(res_rel.json()["status"], "released")

        # Now Examiner 2 can claim it
        res_claim2 = self.client.post(
            "/api/v1/examiner/rooms/TEST_ROOM_1/claim",
            headers={"Authorization": f"Bearer {self.token_ex2}"}
        )
        self.assertEqual(res_claim2.status_code, 200)
        self.assertEqual(res_claim2.json()["status"], "claimed")
        self.assertEqual(res_claim2.json()["examiner_name"], "Квестор Тест 2")

    def test_05_room_switching_auto_releases_previous(self):
        """ When an examiner claims Room B, their previous Room A is automatically released """
        # Examiner 1 claims TEST_ROOM_1
        self.client.post(
            "/api/v1/examiner/rooms/TEST_ROOM_1/claim",
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )
        self.assertIn("TEST_ROOM_1", ACTIVE_EXAMINER_ASSIGNMENTS)

        # Examiner 1 claims TEST_ROOM_2
        self.client.post(
            "/api/v1/examiner/rooms/TEST_ROOM_2/claim",
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )
        self.assertIn("TEST_ROOM_2", ACTIVE_EXAMINER_ASSIGNMENTS)
        self.assertNotIn("TEST_ROOM_1", ACTIVE_EXAMINER_ASSIGNMENTS)

        # TEST_ROOM_1 is now free for Examiner 2
        res = self.client.post(
            "/api/v1/examiner/rooms/TEST_ROOM_1/claim",
            headers={"Authorization": f"Bearer {self.token_ex2}"}
        )
        self.assertEqual(res.status_code, 200)

    def test_06_permitted_students_roster_and_color_states(self):
        """ Test /roster endpoint verifying Gray, Green, and Red color states """
        exam = Exam(
            subject="Мрежова сигурност",
            lecturer="доц. Петров",
            date_time=datetime.now(),
            room_number="TEST_ROOM_3",
            session_type=SessionType.SUMMER,
            faculty="ФКСУ",
            specialty="КСИ",
            course=4,
            stream="1",
            group="1"
        )
        self.db.add(exam)

        # 1. Student A: Approved + Face Embedding -> Waiting (Gray)
        st_a = Student(
            full_name="Студент Сив Чакащ",
            student_id_number="TEST_EX_01",
            email="test_ex_01@tu-sofia.bg",
            hashed_password=get_password_hash("StudentPass123!"),
            faculty="ФКСУ",
            specialty="КСИ",
            course=4,
            stream="1",
            group="1",
            status="APPROVED",
            face_embedding=[0.1] * 128
        )
        # 2. Student B: Pending / Incomplete Biometrics -> Unpermitted (Red)
        st_b = Student(
            full_name="Студент Червен Проблем",
            student_id_number="TEST_EX_02",
            email="test_ex_02@tu-sofia.bg",
            hashed_password=get_password_hash("StudentPass123!"),
            faculty="ФКСУ",
            specialty="КСИ",
            course=4,
            stream="1",
            group="1",
            status="PENDING",
            face_embedding=None
        )
        # 3. Student C: Approved + Face Embedding + Admitted -> Admitted (Green)
        st_c = Student(
            full_name="Студент Зелен Допуснат",
            student_id_number="TEST_EX_03",
            email="test_ex_03@tu-sofia.bg",
            hashed_password=get_password_hash("StudentPass123!"),
            faculty="ФКСУ",
            specialty="КСИ",
            course=4,
            stream="1",
            group="1",
            status="APPROVED",
            face_embedding=[0.2] * 128
        )

        self.db.add_all([st_a, st_b, st_c])
        self.db.commit()

        # Registrations
        reg_a = ExamRegistration(student_id=st_a.id, exam_id=exam.id, is_admitted=False)
        reg_b = ExamRegistration(student_id=st_b.id, exam_id=exam.id, is_admitted=False)
        reg_c = ExamRegistration(student_id=st_c.id, exam_id=exam.id, is_admitted=True, admitted_at=datetime.now())

        self.db.add_all([reg_a, reg_b, reg_c])
        self.db.commit()

        # Query Roster
        res = self.client.get(
            "/api/v1/exams/TEST_ROOM_3/roster",
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()

        metrics = data["metrics"]
        self.assertEqual(metrics["total_expected"], 3)
        self.assertEqual(metrics["total_admitted"], 1)
        self.assertEqual(metrics["total_waiting"], 1)
        self.assertEqual(metrics["total_unpermitted"], 1)
        self.assertEqual(metrics["admission_ratio_pct"], 33.3)

        students_map = {s["faculty_number"]: s for s in data["students"]}
        self.assertEqual(students_map["TEST_EX_01"]["color_state"], "gray")
        self.assertEqual(students_map["TEST_EX_02"]["color_state"], "red")
        self.assertEqual(students_map["TEST_EX_03"]["color_state"], "green")

    def test_07_admit_student_manual(self):
        """ Test manual student admission via /admit/{student_id} """
        exam = Exam(
            subject="Алгоритми",
            lecturer="доц. Георгиев",
            date_time=datetime.now(),
            room_number="TEST_ROOM_1",
            session_type=SessionType.SUMMER,
            faculty="ФКСУ",
            specialty="КСИ",
            course=2,
            stream="1",
            group="1"
        )
        st = Student(
            full_name="Студент За Допускане",
            student_id_number="TEST_EX_04",
            email="test_ex_04@tu-sofia.bg",
            hashed_password=get_password_hash("StudentPass123!"),
            faculty="ФКСУ",
            specialty="КСИ",
            course=2,
            stream="1",
            group="1",
            status="APPROVED",
            face_embedding=[0.3] * 128
        )
        self.db.add_all([exam, st])
        self.db.commit()

        reg = ExamRegistration(student_id=st.id, exam_id=exam.id, is_admitted=False)
        self.db.add(reg)
        self.db.commit()

        # Admit manually
        res = self.client.post(
            f"/api/v1/exams/TEST_ROOM_1/admit/{st.id}",
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "admitted")

        # Verify DB state
        self.db.refresh(reg)
        self.assertTrue(reg.is_admitted)
        self.assertIsNotNone(reg.admitted_at)

        # Verify AccessLog
        log = self.db.query(AccessLog).filter(AccessLog.student_id == st.id, AccessLog.location == "TEST_ROOM_1").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.status, "GRANTED")

    def test_08_force_register_sets_admitted(self):
        """ Test emergency /force-register sets is_admitted=True and logs AccessLog """
        exam = Exam(
            subject="Софтуерно инженерство",
            lecturer="доц. Стоянов",
            date_time=datetime.now(),
            room_number="TEST_ROOM_2",
            session_type=SessionType.SUMMER,
            faculty="ФКСУ",
            specialty="КСИ",
            course=3,
            stream="1",
            group="1"
        )
        st = Student(
            full_name="Студент Спешен",
            student_id_number="TEST_EX_05",
            email="test_ex_05@tu-sofia.bg",
            hashed_password=get_password_hash("StudentPass123!"),
            faculty="ФКСУ",
            specialty="КСИ",
            course=3,
            stream="1",
            group="1",
            status="APPROVED",
            face_embedding=[0.4] * 128
        )
        self.db.add_all([exam, st])
        self.db.commit()

        res = self.client.post(
            "/api/v1/exams/TEST_ROOM_2/force-register",
            data={"student_id_number": "TEST_EX_05"},
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")

        # Verify registration in DB
        reg = self.db.query(ExamRegistration).filter(ExamRegistration.student_id == st.id, ExamRegistration.exam_id == exam.id).first()
        self.assertIsNotNone(reg)
        self.assertTrue(reg.is_admitted)
        self.assertIsNotNone(reg.admitted_at)

    def test_09_examiner_monitoring_unauthorized_access(self):
        """ Verify unauthenticated users and students are denied access """
        # No token -> 401
        res1 = self.client.get("/api/v1/examiner/rooms-overview")
        self.assertEqual(res1.status_code, 401)

        # Student token -> 403
        student_token = create_access_token({"sub": str(uuid.uuid4()), "role": "student"})
        res2 = self.client.get(
            "/api/v1/examiner/rooms-overview",
            headers={"Authorization": f"Bearer {student_token}"}
        )
        self.assertEqual(res2.status_code, 403)

    def test_10_camera_source_toggle_and_webcam_ingest(self):
        """ Verify toggling camera source between ESP32 and local webcam and uploading webcam frames """
        import io
        from PIL import Image

        # 1. Examiner switches to local webcam
        res = self.client.post(
            "/api/v1/exams/ROOM_WEBCAM_TEST/camera-source",
            json={"source": "webcam"},
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["success"])
        self.assertEqual(res.json()["source"], "webcam")

        # 2. Verify source via GET
        res_get = self.client.get("/api/v1/exams/ROOM_WEBCAM_TEST/camera-source")
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json()["source"], "webcam")

        # 3. Create dummy JPEG frame
        img = Image.new("RGB", (320, 240), color=(100, 150, 200))
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        frame_bytes = buf.getvalue()

        # 4. Upload webcam frame
        res_frame = self.client.post(
            "/api/v1/exams/ROOM_WEBCAM_TEST/webcam-frame",
            content=frame_bytes,
            headers={
                "Content-Type": "image/jpeg",
                "Authorization": f"Bearer {self.token_ex1}"
            }
        )
        self.assertEqual(res_frame.status_code, 200)
        self.assertTrue(res_frame.json()["success"])
        self.assertEqual(res_frame.json()["source"], "webcam")

        # 5. Check camera status reflects webcam is armed/online
        res_status = self.client.get("/api/v1/exams/ROOM_WEBCAM_TEST/camera-status")
        self.assertEqual(res_status.status_code, 200)
        status_data = res_status.json()
        self.assertTrue(status_data["armed"])
        self.assertTrue(status_data["is_online"])
        self.assertEqual(status_data["source"], "webcam")

        # 6. Switch back to ESP32
        res_esp = self.client.post(
            "/api/v1/exams/ROOM_WEBCAM_TEST/camera-source",
            json={"source": "esp32"},
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )
        self.assertEqual(res_esp.status_code, 200)
        self.assertEqual(res_esp.json()["source"], "esp32")

    def test_11_camera_source_authorization_and_validation(self):
        """ Verify unauthorized requests and invalid source values are rejected """
        # No token -> 401
        res1 = self.client.post("/api/v1/exams/ROOM_TEST/camera-source", json={"source": "webcam"})
        self.assertEqual(res1.status_code, 401)

        # Student token -> 403
        student_token = create_access_token({"sub": str(uuid.uuid4()), "role": "student"})
        res2 = self.client.post(
            "/api/v1/exams/ROOM_TEST/camera-source",
            json={"source": "webcam"},
            headers={"Authorization": f"Bearer {student_token}"}
        )
        self.assertEqual(res2.status_code, 403)

        # Invalid source value -> 400
        res3 = self.client.post(
            "/api/v1/exams/ROOM_TEST/camera-source",
            json={"source": "invalid_source"},
            headers={"Authorization": f"Bearer {self.token_ex1}"}
        )
        self.assertEqual(res3.status_code, 400)

if __name__ == "__main__":
    unittest.main()
