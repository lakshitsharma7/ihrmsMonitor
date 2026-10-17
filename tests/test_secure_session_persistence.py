"""Unit tests for secure session persistence, restart restoration, and revocation."""

import os
import sys
import unittest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

os.environ["IHRMS_TEST_MODE"] = "1"
app = QApplication.instance() or QApplication([])

from services.secure_session import SessionStore, _cred_write, _cred_read, _cred_delete
from services.session_service import SessionService


class TestSecureSessionPersistence(unittest.TestCase):
    def setUp(self):
        self.store = SessionStore(is_test=True)
        self.store.clear_session()
        SessionService().clear()

    def tearDown(self):
        self.store.clear_session()
        SessionService().clear()

    def test_credential_manager_roundtrip(self):
        """Test Windows Credential Manager direct read/write if on Windows."""
        if not sys.platform.startswith("win"):
            self.skipTest("Windows Credential Manager tests run only on Windows")

        target = "iHRMS_Desktop_Test:unit_test_cred"
        data = {
            "company_code": "TEST-CORP",
            "indo_code": "EMP001",
            "api_key": "api_secret_key_xyz",
            "device_token": "token_device_abc",
            "username": "tester",
        }
        written = _cred_write(target, "tester", data)
        self.assertTrue(written, "CredWrite should succeed")

        read_data = _cred_read(target)
        self.assertIsNotNone(read_data, "CredRead should return stored dict")
        self.assertEqual(read_data.get("company_code"), "TEST-CORP")
        self.assertEqual(read_data.get("indo_code"), "EMP001")
        self.assertEqual(read_data.get("api_key"), "api_secret_key_xyz")
        self.assertEqual(read_data.get("device_token"), "token_device_abc")

        deleted = _cred_delete(target)
        self.assertTrue(deleted, "CredDelete should succeed")
        self.assertIsNone(_cred_read(target), "CredRead after delete should return None")

    def test_save_and_load_session(self):
        """Verify complete session save and restoration across simulated app restarts."""
        saved = self.store.save_session(
            company_code="CORP123",
            indo_code="EMP_99",
            api_key="KEY_SECRET_777",
            device_token="DEV_TOK_888",
            username="john_doe",
            full_name="John Doe",
            user_type="Joined",
            employee_id="99",
            device_info={"hostname": "DESKTOP-TEST", "platform": "Windows"},
            workpulse_permitted=True,
            base_url="https://api.testcorp.com/v1",
            company_id="42",
            allow_user_device=True,
            allow_logout=True,
            session_credential="mypassword",
        )
        self.assertTrue(saved, "Session should save successfully")

        # Simulate subsequent application launch: new SessionStore instance
        restart_store = SessionStore(is_test=True)
        session = restart_store.load_session()
        self.assertIsNotNone(session, "Session should be restored on subsequent launch")
        self.assertEqual(session.get("company_code"), "CORP123")
        self.assertEqual(session.get("username"), "john_doe")
        self.assertEqual(session.get("indo_code"), "EMP_99")
        self.assertEqual(session.get("api_key"), "KEY_SECRET_777")
        self.assertEqual(session.get("device_token"), "DEV_TOK_888")
        self.assertEqual(session.get("base_url"), "https://api.testcorp.com/v1")
        self.assertEqual(session.get("company_id"), "42")
        self.assertEqual(session.get("session_credential"), "mypassword")

        # Verify restore into SessionService
        SessionService().restore_session(
            username=session["username"],
            role=session.get("user_type", "User"),
            full_name=session.get("full_name"),
            user_type=session.get("user_type", "User"),
            workpulse_permitted=session.get("workpulse_permitted", True),
            allow_user_device=session.get("allow_user_device", True),
            allow_logout=session.get("allow_logout", True),
            indo_code=session["indo_code"],
            api_key=session["api_key"],
            employee_id=session.get("employee_id"),
            company_code=session["company_code"],
            device_token=session["device_token"],
            session_credential=session.get("session_credential"),
        )
        current_u = SessionService().current_user
        self.assertIsNotNone(current_u)
        self.assertEqual(current_u.username, "john_doe")
        self.assertEqual(current_u.company_code, "CORP123")
        self.assertEqual(current_u.device_token, "DEV_TOK_888")

    def test_device_token_update(self):
        """Verify device token can be updated without re-entering credentials."""
        self.store.save_session(
            company_code="CORP123",
            indo_code="EMP_99",
            api_key="KEY_SECRET_777",
            device_token="OLD_TOKEN",
            username="john_doe",
            full_name="John Doe",
            user_type="Joined",
            employee_id="99",
            device_info={},
            workpulse_permitted=True,
        )
        self.store.update_device_token("NEW_ROTATED_TOKEN")

        reloaded = self.store.load_session()
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.get("device_token"), "NEW_ROTATED_TOKEN")
        self.assertEqual(reloaded.get("indo_code"), "EMP_99")

    def test_session_revocation_purges_store(self):
        """Verify server session revocation purges the session store and notifies listeners."""
        self.store.save_session(
            company_code="CORP123",
            indo_code="EMP_99",
            api_key="KEY_SECRET_777",
            device_token="DEV_TOK_888",
            username="john_doe",
            full_name="John Doe",
            user_type="Joined",
            employee_id="99",
            device_info={},
            workpulse_permitted=True,
        )
        self.assertIsNotNone(self.store.load_session())

        revoked_reasons = []
        def _on_revoked(reason):
            revoked_reasons.append(reason)

        SessionService().register_session_revoked_listener(_on_revoked)
        SessionService().notify_session_revoked("Token expired by administrator")

        self.assertEqual(len(revoked_reasons), 1)
        self.assertIn("Token expired", revoked_reasons[0])
        # Persistent storage must be empty now
        self.assertIsNone(self.store.load_session())
        self.assertIsNone(SessionService().current_user)

    def test_clean_logout_purges_store(self):
        """Verify explicit logout removes session so credentials are not bypassed."""
        self.store.save_session(
            company_code="CORP123",
            indo_code="EMP_99",
            api_key="KEY_SECRET_777",
            device_token="DEV_TOK_888",
            username="john_doe",
            full_name="John Doe",
            user_type="Joined",
            employee_id="99",
            device_info={},
            workpulse_permitted=True,
        )
        self.assertIsNotNone(self.store.load_session())

        # Call clear_session as done on logout
        self.store.clear_session()
        self.assertIsNone(self.store.load_session())


if __name__ == "__main__":
    unittest.main()
