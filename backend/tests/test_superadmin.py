import os
import unittest
import uuid
import jwt
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Ensure environment variables are loaded
os.environ["SUPERADMIN_EMAIL"] = "superadmin@tu-sofia.bg"
os.environ["SUPERADMIN_PASSWORD"] = "SuperAdmin123!"
os.environ["SUPERADMIN_NAME"] = "Super Administrator"

from app.main import app
from app.database import get_db, SessionLocal, init_db
from app.models import Admin, Student, Examiner, Exam, SessionType, SecureKey
from app.seed import seed_superadmin
from app.auth import get_password_hash, SECRET_KEY, ALGORITHM

client = TestClient(app)

from tests.test_data_isolation import TestDataSnapshot, clean_known_test_data

class SuperadminVersatilityTestCase(unittest.TestCase):
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
        # Ensure database is seeded with the superadmin
        self.superadmin = seed_superadmin(self.db)

    def tearDown(self):
        try:
            self.snapshot.cleanup()
            clean_known_test_data(self.db)
            # Ensure superadmin password is reset to default SuperAdmin123!
            superadmin = self.db.query(Admin).filter(Admin.is_superadmin == True).first()
            if superadmin:
                superadmin.hashed_password = get_password_hash("SuperAdmin123!")
            self.db.commit()
        except Exception:
            self.db.rollback()
        finally:
            self.db.close()

    def test_01_seed_superadmin_creates_or_updates(self):
        """ Test that seed_superadmin creates exactly 1 superadmin and is idempotent """
        superadmins = self.db.query(Admin).filter(Admin.is_superadmin == True).all()
        self.assertEqual(len(superadmins), 1, "There must be exactly 1 superadmin in the database")
        self.assertEqual(superadmins[0].email, "superadmin@tu-sofia.bg")
        self.assertTrue(superadmins[0].is_verified)

        # Call seed_superadmin again - should not create duplicates
        second_run = seed_superadmin(self.db)
        superadmins_after = self.db.query(Admin).filter(Admin.is_superadmin == True).all()
        self.assertEqual(len(superadmins_after), 1, "Seed logic must remain idempotent")
        self.assertEqual(second_run.id, self.superadmin.id)

    def test_02_enforce_max_one_superadmin(self):
        """ Test that attempting to insert a second superadmin record is rejected """
        second_admin = Admin(
            id=uuid.uuid4(),
            full_name="Second Superadmin Imposter",
            email="imposter@tu-sofia.bg",
            hashed_password=get_password_hash("Password123!"),
            is_verified=True,
            is_superadmin=True
        )
        self.db.add(second_admin)
        with self.assertRaises(Exception):
            self.db.commit()
        self.db.rollback()

    def test_03_superadmin_admin_login(self):
        """ Test superadmin authentication through /admins/login """
        response = client.post(
            "/admins/login",
            data={
                "email": "superadmin@tu-sofia.bg",
                "password": "SuperAdmin123!"
            }
        )
        self.assertEqual(response.status_code, 200, f"Login failed: {response.text}")
        data = response.json()
        self.assertIn("access_token", data)
        self.assertTrue(data.get("is_superadmin"))

        # Verify JWT payload
        payload = jwt.decode(data["access_token"], SECRET_KEY, algorithms=[ALGORITHM])
        self.assertEqual(payload.get("role"), "admin")
        self.assertTrue(payload.get("is_superadmin"))

        # Verify access to admin dashboard data endpoint
        dash_response = client.get(
            "/admins/dashboard-data",
            headers={"Authorization": f"Bearer {data['access_token']}"}
        )
        self.assertEqual(dash_response.status_code, 200)

        # Verify access to admin dashboard HTML page with cookie
        page_response = client.get(
            "/admins/dashboard",
            cookies={"admin_token": data["access_token"]}
        )
        self.assertEqual(page_response.status_code, 200)


    def test_04_superadmin_examiner_login(self):
        """ Test superadmin authentication through /examiners/login (Omni-Role) """
        response = client.post(
            "/examiners/login",
            data={
                "email": "superadmin@tu-sofia.bg",
                "password": "SuperAdmin123!"
            }
        )
        self.assertEqual(response.status_code, 200, f"Examiner login failed: {response.text}")
        data = response.json()
        self.assertIn("access_token", data)
        self.assertTrue(data.get("is_superadmin"))
        self.assertIn("Superadmin", data.get("full_name"))

        # Verify examiner token works on examiner status endpoint
        status_res = client.get(
            f"/api/v1/exams/1151/status?token={data['access_token']}"
        )
        self.assertEqual(status_res.status_code, 200)

    def test_05_superadmin_student_login_variants(self):
        """ Test superadmin authentication through /students/login via email, 'superadmin', and '000000000' """
        test_identifiers = ["superadmin@tu-sofia.bg", "superadmin", "000000000", "0"]
        for ident in test_identifiers:
            response = client.post(
                "/students/login",
                json={
                    "student_id_number": ident,
                    "password": "SuperAdmin123!"
                }
            )
            self.assertEqual(response.status_code, 200, f"Student login failed for {ident}: {response.text}")
            data = response.json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["student_status"], "APPROVED")
            self.assertTrue(data["has_face_embedding"])
            self.assertFalse(data["must_change_password"])

    def test_06_superadmin_student_endpoints(self):
        """ Test student profile, registrations, and password change using superadmin token """
        # 1. Login as student to get token
        login_res = client.post(
            "/students/login",
            json={
                "student_id_number": "000000000",
                "password": "SuperAdmin123!"
            }
        )
        token = login_res.json()["access_token"]
        auth_header = {"Authorization": f"Bearer {token}"}

        # 2. Test /students/profile & /students/me
        profile_res = client.get("/students/profile", headers=auth_header)
        self.assertEqual(profile_res.status_code, 200)
        profile_data = profile_res.json()
        self.assertEqual(profile_data["student_id_number"], "000000000")
        self.assertEqual(profile_data["status"], "APPROVED")
        self.assertTrue(profile_data["has_face_embedding"])

        # 3. Test /students/my-registrations
        exams_res = client.get("/students/my-registrations", headers=auth_header)
        self.assertEqual(exams_res.status_code, 200)
        self.assertIsInstance(exams_res.json(), list)

        # 4. Test delete-account prevention
        del_res = client.delete("/students/delete-account", headers=auth_header)
        self.assertEqual(del_res.status_code, 400, "Superadmin account must not be deleted via mobile student app")

    def test_07_superadmin_password_change(self):
        """ Test changing superadmin password via /students/change-password """
        login_res = client.post(
            "/students/login",
            json={
                "student_id_number": "000000000",
                "password": "SuperAdmin123!"
            }
        )
        token = login_res.json()["access_token"]

        # Change password to new password
        change_res = client.post(
            "/students/change-password",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "old_password": "SuperAdmin123!",
                "new_password": "SuperAdmin456!"
            }
        )
        self.assertEqual(change_res.status_code, 200)

        # Verify old password no longer works
        fail_login = client.post(
            "/admins/login",
            data={
                "email": "superadmin@tu-sofia.bg",
                "password": "SuperAdmin123!"
            }
        )
        self.assertEqual(fail_login.status_code, 400)

        # Verify new password works
        success_login = client.post(
            "/admins/login",
            data={
                "email": "superadmin@tu-sofia.bg",
                "password": "SuperAdmin456!"
            }
        )
        self.assertEqual(success_login.status_code, 200)

        # Reset password back to original SuperAdmin123!
        admin = self.db.query(Admin).filter(Admin.is_superadmin == True).first()
        admin.hashed_password = get_password_hash("SuperAdmin123!")
        self.db.commit()

    def test_08_regular_user_isolation(self):
        """ Test that standard non-superadmin accounts cannot access cross-role endpoints """
        # Create a regular admin (is_superadmin = False)
        reg_email = "standard_admin@tu-sofia.bg"
        reg_admin = self.db.query(Admin).filter(Admin.email == reg_email).first()
        if not reg_admin:
            reg_admin = Admin(
                id=uuid.uuid4(),
                full_name="Standard Administrator",
                email=reg_email,
                hashed_password=get_password_hash("AdminPass123!"),
                is_verified=True,
                is_superadmin=False
            )
            self.db.add(reg_admin)
            self.db.commit()

        # Regular admin CAN log in to /admins/login
        admin_login = client.post("/admins/login", data={"email": reg_email, "password": "AdminPass123!"})
        self.assertEqual(admin_login.status_code, 200)
        reg_token = admin_login.json()["access_token"]

        # Regular admin CANNOT log in to /examiners/login
        examiner_login = client.post("/examiners/login", data={"email": reg_email, "password": "AdminPass123!"})
        self.assertEqual(examiner_login.status_code, 400)

        # Regular admin CANNOT log in to /students/login
        student_login = client.post("/students/login", json={"student_id_number": reg_email, "password": "AdminPass123!"})
        self.assertEqual(student_login.status_code, 401)

        # Regular admin token CANNOT access student endpoints
        stu_res = client.get("/students/profile", headers={"Authorization": f"Bearer {reg_token}"})
        self.assertEqual(stu_res.status_code, 403)

        # Clean up regular admin
        self.db.delete(reg_admin)
        self.db.commit()

    def test_09_superadmin_student_impersonation(self):
        """ Test superadmin student impersonation workflow and RBAC gating """
        # 1. Ensure at least one test student exists in DB
        test_student = self.db.query(Student).filter(Student.student_id_number == "999999999").first()
        created_temp = False
        if not test_student:
            test_student = Student(
                id=uuid.uuid4(),
                full_name="Иван Иванов (Тестов)",
                student_id_number="999999999",
                email="ivan.test@tu-sofia.bg",
                hashed_password=get_password_hash("Student123!"),
                faculty="ФКСТ",
                specialty="КСИ",
                course=3,
                stream=2,
                group=35,
                status="APPROVED",
                must_change_password=False
            )
            self.db.add(test_student)
            self.db.commit()
            created_temp = True

        try:
            # 2. Superadmin login to obtain token
            super_login = client.post("/students/login", json={"student_id_number": "superadmin", "password": "SuperAdmin123!"})
            self.assertEqual(super_login.status_code, 200)
            super_token = super_login.json()["access_token"]
            super_header = {"Authorization": f"Bearer {super_token}"}

            # 3. Superadmin can fetch impersonation list
            list_res = client.get("/students/impersonate/list", headers=super_header)
            self.assertEqual(list_res.status_code, 200)
            students_list = list_res.json()
            self.assertIsInstance(students_list, list)
            self.assertTrue(any(s["student_id_number"] == "999999999" for s in students_list))

            # 4. Superadmin can impersonate the test student
            imp_profile = client.get(f"/students/profile?impersonate_id={test_student.id}", headers=super_header)
            self.assertEqual(imp_profile.status_code, 200)
            profile_data = imp_profile.json()
            self.assertEqual(profile_data["student_id_number"], "999999999")
            self.assertEqual(profile_data["full_name"], "Иван Иванов (Тестов)")
            self.assertTrue(profile_data["is_superadmin"])
            self.assertTrue(profile_data["is_impersonating"])

            # 5. Superadmin can fetch impersonated student's registrations
            imp_regs = client.get(f"/students/my-registrations?impersonate_id={test_student.id}", headers=super_header)
            self.assertEqual(imp_regs.status_code, 200)
            self.assertIsInstance(imp_regs.json(), list)

            # 6. Regular student login
            reg_student_login = client.post("/students/login", json={"student_id_number": "999999999", "password": "Student123!"})
            self.assertEqual(reg_student_login.status_code, 200)
            reg_student_token = reg_student_login.json()["access_token"]
            reg_student_header = {"Authorization": f"Bearer {reg_student_token}"}

            # 7. Regular student CANNOT access /students/impersonate/list
            forbidden_list = client.get("/students/impersonate/list", headers=reg_student_header)
            self.assertEqual(forbidden_list.status_code, 403)

            # 8. Regular student CANNOT impersonate another student
            forbidden_imp = client.get(f"/students/profile?impersonate_id={test_student.id}", headers=reg_student_header)
            self.assertEqual(forbidden_imp.status_code, 403)
        finally:
            if created_temp:
                self.db.delete(test_student)
                self.db.commit()


if __name__ == "__main__":
    unittest.main()


