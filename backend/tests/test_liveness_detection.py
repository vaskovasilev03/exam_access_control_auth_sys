import io
import os
import unittest
import uuid
import numpy as np
import cv2
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Ensure environment variables
os.environ["SUPERADMIN_EMAIL"] = "superadmin@tu-sofia.bg"
os.environ["SUPERADMIN_PASSWORD"] = "SuperAdmin123!"
os.environ["SUPERADMIN_NAME"] = "Super Administrator"

from app.main import app, verify_selfie_liveness_and_uniqueness
from app.database import SessionLocal, init_db
from app.models import Student
from app.auth import get_password_hash, create_access_token
from app.liveness import LivenessDetector, get_liveness_detector
from tests.test_data_isolation import TestDataSnapshot, clean_known_test_data

client = TestClient(app)

TEST_STUDENT_ID_A = "99900001"
TEST_STUDENT_ID_B = "99900002"
TEST_EMAIL_A = "test.liveness.a@tu-sofia.bg"
TEST_EMAIL_B = "test.liveness.b@tu-sofia.bg"


def _make_dummy_image_bytes(width=200, height=200):
    img = np.ones((height, width, 3), dtype=np.uint8) * 128
    success, encoded = cv2.imencode(".jpg", img)
    return encoded.tobytes() if success else b""


class LivenessDetectorUnitTestCase(unittest.TestCase):
    """Unit tests for the MiniFASNetV2 Anti-Spoofing Detector"""

    def setUp(self):
        self.detector = LivenessDetector(threshold=0.85)

    def test_detector_initialization(self):
        self.assertEqual(self.detector.threshold, 0.85)
        self.assertIsNotNone(self.detector.model)
        self.assertTrue(os.path.exists(self.detector.model_path))

    def test_detector_empty_or_invalid_frame(self):
        # Empty array
        is_real, score = self.detector.check(np.array([]), (10, 10, 50, 50))
        self.assertFalse(is_real)
        self.assertEqual(score, 0.0)

        # None frame
        is_real, score = self.detector.check(None, (10, 10, 50, 50))
        self.assertFalse(is_real)
        self.assertEqual(score, 0.0)

    def test_detector_invalid_bbox(self):
        frame = np.zeros((200, 200, 3), dtype=np.uint8)

        # Zero-width / height box
        is_real, score = self.detector.check(frame, (50, 50, 0, 0))
        self.assertFalse(is_real)
        self.assertEqual(score, 0.0)

        # Negative dimension box
        is_real, score = self.detector.check(frame, (50, 50, -10, 50))
        self.assertFalse(is_real)
        self.assertEqual(score, 0.0)

        # Invalid length
        is_real, score = self.detector.check(frame, (50, 50))
        self.assertFalse(is_real)
        self.assertEqual(score, 0.0)

    def test_detector_synthetic_inference(self):
        frame = np.ones((200, 200, 3), dtype=np.uint8) * 100
        # Box in (top, right, bottom, left) format
        is_real, score = self.detector.check(frame, (30, 150, 150, 30))
        self.assertIsInstance(is_real, bool)
        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_detector_custom_threshold(self):
        # Threshold at 0.0 -> even non-faces should pass
        lenient_detector = LivenessDetector(threshold=0.0)
        frame = np.ones((200, 200, 3), dtype=np.uint8) * 100
        is_real, score = lenient_detector.check(frame, (30, 150, 150, 30))
        self.assertTrue(is_real)

        # Threshold at 1.0 -> should fail
        strict_detector = LivenessDetector(threshold=1.0)
        is_real, score = strict_detector.check(frame, (30, 150, 150, 30))
        self.assertFalse(is_real)

    def test_singleton_accessor(self):
        d1 = get_liveness_detector()
        d2 = get_liveness_detector()
        self.assertIs(d1, d2)


class LivenessAndDuplicateIntegrationTestCase(unittest.TestCase):
    """Integration tests for verification, anti-spoofing and 1:N duplicate detection"""

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
        self.db: Session = SessionLocal()
        clean_known_test_data(self.db)
        self.snapshot = TestDataSnapshot(self.db)

    def tearDown(self):
        try:
            if hasattr(self, "snapshot"):
                self.snapshot.cleanup()
            clean_known_test_data(self.db)
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    def _create_test_student(self, student_id_num, email, status="PENDING", embedding=None):
        student = Student(
            full_name=f"Студент {student_id_num}",
            student_id_number=student_id_num,
            email=email,
            faculty="ФКСТ",
            specialty="КСИ",
            course=3,
            stream=1,
            group=35,
            hashed_password=get_password_hash("Pass1234!"),
            status=status,
            face_embedding=embedding,
            must_change_password=False,
            is_active=True
        )
        self.db.add(student)
        self.db.commit()
        self.db.refresh(student)
        return student

    def test_01_missing_face_bytes(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            verify_selfie_liveness_and_uniqueness(b"", None, self.db)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Липсва съдържание", ctx.exception.detail)

    def test_02_corrupt_face_bytes(self):
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            verify_selfie_liveness_and_uniqueness(b"not_an_image_corrupt_data", None, self.db)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Невалидно изображение", ctx.exception.detail)

    @patch("face_recognition.face_locations", return_value=[])
    def test_03_no_face_detected(self, mock_locations):
        dummy_img = _make_dummy_image_bytes()
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            verify_selfie_liveness_and_uniqueness(dummy_img, None, self.db)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Не е открито лице", ctx.exception.detail)

    @patch("face_recognition.face_locations", return_value=[(10, 50, 50, 10), (60, 100, 100, 60)])
    def test_04_multiple_faces_detected(self, mock_locations):
        dummy_img = _make_dummy_image_bytes()
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            verify_selfie_liveness_and_uniqueness(dummy_img, None, self.db)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("открити няколко лица", ctx.exception.detail)

    @patch("face_recognition.face_locations", return_value=[(20, 80, 80, 20)])
    @patch.object(LivenessDetector, "check", return_value=(False, 0.32))
    def test_05_spoof_attack_rejected(self, mock_check, mock_locations):
        dummy_img = _make_dummy_image_bytes()
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            verify_selfie_liveness_and_uniqueness(dummy_img, None, self.db)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Liveness Failed: 0.32", ctx.exception.detail)

    @patch("face_recognition.face_locations", return_value=[(20, 80, 80, 20)])
    @patch.object(LivenessDetector, "check", return_value=(True, 0.94))
    @patch("face_recognition.face_encodings")
    @patch("app.main.upload_photo_to_cloud", return_value="/access-control-bucket/test_photo.jpg")
    def test_06_genuine_live_face_upload_success(self, mock_upload, mock_encodings, mock_check, mock_locations):
        # Unique face vector
        mock_encodings.return_value = [np.array([0.5] * 128, dtype=np.float32)]

        student = self._create_test_student(TEST_STUDENT_ID_A, TEST_EMAIL_A, status="PENDING")
        token = create_access_token(data={"sub": str(student.id), "role": "student"})

        dummy_img = _make_dummy_image_bytes()
        res = client.post(
            "/students/validate",
            data={"status": "LIVENESS_PASSED"},
            files={"file": ("selfie.jpg", io.BytesIO(dummy_img), "image/jpeg")},
            headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertFalse(data["duplicate_detected"])
        self.assertAlmostEqual(data["liveness_score"], 0.94, places=2)

        self.db.refresh(student)
        self.assertEqual(student.status, "PENDING_APPROVAL")
        self.assertTrue(student.gdpr_consent_given)
        self.assertIsNotNone(student.gdpr_consent_timestamp)
        self.assertIsNone(student.duplicate_flagged_student_id)
        self.assertIsNone(student.duplicate_similarity_distance)

    @patch("face_recognition.face_locations", return_value=[(20, 80, 80, 20)])
    @patch.object(LivenessDetector, "check", return_value=(True, 0.96))
    @patch("face_recognition.face_encodings")
    @patch("app.main.upload_photo_to_cloud", return_value="/access-control-bucket/test_photo.jpg")
    def test_07_duplicate_collision_detected_quarantine(self, mock_upload, mock_encodings, mock_check, mock_locations):
        """
        Student A is already APPROVED with face embedding [0.2] * 128.
        Student B uploads a live photo whose embedding is identical to Student A (distance ~ 0.0 < 0.42).
        Student B must be soft-quarantined to PENDING_DUPLICATE_REVIEW.
        """
        embedding_a = [0.2] * 128
        student_a = self._create_test_student(
            TEST_STUDENT_ID_A, TEST_EMAIL_A, status="APPROVED", embedding=embedding_a
        )

        # Candidate student B produces the exact same face encoding
        mock_encodings.return_value = [np.array(embedding_a, dtype=np.float32)]

        student_b = self._create_test_student(TEST_STUDENT_ID_B, TEST_EMAIL_B, status="PENDING")
        token_b = create_access_token(data={"sub": str(student_b.id), "role": "student"})

        dummy_img = _make_dummy_image_bytes()
        res = client.post(
            "/students/validate",
            data={"status": "LIVENESS_PASSED"},
            files={"file": ("selfie.jpg", io.BytesIO(dummy_img), "image/jpeg")},
            headers={"Authorization": f"Bearer {token_b}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["duplicate_detected"])

        self.db.refresh(student_b)
        self.assertEqual(student_b.status, "PENDING_DUPLICATE_REVIEW")
        self.assertEqual(student_b.duplicate_flagged_student_id, student_a.id)
        self.assertIsNotNone(student_b.duplicate_similarity_distance)
        self.assertLess(student_b.duplicate_similarity_distance, 0.42)

    @patch("face_recognition.face_locations", return_value=[(20, 80, 80, 20)])
    @patch.object(LivenessDetector, "check", return_value=(True, 0.95))
    @patch("face_recognition.face_encodings")
    @patch("app.main.upload_photo_to_cloud")
    def test_08_dual_docs_upload_with_duplicate_collision(self, mock_upload, mock_encodings, mock_check, mock_locations):
        """
        Tests POST /students/upload-verification-docs with duplicate collision.
        """
        mock_upload.side_effect = lambda file_data, object_name, content_type: f"/access-control-bucket/{object_name}"

        embedding_a = [0.3] * 128
        student_a = self._create_test_student(
            TEST_STUDENT_ID_A, TEST_EMAIL_A, status="APPROVED", embedding=embedding_a
        )

        mock_encodings.return_value = [np.array(embedding_a, dtype=np.float32)]

        student_b = self._create_test_student(TEST_STUDENT_ID_B, TEST_EMAIL_B, status="PENDING")
        token_b = create_access_token(data={"sub": str(student_b.id), "role": "student"})

        face_bytes = _make_dummy_image_bytes()
        book_bytes = _make_dummy_image_bytes()

        res = client.post(
            "/students/upload-verification-docs",
            files={
                "face_photo": ("face.jpg", io.BytesIO(face_bytes), "image/jpeg"),
                "student_book_photo": ("book.jpg", io.BytesIO(book_bytes), "image/jpeg"),
            },
            headers={"Authorization": f"Bearer {token_b}"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["duplicate_detected"])

        self.db.refresh(student_b)
        self.assertEqual(student_b.status, "PENDING_DUPLICATE_REVIEW")
        self.assertEqual(student_b.duplicate_flagged_student_id, student_a.id)
        self.assertIsNotNone(student_b.student_book_photo_path)
        self.assertTrue(student_b.gdpr_consent_given)
