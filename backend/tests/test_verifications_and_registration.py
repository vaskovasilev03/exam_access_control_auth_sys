import os
import unittest
import uuid
import jwt
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

os.environ["SUPERADMIN_EMAIL"] = "superadmin@tu-sofia.bg"
os.environ["SUPERADMIN_PASSWORD"] = "SuperAdmin123!"
os.environ["SUPERADMIN_NAME"] = "Super Administrator"

from app.main import app
from app.database import get_db, SessionLocal, init_db
from app.models import Admin, Examiner, SecureKey
from app.seed import seed_superadmin
from app.auth import get_password_hash, SECRET_KEY, ALGORITHM

client = TestClient(app)

class VerificationsAndRegistrationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.db: Session = SessionLocal()
        self.superadmin = seed_superadmin(self.db)
        # Login as superadmin to get token
        login_res = client.post(
            "/login",
            data={
                "email": "superadmin@tu-sofia.bg",
                "password": "SuperAdmin123!",
                "role": "admin"
            }
        )
        self.superadmin_token = login_res.json()["access_token"]
        self.superadmin_headers = {"Authorization": f"Bearer {self.superadmin_token}"}

    def tearDown(self):
        self.db.close()

    def test_01_html_views_served_successfully(self):
        """ Test that /login and /register HTML endpoints serve 200 OK """
        res_login = client.get("/login")
        self.assertEqual(res_login.status_code, 200)
        self.assertIn("Вход в системата", res_login.text)

        res_register = client.get("/register")
        self.assertEqual(res_register.status_code, 200)
        self.assertIn("Регистрация в системата", res_register.text)
        self.assertIn("Register using a Secure Key!", res_register.text)

    def test_02_registration_without_key_creates_unverified_accounts(self):
        """ Test that registering without a secure key creates accounts with is_verified=False """
        admin_email = f"pending_admin_{uuid.uuid4().hex[:6]}@tu-sofia.bg"
        res_admin = client.post(
            "/register",
            json={
                "full_name": "Pending Admin",
                "email": admin_email,
                "password": "AdminPassword123!",
                "role": "admin"
            }
        )
        self.assertEqual(res_admin.status_code, 200)
        data_admin = res_admin.json()
        self.assertFalse(data_admin["is_verified"])
        self.assertIn("Waiting for superadmin verification", data_admin["message"])

        # Attempt to login should fail with 403
        login_fail = client.post("/login", data={"email": admin_email, "password": "AdminPassword123!", "role": "admin"})
        self.assertEqual(login_fail.status_code, 403)
        self.assertIn("pending verification", login_fail.json()["detail"])

        examiner_email = f"pending_examiner_{uuid.uuid4().hex[:6]}@tu-sofia.bg"
        res_examiner = client.post(
            "/register",
            json={
                "full_name": "Pending Examiner",
                "email": examiner_email,
                "password": "ExaminerPassword123!",
                "role": "examiner"
            }
        )
        self.assertEqual(res_examiner.status_code, 200)
        data_examiner = res_examiner.json()
        self.assertFalse(data_examiner["is_verified"])
        self.assertIn("Waiting for superadmin verification", data_examiner["message"])

        # Attempt to login as unverified examiner should fail with 403
        login_fail_ex = client.post("/login", data={"email": examiner_email, "password": "ExaminerPassword123!", "role": "examiner"})
        self.assertEqual(login_fail_ex.status_code, 403)

    def test_03_superadmin_verifications_list_and_sorting(self):
        """ Test superadmin pending verifications query and chronological sorting (oldest first) """
        res = client.get("/admins/verifications/pending", headers=self.superadmin_headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("pending_verifications", data)
        items = data["pending_verifications"]
        self.assertIsInstance(items, list)

        # Check chronological order if at least 2 items
        if len(items) >= 2:
            timestamps = [item["created_at"] for item in items if item.get("created_at")]
            self.assertEqual(timestamps, sorted(timestamps), "Verifications list must be sorted oldest first")

    def test_04_regular_admin_forbidden_from_verifications(self):
        """ Test that a non-superadmin verified admin cannot access verification endpoints """
        # Create a verified regular admin
        reg_email = f"reg_admin_{uuid.uuid4().hex[:6]}@tu-sofia.bg"
        reg_admin = Admin(
            id=uuid.uuid4(),
            full_name="Regular Verified Admin",
            email=reg_email,
            hashed_password=get_password_hash("RegularPass123!"),
            is_verified=True,
            is_superadmin=False
        )
        self.db.add(reg_admin)
        self.db.commit()

        login_res = client.post("/login", data={"email": reg_email, "password": "RegularPass123!", "role": "admin"})
        self.assertEqual(login_res.status_code, 200)
        reg_token = login_res.json()["access_token"]
        reg_headers = {"Authorization": f"Bearer {reg_token}"}

        # Accessing verifications should return 403
        res = client.get("/admins/verifications/pending", headers=reg_headers)
        self.assertEqual(res.status_code, 403)

        # Accessing secure-key should return 403
        res_key = client.get("/admins/secure-key/status", headers=reg_headers)
        self.assertEqual(res_key.status_code, 403)

    def test_05_grant_access_approves_account(self):
        """ Test granting access (V) updates is_verified=True and enables immediate login """
        email = f"approve_me_{uuid.uuid4().hex[:6]}@tu-sofia.bg"
        client.post(
            "/register",
            json={
                "full_name": "Approve Me Admin",
                "email": email,
                "password": "ApprovePass123!",
                "role": "admin"
            }
        )
        admin_row = self.db.query(Admin).filter(Admin.email == email).first()
        self.assertFalse(admin_row.is_verified)

        grant_res = client.post(
            f"/admins/verifications/admin/{admin_row.id}/grant",
            headers=self.superadmin_headers
        )
        self.assertEqual(grant_res.status_code, 200)

        # Now login should succeed
        login_res = client.post("/login", data={"email": email, "password": "ApprovePass123!", "role": "admin"})
        self.assertEqual(login_res.status_code, 200)
        self.assertIn("access_token", login_res.json())

    def test_06_reject_access_deletes_unverified_account(self):
        """ Test rejecting request (X) removes the unverified record from database """
        email = f"reject_me_{uuid.uuid4().hex[:6]}@tu-sofia.bg"
        client.post(
            "/register",
            json={
                "full_name": "Reject Me Examiner",
                "email": email,
                "password": "RejectPass123!",
                "role": "examiner"
            }
        )
        examiner_row = self.db.query(Examiner).filter(Examiner.email == email).first()
        self.assertIsNotNone(examiner_row)

        reject_res = client.post(
            f"/admins/verifications/examiner/{examiner_row.id}/reject",
            headers=self.superadmin_headers
        )
        self.assertEqual(reject_res.status_code, 200)

        # Verify row is deleted
        self.db.expire_all()
        deleted_row = self.db.query(Examiner).filter(Examiner.email == email).first()
        self.assertIsNone(deleted_row)

    def test_07_secure_key_generation_and_masking(self):
        """ Test generating secure key with different durations and verifying masking """
        for duration in ["1_day", "1_week", "1_month", "indefinite"]:
            gen_res = client.post(
                "/admins/secure-key/generate",
                json={"duration": duration},
                headers=self.superadmin_headers
            )
            self.assertEqual(gen_res.status_code, 200)
            data = gen_res.json()
            raw_key = data["secure_key"]
            self.assertTrue(len(raw_key) > 20)
            self.assertEqual(data["duration_type"], duration)

            # Check status endpoint - must NOT return raw key! Must return masked ********
            status_res = client.get("/admins/secure-key/status", headers=self.superadmin_headers)
            self.assertEqual(status_res.status_code, 200)
            status_data = status_res.json()
            self.assertTrue(status_data["has_active_key"])
            self.assertTrue(status_data["unattended_enabled"])
            self.assertEqual(status_data["masked_key"], "********")
            self.assertNotEqual(status_data["masked_key"], raw_key)

    def test_08_registration_with_valid_secure_key(self):
        """ Test registering with a valid secure key results in is_verified=True and instant login """
        # Generate active key
        gen_res = client.post(
            "/admins/secure-key/generate",
            json={"duration": "1_week"},
            headers=self.superadmin_headers
        )
        valid_key = gen_res.json()["secure_key"]

        admin_email = f"instant_admin_{uuid.uuid4().hex[:6]}@tu-sofia.bg"
        res_admin = client.post(
            "/register",
            json={
                "full_name": "Instant Admin",
                "email": admin_email,
                "password": "InstantPass123!",
                "role": "admin",
                "secure_key": valid_key
            }
        )
        self.assertEqual(res_admin.status_code, 200)
        self.assertTrue(res_admin.json()["is_verified"])

        # Should be able to log in immediately
        login_res = client.post("/login", data={"email": admin_email, "password": "InstantPass123!", "role": "admin"})
        self.assertEqual(login_res.status_code, 200)

        examiner_email = f"instant_examiner_{uuid.uuid4().hex[:6]}@tu-sofia.bg"
        res_examiner = client.post(
            "/register",
            json={
                "full_name": "Instant Examiner",
                "email": examiner_email,
                "password": "InstantPass123!",
                "role": "examiner",
                "secure_key": valid_key
            }
        )
        self.assertEqual(res_examiner.status_code, 200)
        self.assertTrue(res_examiner.json()["is_verified"])

        # Should be able to log in immediately
        login_ex = client.post("/login", data={"email": examiner_email, "password": "InstantPass123!", "role": "examiner"})
        self.assertEqual(login_ex.status_code, 200)

    def test_09_registration_with_invalid_secure_key_fails(self):
        """ Test registration with invalid secure key fails with 400 error """
        email = f"fake_key_{uuid.uuid4().hex[:6]}@tu-sofia.bg"
        res = client.post(
            "/register",
            json={
                "full_name": "Fake Key Admin",
                "email": email,
                "password": "FakePass123!",
                "role": "admin",
                "secure_key": "invalid_or_forged_key"
            }
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("Secure Key", res.json()["detail"])

    def test_10_secure_key_deletion_revokes_key(self):
        """ Test that deleting a secure key revokes it from further registrations """
        gen_res = client.post(
            "/admins/secure-key/generate",
            json={"duration": "1_day"},
            headers=self.superadmin_headers
        )
        key_to_delete = gen_res.json()["secure_key"]

        # Delete key
        del_res = client.delete("/admins/secure-key", headers=self.superadmin_headers)
        self.assertEqual(del_res.status_code, 200)

        # Status should show no active key
        status_res = client.get("/admins/secure-key/status", headers=self.superadmin_headers)
        self.assertFalse(status_res.json()["has_active_key"])

        # Registering with deleted key should now fail
        email = f"revoked_key_{uuid.uuid4().hex[:6]}@tu-sofia.bg"
        res = client.post(
            "/register",
            json={
                "full_name": "Revoked Key User",
                "email": email,
                "password": "RevokedPass123!",
                "role": "admin",
                "secure_key": key_to_delete
            }
        )
        self.assertEqual(res.status_code, 400)

    def test_11_regular_admin_cannot_see_or_access_verifications_tab(self):
        """ Test that regular admin does NOT see the Verifications tab, panel, or modal, and only superadmin does """
        # Create and verify a regular admin
        reg_email = f"regular_admin_{uuid.uuid4().hex[:6]}@tu-sofia.bg"
        reg_admin = Admin(
            id=uuid.uuid4(),
            email=reg_email,
            full_name="Regular Admin User",
            hashed_password=get_password_hash("RegPass123!"),
            is_superadmin=False,
            is_verified=True
        )
        self.db.add(reg_admin)
        self.db.commit()

        # Login as regular admin
        login_res = client.post(
            "/login",
            data={
                "email": reg_email,
                "password": "RegPass123!",
                "role": "admin"
            }
        )
        self.assertEqual(login_res.status_code, 200)
        reg_token = login_res.json()["access_token"]
        self.assertFalse(login_res.json()["is_superadmin"])

        # 1. GET /admins/dashboard as regular admin
        reg_dash_page = client.get(
            "/admins/dashboard",
            cookies={"admin_token": reg_token}
        )
        self.assertEqual(reg_dash_page.status_code, 200)
        # Verify Verifications tab button, panel, and modal HTML elements are NOT in the page for normal admin
        self.assertNotIn('id="verificationsTabBtn"', reg_dash_page.text)
        self.assertNotIn('id="panel-verifications"', reg_dash_page.text)
        self.assertNotIn('id="generateKeyModal"', reg_dash_page.text)

        # 2. GET /admins/dashboard as superadmin
        super_dash_page = client.get(
            "/admins/dashboard",
            cookies={"admin_token": self.superadmin_token}
        )
        self.assertEqual(super_dash_page.status_code, 200)
        # Verify Verifications tab button, panel, and modal HTML elements ARE in the page for superadmin
        self.assertIn('id="verificationsTabBtn"', super_dash_page.text)
        self.assertIn('id="panel-verifications"', super_dash_page.text)
        self.assertIn('id="generateKeyModal"', super_dash_page.text)

        # 3. GET /admins/dashboard-data as regular admin
        reg_dash_data = client.get(
            "/admins/dashboard-data",
            headers={"Authorization": f"Bearer {reg_token}"}
        )
        self.assertEqual(reg_dash_data.status_code, 200)
        self.assertFalse(reg_dash_data.json()["is_superadmin"])
        self.assertEqual(reg_dash_data.json()["pending_verifications_count"], 0)

        # 4. Attempting to call verifications or secure key endpoints as regular admin returns 403
        pending_attempt = client.get(
            "/admins/verifications/pending",
            headers={"Authorization": f"Bearer {reg_token}"}
        )
        self.assertEqual(pending_attempt.status_code, 403)

        key_status_attempt = client.get(
            "/admins/secure-key/status",
            headers={"Authorization": f"Bearer {reg_token}"}
        )
        self.assertEqual(key_status_attempt.status_code, 403)

if __name__ == "__main__":
    unittest.main()

