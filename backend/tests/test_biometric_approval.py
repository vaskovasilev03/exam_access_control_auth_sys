import io
import os
import unittest
from unittest.mock import patch
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
from app.auth import get_password_hash, create_access_token

client = TestClient(app)

TEST_STUDENT_ID_NUM = "99900001"
TEST_STUDENT_EMAIL = "test.biometric@tu-sofia.bg"


from tests.test_data_isolation import TestDataSnapshot, clean_known_test_data

class BiometricApprovalTestCase(unittest.TestCase):
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

        # Login as superadmin to get token
        login_res = client.post("/login", data={
            "role": "admin",
            "email": "superadmin@tu-sofia.bg",
            "password": "SuperAdmin123!"
        }, follow_redirects=False)
        self.admin_token = login_res.cookies.get("admin_token")
        self.auth_headers = {"Authorization": f"Bearer {self.admin_token}"}

    def tearDown(self):
        self._cleanup_test_records()
        self.db.close()

    def _cleanup_test_records(self):
        try:
            if hasattr(self, "snapshot"):
                self.snapshot.cleanup()
            clean_known_test_data(self.db)
        except Exception:
            self.db.rollback()

    def _create_test_student(self, status="PENDING_APPROVAL", photo_path="/test-bucket/face.jpg", book_path="/test-bucket/book.jpg"):
        student = Student(
            full_name="Тест Биометричен Студент",
            student_id_number=TEST_STUDENT_ID_NUM,
            email=TEST_STUDENT_EMAIL,
            faculty="ФКСТ",
            specialty="КСИ",
            course=3,
            stream=1,
            group=35,
            hashed_password=get_password_hash("StudentPass123!"),
            status=status,
            must_change_password=False,
            is_active=True,
            photo_path=photo_path,
            student_book_photo_path=book_path
        )
        self.db.add(student)
        self.db.commit()
        self.db.refresh(student)
        return student

    def test_01_student_book_photo_schema_and_payload(self):
        """Проверка дали student_book_photo_path и student_book_photo_url присъстват в dashboard-data."""
        student = self._create_test_student(
            status="PENDING_APPROVAL",
            photo_path="/access-control-bucket/99900001_face.jpg",
            book_path="/access-control-bucket/99900001_book.jpg"
        )

        res = client.get("/admins/dashboard-data", headers=self.auth_headers, cookies={"admin_token": self.admin_token})
        self.assertEqual(res.status_code, 200)
        data = res.json()

        pending = [s for s in data.get("pending_students", []) if s["student_id_number"] == TEST_STUDENT_ID_NUM]
        self.assertEqual(len(pending), 1)
        st_data = pending[0]

        self.assertEqual(st_data["student_book_photo_path"], "/access-control-bucket/99900001_book.jpg")
        self.assertIn(f"/admins/students/{student.id}/student-book-photo", st_data["student_book_photo_url"])
        self.assertIn(f"/admins/students/{student.id}/photo", st_data["photo_url"])

    @patch("app.main.get_photo_from_cloud")
    def test_02_student_book_photo_stream_endpoint(self, mock_get_photo):
        """Тества ендпоинта GET /admins/students/{student_id}/student-book-photo за права и стрийминг."""
        mock_image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01mock_jpeg_bytes"
        mock_get_photo.return_value = mock_image_bytes

        student = self._create_test_student()

        # 1. Без токен -> 422
        res_no_token = client.get(f"/admins/students/{student.id}/student-book-photo")
        self.assertEqual(res_no_token.status_code, 422)

        # 2. Невалиден токен -> 401
        res_invalid_token = client.get(f"/admins/students/{student.id}/student-book-photo?token=invalid_jwt")
        self.assertEqual(res_invalid_token.status_code, 401)

        # 3. Токен от студент (не-админ) -> 403
        student_token = create_access_token(data={"sub": str(student.id), "role": "student"})
        res_student_token = client.get(f"/admins/students/{student.id}/student-book-photo?token={student_token}")
        self.assertEqual(res_student_token.status_code, 403)

        # 4. Валиден администраторски токен -> 200 OK стрийминг
        res_ok = client.get(f"/admins/students/{student.id}/student-book-photo?token={self.admin_token}")
        self.assertEqual(res_ok.status_code, 200)
        self.assertEqual(res_ok.content, mock_image_bytes)

        # 5. Студент без качена книжка -> 404
        student.student_book_photo_path = None
        self.db.commit()
        res_none = client.get(f"/admins/students/{student.id}/student-book-photo?token={self.admin_token}")
        self.assertEqual(res_none.status_code, 404)

    @patch("app.main.verify_selfie_liveness_and_uniqueness", return_value=(True, 0.98, None, None))
    @patch("app.main.upload_photo_to_cloud")
    def test_03_dual_photo_upload_verification_docs(self, mock_upload, mock_liveness):
        """Тества двуснимковото качване през POST /students/upload-verification-docs."""
        mock_upload.side_effect = lambda file_data, object_name, content_type: f"/access-control-bucket/{object_name}"

        student = self._create_test_student(status="PENDING", photo_path=None, book_path=None)
        student_token = create_access_token(data={"sub": str(student.id), "role": "student"})

        face_file = ("face.jpg", io.BytesIO(b"fake_face_bytes"), "image/jpeg")
        book_file = ("book.jpg", io.BytesIO(b"fake_book_bytes"), "image/jpeg")

        res = client.post(
            "/students/upload-verification-docs",
            files={"face_photo": face_file, "student_book_photo": book_file},
            headers={"Authorization": f"Bearer {student_token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")

        self.db.refresh(student)
        self.assertEqual(student.status, "PENDING_APPROVAL")
        self.assertTrue(student.photo_path.startswith("/access-control-bucket/"))
        self.assertIn("face", student.photo_path)
        self.assertTrue(student.student_book_photo_path.startswith("/access-control-bucket/"))
        self.assertIn("book", student.student_book_photo_path)

    @patch("app.main.verify_selfie_liveness_and_uniqueness", return_value=(True, 0.98, None, None))
    @patch("app.main.upload_photo_to_cloud")
    def test_04_validate_endpoint_backward_compatibility(self, mock_upload, mock_liveness):
        """Тества съвместимостта на /students/validate при подаване на student_book_file."""
        mock_upload.side_effect = lambda file_data, object_name, content_type: f"/access-control-bucket/{object_name}"

        student = self._create_test_student(status="PENDING", photo_path=None, book_path=None)
        student_token = create_access_token(data={"sub": str(student.id), "role": "student"})

        face_file = ("selfie.jpg", io.BytesIO(b"fake_selfie_data"), "image/jpeg")
        book_file = ("book.jpg", io.BytesIO(b"fake_book_data"), "image/jpeg")

        res = client.post(
            "/students/validate",
            data={"status": "LIVENESS_PASSED"},
            files={"file": face_file, "student_book_file": book_file},
            headers={"Authorization": f"Bearer {student_token}"}
        )
        self.assertEqual(res.status_code, 200)

        self.db.refresh(student)
        self.assertEqual(student.status, "PENDING_APPROVAL")
        self.assertIsNotNone(student.photo_path)
        self.assertIsNotNone(student.student_book_photo_path)

    @patch("app.main.get_photo_from_cloud")
    @patch("face_recognition.load_image_file")
    @patch("face_recognition.face_encodings")
    def test_05_approve_pending_student_biometrics(self, mock_encodings, mock_load, mock_get_photo):
        """Тества одобрението на студент, генерирането на 128D вектор и записването в базата."""
        mock_get_photo.return_value = b"fake_image_bytes"
        mock_load.return_value = object()
        mock_vector = [0.05] * 128
        mock_encodings.return_value = [type("MockEncoding", (), {"tolist": lambda self: mock_vector})()]

        student = self._create_test_student(status="PENDING_APPROVAL")

        res = client.post(
            f"/admins/approve-student/{student.id}",
            headers=self.auth_headers,
            cookies={"admin_token": self.admin_token}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")

        self.db.refresh(student)
        self.assertEqual(student.status, "APPROVED")
        self.assertIsNotNone(student.face_embedding)
        self.assertEqual(len(student.face_embedding), 128)

        log = self.db.query(AdminLog).filter(
            AdminLog.action_type == "STUDENT_APPROVE",
            AdminLog.details.like(f"%{TEST_STUDENT_ID_NUM}%")
        ).order_by(AdminLog.created_at.desc()).first()
        self.assertIsNotNone(log)

    def test_06_reject_pending_student_with_reason(self):
        """Тества отхвърлянето на студент, валидацията за причина и извличането в студентския профил."""
        student = self._create_test_student(status="PENDING_APPROVAL")

        # 1. Липсваща причина -> 400
        res_empty = client.post(
            f"/admins/reject-student/{student.id}",
            json={"reason": "  "},
            headers=self.auth_headers,
            cookies={"admin_token": self.admin_token}
        )
        self.assertEqual(res_empty.status_code, 400)

        # 2. Валидна причина за отхвърляне
        rejection_reason = "Нечетлив печат на деканата в студентската книжка."
        res_reject = client.post(
            f"/admins/reject-student/{student.id}",
            json={"reason": rejection_reason},
            headers=self.auth_headers,
            cookies={"admin_token": self.admin_token}
        )
        self.assertEqual(res_reject.status_code, 200)

        self.db.refresh(student)
        self.assertEqual(student.status, "REJECTED")
        self.assertIsNone(student.face_embedding)

        # 3. Проверка дали студентът вижда причината за отхвърляне в /students/profile
        student_token = create_access_token(data={"sub": str(student.id), "role": "student"})
        res_prof = client.get("/students/profile", headers={"Authorization": f"Bearer {student_token}"})
        self.assertEqual(res_prof.status_code, 200)
        prof_data = res_prof.json()
        self.assertEqual(prof_data["status"], "REJECTED")
        self.assertEqual(prof_data["rejection_reason"], rejection_reason)


if __name__ == "__main__":
    unittest.main()
