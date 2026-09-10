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
from app.models import Admin, Student, AdminLog
from app.seed import seed_superadmin

client = TestClient(app)

class StudentManagementTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    @classmethod
    def tearDownClass(cls):
        db: Session = SessionLocal()
        try:
            db.query(Student).filter(Student.student_id_number.in_(["88800001", "88800002"])).delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def setUp(self):
        self.db: Session = SessionLocal()
        self.superadmin = seed_superadmin(self.db)
        # Login as superadmin to get token
        login_res = client.post("/login", data={
            "role": "admin",
            "email": "superadmin@tu-sofia.bg",
            "password": "SuperAdmin123!"
        }, follow_redirects=False)
        self.token = login_res.cookies.get("admin_token")
        self.auth_headers = {"Authorization": f"Bearer {self.token}"}

    def tearDown(self):
        try:
            self.db.query(Student).filter(Student.student_id_number.in_(["88800001", "88800002"])).delete(synchronize_session=False)
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    def _create_mock_excel(self):
        data = {
            "Име": ["Георги", "Мария"],
            "Фамилия": ["Иванов", "Петрова"],
            "Фак. Номер": ["88800001", "88800002"],
            "Имейл": ["georgi.test@tu-sofia.bg", "maria.test@tu-sofia.bg"]
        }
        df = pd.DataFrame(data)
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        excel_buffer.seek(0)
        return excel_buffer

    def test_01_upload_students_excel_and_is_active_flag(self):
        """ Test that excel student upload initializes is_active=False and LOCKED_UNTIL_EMAIL_SENT """
        excel_file = self._create_mock_excel()
        response = client.post(
            "/admins/upload/students",
            headers=self.auth_headers,
            data={
                "faculty": "TEST-FKSU",
                "specialty": "TEST-CSI",
                "course": 2,
                "stream": 1,
                "group": 99,
            },
            files={
                "file": ("students.xlsx", excel_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            }
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("Успешно импортирани 2 студенти", data["message"])
        self.assertIn("admin_log_id", data)

        # Check students in database
        st1 = self.db.query(Student).filter(Student.student_id_number == "88800001").first()
        self.assertIsNotNone(st1)
        self.assertFalse(st1.is_active, "Imported student must have is_active=False initially")
        self.assertEqual(st1.status, "PENDING")
        self.assertEqual(st1.hashed_password, "LOCKED_UNTIL_EMAIL_SENT")

    def test_02_dashboard_data_reflects_student_status(self):
        """ Test that dashboard-data exposes is_active and email_sent accurately in student payload """
        excel_file = self._create_mock_excel()
        upload_res = client.post(
            "/admins/upload/students",
            headers=self.auth_headers,
            data={
                "faculty": "TEST-FKSU",
                "specialty": "TEST-CSI",
                "course": 2,
                "stream": 1,
                "group": 99,
            },
            files={
                "file": ("students.xlsx", excel_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            }
        )
        self.assertEqual(upload_res.status_code, 200)
        upload_log_id = upload_res.json()["admin_log_id"]

        dash_res = client.get("/admins/dashboard-data", headers=self.auth_headers)
        self.assertEqual(dash_res.status_code, 200)
        dash_data = dash_res.json()
        
        test_log = next((l for l in dash_data.get("student_import_logs", []) if str(l.get("id")) == str(upload_log_id)), None)
        self.assertIsNotNone(test_log)
        self.assertEqual(len(test_log["students"]), 2)
        for s in test_log["students"]:
            self.assertFalse(s["is_active"])
            self.assertFalse(s["email_sent"])

    @patch("app.main.send_welcome_email", return_value=True)
    def test_03_send_bulk_student_emails_activates_students(self, mock_email):
        """ Test that sending welcome email sets is_active=True and marks log notification_sent """
        excel_file = self._create_mock_excel()
        upload_res = client.post(
            "/admins/upload/students",
            headers=self.auth_headers,
            data={
                "faculty": "TEST-FKSU",
                "specialty": "TEST-CSI",
                "course": 2,
                "stream": 1,
                "group": 99,
            },
            files={
                "file": ("students.xlsx", excel_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            }
        )
        log_id = upload_res.json()["admin_log_id"]

        st1 = self.db.query(Student).filter(Student.student_id_number == "88800001").first()
        st2 = self.db.query(Student).filter(Student.student_id_number == "88800002").first()

        # Send email only to student 1
        send_res = client.post(
            f"/admins/notifications/send/{log_id}",
            headers=self.auth_headers,
            json={"student_ids": [str(st1.id)]}
        )
        self.assertEqual(send_res.status_code, 200)
        self.assertEqual(send_res.json()["sent_count"], 1)

        self.db.expire_all()
        st1_updated = self.db.query(Student).filter(Student.id == st1.id).first()
        st2_updated = self.db.query(Student).filter(Student.id == st2.id).first()
        self.assertTrue(st1_updated.is_active, "Student 1 must now be is_active=True")
        self.assertFalse(st2_updated.is_active, "Student 2 must remain is_active=False")

        # Now send to student 2
        send_res2 = client.post(
            f"/admins/notifications/send/{log_id}",
            headers=self.auth_headers,
            json={"student_ids": [str(st2.id)]}
        )
        self.assertEqual(send_res2.status_code, 200)

        self.db.expire_all()
        log_updated = self.db.query(AdminLog).filter(AdminLog.id == log_id).first()
        self.assertTrue(log_updated.notification_sent, "When all students in log are active, notification_sent must be True")

if __name__ == "__main__":
    unittest.main()

