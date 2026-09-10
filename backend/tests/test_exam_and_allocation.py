import io
import os
import unittest
from unittest.mock import patch
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Ensure environment variables are loaded
os.environ["SUPERADMIN_EMAIL"] = "superadmin@tu-sofia.bg"
os.environ["SUPERADMIN_PASSWORD"] = "SuperAdmin123!"
os.environ["SUPERADMIN_NAME"] = "Super Administrator"

from app.main import app
from app.database import SessionLocal, init_db
from app.models import Admin, Student, Exam, ExamRegistration, AdminLog, SessionType
from app.seed import seed_superadmin

client = TestClient(app)

from tests.test_data_isolation import TestDataSnapshot, clean_known_test_data

class ExamAndAllocationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        cls._cleanup_database()

    @classmethod
    def tearDownClass(cls):
        cls._cleanup_database()

    @classmethod
    def _cleanup_database(cls):
        db: Session = SessionLocal()
        try:
            clean_known_test_data(db)
        finally:
            db.close()

    def setUp(self):
        self.db: Session = SessionLocal()
        clean_known_test_data(self.db)
        self.snapshot = TestDataSnapshot(self.db)
        self.superadmin = seed_superadmin(self.db)
        # Login as superadmin
        login_res = client.post("/login", data={
            "role": "admin",
            "email": "superadmin@tu-sofia.bg",
            "password": "SuperAdmin123!"
        }, follow_redirects=False)
        self.token = login_res.cookies.get("admin_token")
        self.auth_headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        try:
            self.snapshot.cleanup()
            clean_known_test_data(self.db)
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    def _create_mock_exam_excel(self):
        data = {
            "Сесия": ["лятна", "зимна", "поправителна", "ликвидационна"],
            "Дисциплина": ["TEST-Обектно Ориентирано Програмиране", "TEST-Бази Данни", "TEST-Операционни Системи", "TEST-Компютърни Мрежи"],
            "Преподавател": ["доц. Иван Иванов", "проф. Петър Петров", "доц. Георги Георгиев", "гл. ас. Димитър Димитров"],
            "Дата": ["2026-06-15", "2026-01-20", "2026-09-01", "2026-09-15"],
            "Час": ["09:00", "13:30", "10:00", "14:00"],
            "Зала": ["1151", "2201", "3302", "4403"],
            "Факултет": ["TEST-FKSU", "TEST-FKSU", "TEST-FKSU", "TEST-FKSU"],
            "Специалност": ["TEST-CSI", "TEST-CSI", "TEST-CSI", "TEST-CSI"],
            "Курс": [2, 2, 2, 2],
            "Поток": [1, 1, 1, 1],
            "Група": ["99", "99", "99", "99"]
        }
        df = pd.DataFrame(data)
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        excel_buffer.seek(0)
        return excel_buffer

    def _create_test_students(self):
        # Student 1: APPROVED with matching group 99
        st1 = Student(
            full_name="Тестов Студент Едно",
            student_id_number="99900001",
            email="test1.approved@tu-sofia.bg",
            hashed_password="hashed_pass_mock_1",
            faculty="TEST-FKSU",
            specialty="TEST-CSI",
            course=2,
            stream=1,
            group=99,
            status="APPROVED",
            is_active=True
        )
        # Student 2: APPROVED with matching group 99
        st2 = Student(
            full_name="Тестов Студент Две",
            student_id_number="99900002",
            email="test2.approved@tu-sofia.bg",
            hashed_password="hashed_pass_mock_2",
            faculty="TEST-FKSU",
            specialty="TEST-CSI",
            course=2,
            stream=1,
            group=99,
            status="APPROVED",
            is_active=True
        )
        # Student 3: PENDING (not approved, should not be allocated yet)
        st3 = Student(
            full_name="Тестов Студент Три (Чакащ)",
            student_id_number="99900003",
            email="test3.pending@tu-sofia.bg",
            hashed_password="LOCKED_UNTIL_EMAIL_SENT",
            faculty="TEST-FKSU",
            specialty="TEST-CSI",
            course=2,
            stream=1,
            group=99,
            status="PENDING",
            is_active=False
        )
        self.db.add_all([st1, st2, st3])
        self.db.commit()
        return st1, st2, st3

    def test_01_upload_exams_excel_validation_and_session_types(self):
        """ Test uploading exam schedule Excel with session types (лятна, зимна, поправителна, ликвидационна) """
        excel_file = self._create_mock_exam_excel()
        response = client.post(
            "/admins/upload/exams",
            headers=self.auth_headers,
            files={
                "file": ("exam_schedule.xlsx", excel_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["created"], 4)
        self.assertIn("admin_log_id", data)
        self.assertIsNotNone(data["admin_log_id"])

        # Check exams in DB
        exams = self.db.query(Exam).filter(Exam.faculty == "TEST-FKSU").all()
        self.assertEqual(len(exams), 4)

        session_types = {e.session_type for e in exams}
        expected_sessions = {SessionType.SUMMER, SessionType.WINTER, SessionType.RESIT, SessionType.LIQUIDATION}
        self.assertEqual(session_types, expected_sessions)

    def test_02_dashboard_data_includes_exams_and_import_logs(self):
        """ Test that dashboard-data endpoint provides enriched exam import logs and allocation ratios """
        self._create_test_students()
        excel_file = self._create_mock_exam_excel()
        client.post(
            "/admins/upload/exams",
            headers=self.auth_headers,
            files={
                "file": ("exam_schedule.xlsx", excel_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            }
        )

        dash_res = client.get("/admins/dashboard-data", headers=self.auth_headers)
        self.assertEqual(dash_res.status_code, 200)
        data = dash_res.json()

        # Check exams in dashboard-data
        test_exams = [e for e in data.get("exams", []) if e.get("faculty") == "TEST-FKSU"]
        self.assertEqual(len(test_exams), 4)

        for exam_item in test_exams:
            self.assertIn("session_type", exam_item)
            self.assertIn("allocated_count", exam_item)
            self.assertIn("eligible_count", exam_item)
            self.assertIn("approved_count", exam_item)
            self.assertIn("pending_bio_count", exam_item)
            # Group 99 has 3 students total: 2 approved, 1 pending bio
            self.assertEqual(exam_item["eligible_count"], 3)
            self.assertEqual(exam_item["approved_count"], 2)
            self.assertEqual(exam_item["pending_bio_count"], 1)
            self.assertEqual(exam_item["allocated_count"], 0)

    def test_03_execute_student_allocation_single_and_bulk(self):
        """ Test executing smart allocation for single exam and verifying ratio updates and idempotency """
        st1, st2, st3 = self._create_test_students()
        excel_file = self._create_mock_exam_excel()
        client.post(
            "/admins/upload/exams",
            headers=self.auth_headers,
            files={
                "file": ("exam_schedule.xlsx", excel_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            }
        )

        summer_exam = self.db.query(Exam).filter(
            Exam.faculty == "TEST-FKSU",
            Exam.session_type == SessionType.SUMMER
        ).first()
        self.assertIsNotNone(summer_exam)

        # 1. Execute allocation for single exam
        alloc_res = client.post(
            "/admins/execute-allocation",
            headers=self.auth_headers,
            json={"exam_id": str(summer_exam.id)}
        )
        self.assertEqual(alloc_res.status_code, 200)
        alloc_data = alloc_res.json()
        self.assertEqual(alloc_data["new_registrations_created"], 2)
        self.assertIn("admin_log_id", alloc_data)

        # Check registrations in DB: only approved students (st1, st2) are registered
        regs = self.db.query(ExamRegistration).filter(ExamRegistration.exam_id == summer_exam.id).all()
        self.assertEqual(len(regs), 2)
        registered_student_ids = {str(r.student_id) for r in regs}
        self.assertEqual(registered_student_ids, {str(st1.id), str(st2.id)})

        # 2. Idempotency test: executing again must yield 0 new registrations
        alloc_res_2 = client.post(
            "/admins/execute-allocation",
            headers=self.auth_headers,
            json={"exam_id": str(summer_exam.id)}
        )
        self.assertEqual(alloc_res_2.status_code, 200)
        self.assertEqual(alloc_res_2.json()["new_registrations_created"], 0)

        # 3. Bulk allocation for all regular sessions
        bulk_res = client.post(
            "/admins/execute-allocation",
            headers=self.auth_headers,
            json={}
        )
        self.assertEqual(bulk_res.status_code, 200)
        # Winter exam will now allocate the 2 approved students (+2 registrations)
        self.assertEqual(bulk_res.json()["new_registrations_created"], 2)

    @patch("app.main.send_allocation_email", return_value=True)
    def test_04_send_allocation_notification_emails(self, mock_send_email):
        """ Test sending exam allocation email notifications to allocated students """
        self._create_test_students()
        excel_file = self._create_mock_exam_excel()
        client.post(
            "/admins/upload/exams",
            headers=self.auth_headers,
            files={
                "file": ("exam_schedule.xlsx", excel_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            }
        )

        summer_exam = self.db.query(Exam).filter(
            Exam.faculty == "TEST-FKSU",
            Exam.session_type == SessionType.SUMMER
        ).first()

        alloc_res = client.post(
            "/admins/execute-allocation",
            headers=self.auth_headers,
            json={"exam_id": str(summer_exam.id)}
        )
        log_id = alloc_res.json()["admin_log_id"]

        # Send notifications
        notify_res = client.post(
            f"/admins/notifications/send/{log_id}",
            headers=self.auth_headers,
            json={}
        )
        self.assertEqual(notify_res.status_code, 200)

        self.db.expire_all()
        log = self.db.query(AdminLog).filter(AdminLog.id == log_id).first()
        self.assertTrue(log.notification_sent)
        self.assertEqual(mock_send_email.call_count, 2)

    def test_05_execute_student_allocation_chunked_exam_ids(self):
        """ Test executing smart allocation with chunked exam_ids list """
        self._create_test_students()
        excel_file = self._create_mock_exam_excel()
        client.post(
            "/admins/upload/exams",
            headers=self.auth_headers,
            files={
                "file": ("exam_schedule.xlsx", excel_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            }
        )

        test_exams = self.db.query(Exam).filter(Exam.faculty == "TEST-FKSU").all()
        exam_ids = [str(e.id) for e in test_exams[:2]]

        chunk_res = client.post(
            "/admins/execute-allocation",
            headers=self.auth_headers,
            json={"exam_ids": exam_ids}
        )
        self.assertEqual(chunk_res.status_code, 200)
        data = chunk_res.json()
        self.assertIn("new_registrations_created", data)
        self.assertIn("admin_log_id", data)
        self.assertGreater(data["new_registrations_created"], 0)

    def test_06_allocation_preview_and_noop_handling(self):
        """ Test previewing allocation before execution and avoiding empty admin logs """
        self._create_test_students()
        excel_file = self._create_mock_exam_excel()
        client.post(
            "/admins/upload/exams",
            headers=self.auth_headers,
            files={
                "file": ("exam_schedule.xlsx", excel_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            }
        )

        # 1. Check preview before any allocation
        preview_res = client.get(
            "/admins/allocation-preview",
            headers=self.auth_headers
        )
        self.assertEqual(preview_res.status_code, 200)
        preview_data = preview_res.json()
        self.assertEqual(preview_data["status"], "success")
        self.assertTrue(preview_data["can_allocate"])
        self.assertEqual(preview_data["ready_registrations_count"], 4)
        self.assertEqual(preview_data["unique_students_count"], 2)
        self.assertGreaterEqual(preview_data["skipped_pending_bio_count"], 1)
        self.assertGreaterEqual(len(preview_data["preview_items"]), 1)

        # 2. Check preview for single exam
        summer_exam = self.db.query(Exam).filter(
            Exam.faculty == "TEST-FKSU",
            Exam.session_type == SessionType.SUMMER
        ).first()
        single_preview = client.get(
            f"/admins/allocation-preview?exam_id={summer_exam.id}",
            headers=self.auth_headers
        )
        self.assertEqual(single_preview.status_code, 200)
        single_data = single_preview.json()
        self.assertEqual(single_data["ready_registrations_count"], 2)
        self.assertEqual(single_data["unique_students_count"], 2)
        self.assertEqual(single_data["skipped_pending_bio_count"], 1)

        # 3. Execute allocation
        exec_res = client.post(
            "/admins/execute-allocation",
            headers=self.auth_headers,
            json={}
        )
        self.assertEqual(exec_res.status_code, 200)
        self.assertEqual(exec_res.json()["new_registrations_created"], 4)

        # Count logs in DB
        initial_log_count = self.db.query(AdminLog).filter(
            AdminLog.action_type.in_(["ALLOCATION_EXECUTION", "ALLOCATION_EXECUTION_NO_NEW"])
        ).count()

        # 4. Preview after all approved students are allocated
        post_preview = client.get(
            f"/admins/allocation-preview?exam_id={summer_exam.id}",
            headers=self.auth_headers
        )
        self.assertEqual(post_preview.status_code, 200)
        post_data = post_preview.json()
        self.assertEqual(post_data["ready_registrations_count"], 0)
        self.assertFalse(post_data["can_allocate"])
        self.assertEqual(post_data["skipped_pending_bio_count"], 1)

        # 5. Executing allocation again should return noop and NOT create an AdminLog
        noop_res = client.post(
            "/admins/execute-allocation",
            headers=self.auth_headers,
            json={}
        )
        self.assertEqual(noop_res.status_code, 200)
        noop_data = noop_res.json()
        self.assertEqual(noop_data["status"], "noop")
        self.assertEqual(noop_data["new_registrations_created"], 0)
        self.assertIsNone(noop_data["admin_log_id"])

        # Check DB log count did not increase
        self.db.expire_all()
        post_log_count = self.db.query(AdminLog).filter(
            AdminLog.action_type.in_(["ALLOCATION_EXECUTION", "ALLOCATION_EXECUTION_NO_NEW"])
        ).count()
        self.assertEqual(post_log_count, initial_log_count)

if __name__ == "__main__":
    unittest.main()


