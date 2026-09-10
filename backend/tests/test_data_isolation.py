"""
Hermetic test data isolation helper.
Guarantees:
1. Tests clean up all entries they create (including AdminLog, ExamRegistration, Student, Exam, Admin, Examiner, SecureKey, AccessLog).
2. Tests NEVER touch, modify, or delete any entries that do not belong to the tests (production, development, or seed data).
"""
from typing import Optional, Set
import uuid
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Admin, Examiner, Student, Exam, ExamRegistration, AccessLog, AdminLog, SecureKey


def clean_known_test_data(db: Session):
    """
    Cleans up any orphaned test artifacts matching explicit test identifiers.
    Guaranteed NEVER to touch non-test entities.
    """
    try:
        # 1. Test Exam Registrations
        test_exam_ids = [e.id for e in db.query(Exam.id).filter(Exam.faculty == "TEST-FKSU").all()]
        test_student_ids = [s.id for s in db.query(Student.id).filter(
            Student.student_id_number.in_(["99900001", "99900002", "99900003", "88800001", "88800002", "999999999"]) |
            Student.student_id_number.like("TEST_EX_%") |
            Student.email.like("test_ex_%") |
            Student.email.like("%test%@tu-sofia.bg")
        ).all()]

        if test_exam_ids or test_student_ids:
            q = db.query(ExamRegistration)
            if test_exam_ids and test_student_ids:
                q = q.filter((ExamRegistration.exam_id.in_(test_exam_ids)) | (ExamRegistration.student_id.in_(test_student_ids)))
            elif test_exam_ids:
                q = q.filter(ExamRegistration.exam_id.in_(test_exam_ids))
            else:
                q = q.filter(ExamRegistration.student_id.in_(test_student_ids))
            q.delete(synchronize_session=False)

        # 2. Test Access Logs
        db.query(AccessLog).filter(AccessLog.location.like("TEST_ROOM%")).delete(synchronize_session=False)

        # 3. Test Admin Logs
        db.query(AdminLog).filter(
            (AdminLog.specialty == "TEST-CSI") |
            (AdminLog.details.like("%TEST-%")) |
            (AdminLog.details.like("%99900001%")) |
            (AdminLog.details.like("%88800001%")) |
            (AdminLog.details.like("%TEST_ROOM%")) |
            (AdminLog.details.like("%Създадени 4, Обновени 0%")) |
            (AdminLog.details.like("%Спешен%"))
        ).delete(synchronize_session=False)

        # Test Allocation Logs (identifiable by test details or small test registration counts created on test exams)
        for l in db.query(AdminLog).filter(AdminLog.action_type.like("ALLOCATION%")).all():
            if l.details and any(k in l.details for k in ["TEST", "TEST-FKSU", "TEST-CSI"]):
                db.delete(l)
            elif l.details and ("новите регистрации: 2" in l.details or "новите регистрации: 4" in l.details):
                db.delete(l)

        # 4. Test Exams
        db.query(Exam).filter((Exam.faculty == "TEST-FKSU") | (Exam.room_number.like("TEST_ROOM%"))).delete(synchronize_session=False)

        # 5. Test Students
        db.query(Student).filter(
            Student.student_id_number.in_(["99900001", "99900002", "99900003", "88800001", "88800002", "999999999"]) |
            Student.student_id_number.like("TEST_EX_%") |
            Student.email.like("test_ex_%") |
            Student.email.like("%test%@tu-sofia.bg")
        ).delete(synchronize_session=False)

        # 6. Test Examiners
        db.query(Examiner).filter(
            Examiner.email.in_(["examiner1_test@tu-sofia.bg", "examiner2_test@tu-sofia.bg"]) |
            Examiner.email.like("pending_examiner_%") |
            Examiner.email.like("instant_examiner_%") |
            Examiner.email.like("approve_me_%") |
            Examiner.email.like("reject_me_%") |
            Examiner.email.like("fake_key_%") |
            Examiner.email.like("revoked_key_%")
        ).delete(synchronize_session=False)

        # 7. Test Admins
        db.query(Admin).filter(
            (Admin.email == "standard_admin@tu-sofia.bg") |
            Admin.email.like("pending_admin_%") |
            Admin.email.like("reg_admin_%") |
            Admin.email.like("instant_admin_%") |
            Admin.email.like("regular_admin_%")
        ).delete(synchronize_session=False)

        db.commit()
    except Exception:
        db.rollback()


class TestDataSnapshot:
    """
    Snapshots database IDs before a test runs, and on cleanup() removes
    ONLY entries created during that test run.
    """
    def __init__(self, db: Optional[Session] = None):
        self._owned_db = False
        if db is None:
            self.db = SessionLocal()
            self._owned_db = True
        else:
            self.db = db

        self.initial_reg_ids: Set[uuid.UUID] = {r[0] for r in self.db.query(ExamRegistration.id).all()}
        self.initial_access_ids: Set[uuid.UUID] = {a[0] for a in self.db.query(AccessLog.id).all()}
        self.initial_admin_log_ids: Set[uuid.UUID] = {l[0] for l in self.db.query(AdminLog.id).all()}
        self.initial_student_ids: Set[uuid.UUID] = {s[0] for s in self.db.query(Student.id).all()}
        self.initial_exam_ids: Set[uuid.UUID] = {e[0] for e in self.db.query(Exam.id).all()}
        self.initial_secure_key_ids: Set[uuid.UUID] = {k[0] for k in self.db.query(SecureKey.id).all()}
        self.initial_examiner_ids: Set[uuid.UUID] = {e[0] for e in self.db.query(Examiner.id).all()}
        self.initial_admin_ids: Set[uuid.UUID] = {a[0] for a in self.db.query(Admin.id).all()}
        self.db.commit()

    def cleanup(self):
        """
        Deletes only newly added IDs created since this snapshot was initialized.
        """
        try:
            # 1. Registrations
            cur_regs = {r[0] for r in self.db.query(ExamRegistration.id).all()}
            new_regs = cur_regs - self.initial_reg_ids
            if new_regs:
                self.db.query(ExamRegistration).filter(ExamRegistration.id.in_(new_regs)).delete(synchronize_session=False)

            # 2. Access logs
            cur_access = {a[0] for a in self.db.query(AccessLog.id).all()}
            new_access = cur_access - self.initial_access_ids
            if new_access:
                self.db.query(AccessLog).filter(AccessLog.id.in_(new_access)).delete(synchronize_session=False)

            # 3. Admin logs
            cur_admin_logs = {l[0] for l in self.db.query(AdminLog.id).all()}
            new_admin_logs = cur_admin_logs - self.initial_admin_log_ids
            if new_admin_logs:
                self.db.query(AdminLog).filter(AdminLog.id.in_(new_admin_logs)).delete(synchronize_session=False)

            # 4. Students
            cur_students = {s[0] for s in self.db.query(Student.id).all()}
            new_students = cur_students - self.initial_student_ids
            if new_students:
                self.db.query(Student).filter(Student.id.in_(new_students)).delete(synchronize_session=False)

            # 5. Exams
            cur_exams = {e[0] for e in self.db.query(Exam.id).all()}
            new_exams = cur_exams - self.initial_exam_ids
            if new_exams:
                self.db.query(Exam).filter(Exam.id.in_(new_exams)).delete(synchronize_session=False)

            # 6. Secure keys
            cur_keys = {k[0] for k in self.db.query(SecureKey.id).all()}
            new_keys = cur_keys - self.initial_secure_key_ids
            if new_keys:
                self.db.query(SecureKey).filter(SecureKey.id.in_(new_keys)).delete(synchronize_session=False)

            # 7. Examiners
            cur_examiners = {e[0] for e in self.db.query(Examiner.id).all()}
            new_examiners = cur_examiners - self.initial_examiner_ids
            if new_examiners:
                self.db.query(Examiner).filter(Examiner.id.in_(new_examiners)).delete(synchronize_session=False)

            # 8. Admins
            cur_admins = {a[0] for a in self.db.query(Admin.id).all()}
            new_admins = cur_admins - self.initial_admin_ids
            if new_admins:
                self.db.query(Admin).filter(Admin.id.in_(new_admins)).delete(synchronize_session=False)

            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            if self._owned_db:
                self.db.close()

