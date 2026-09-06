import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app as app_module


class ChangePasswordApiTests(unittest.TestCase):
    @staticmethod
    def member():
        member = SimpleNamespace(password=None)
        member.verify_password = lambda value: value in {"old-password", "same-password"}
        return member

    def test_rejects_incorrect_current_password(self):
        member = self.member()
        with app_module.app.test_request_context(
            "/api/change-password",
            method="POST",
            json={
                "currentPassword": "wrong-password",
                "newPassword": "new-password",
                "confirmPassword": "new-password",
            },
        ), patch.object(app_module, "require_actor", return_value=(member, None)):
            response, status = app_module.api_change_password()

        self.assertEqual(status, 401)
        self.assertEqual(response.get_json()["error"]["code"], "CURRENT_PASSWORD_INCORRECT")

    def test_rejects_confirmation_mismatch(self):
        member = self.member()
        with app_module.app.test_request_context(
            "/api/change-password",
            method="POST",
            json={
                "currentPassword": "old-password",
                "newPassword": "new-password",
                "confirmPassword": "different-password",
            },
        ), patch.object(app_module, "require_actor", return_value=(member, None)):
            response, status = app_module.api_change_password()

        self.assertEqual(status, 422)
        self.assertEqual(response.get_json()["error"]["code"], "PASSWORD_MISMATCH")

    def test_changes_password_and_revokes_sessions(self):
        member = self.member()
        with app_module.app.test_request_context(
            "/api/change-password",
            method="POST",
            json={
                "currentPassword": "old-password",
                "newPassword": "new-password",
                "confirmPassword": "new-password",
            },
        ), patch.object(
            app_module, "require_actor", return_value=(member, None)
        ), patch.object(
            app_module, "revoke_all_member_sessions"
        ) as revoke, patch.object(app_module.db.session, "commit"):
            response = app_module.api_change_password()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["code"], "PASSWORD_CHANGED")
        self.assertTrue(response.get_json()["logoutRequired"])
        self.assertEqual(member.password, "new-password")
        revoke.assert_called_once_with(member)


if __name__ == "__main__":
    unittest.main()
