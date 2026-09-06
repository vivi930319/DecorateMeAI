import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app as app_module
from forms import ChangePasswordForm, ResetPasswordForm
from otp_utils import generate_otp


class PasswordResetContractTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        self.app_context = app_module.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_unknown_email_never_creates_or_sends_an_otp(self):
        query = MagicMock()
        query.filter_by.return_value.first.return_value = None
        with patch.object(app_module.Members, "query", query), \
                patch.object(app_module, "send_otp_email") as send:
            success, code, _, status = app_module._request_password_reset_otp("missing@example.com")

        self.assertFalse(success)
        self.assertEqual(code, "EMAIL_NOT_REGISTERED")
        self.assertEqual(status, 404)
        send.assert_not_called()

    def test_registered_email_sends_otp_and_sets_five_minute_ttl(self):
        member = SimpleNamespace(email_verified=True, status="active", member_role=lambda: "member")
        query = MagicMock()
        query.filter_by.return_value.first.return_value = member
        redis_client = MagicMock()
        redis_client.ttl.return_value = -2
        redis_client.incr.return_value = 1
        with patch.object(app_module.Members, "query", query), \
                patch.object(app_module, "r", redis_client), \
                patch.object(app_module, "send_otp_email") as send:
            success, code, _, status = app_module._request_password_reset_otp("member@example.com")

        self.assertTrue(success)
        self.assertEqual(code, "OTP_SENT")
        self.assertEqual(status, 200)
        self.assertEqual(redis_client.set.call_args.kwargs["ex"], app_module.OTP_EXPIRE)
        send.assert_called_once()

    def test_email_failure_removes_the_unusable_redis_otp(self):
        member = SimpleNamespace(email_verified=True, status="active", member_role=lambda: "member")
        query = MagicMock()
        query.filter_by.return_value.first.return_value = member
        redis_client = MagicMock()
        redis_client.ttl.return_value = -2
        redis_client.incr.return_value = 1
        with patch.object(app_module.Members, "query", query), \
                patch.object(app_module, "r", redis_client), \
                patch.object(app_module, "send_otp_email", side_effect=RuntimeError("smtp failed")):
            success, code, _, status = app_module._request_password_reset_otp("member@example.com")

        self.assertFalse(success)
        self.assertEqual(code, "OTP_SEND_FAILED")
        self.assertEqual(status, 502)
        redis_client.delete.assert_any_call(app_module.redis_key("member@example.com"))

    def test_registration_api_rejects_password_shorter_than_reset_policy(self):
        response = app_module.app.test_client().post("/api/register", json={
            "phone_number": "0912345678",
            "name": "Test User",
            "email": "test@example.com",
            "password": "12345",
            "age": 20,
        })

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.get_json()["error"]["code"], "INVALID_PASSWORD")

    def test_reset_and_change_forms_share_six_to_128_character_policy(self):
        with app_module.app.test_request_context("/"):
            reset = ResetPasswordForm(
                meta={"csrf": False}, email="member@example.com", otp="123456",
                new_password="12345", confirm_new_password="12345",
            )
            change = ChangePasswordForm(
                meta={"csrf": False}, old_password="old-password",
                new_password="x" * 129, confirm_new_password="x" * 129,
            )
            self.assertFalse(reset.validate())
            self.assertIn("密碼需為 6～128 碼", reset.new_password.errors)
            self.assertFalse(change.validate())
            self.assertIn("密碼需為 6～128 碼", change.new_password.errors)

    def test_otp_generator_always_returns_six_digits(self):
        values = {generate_otp() for _ in range(20)}
        self.assertTrue(all(len(value) == 6 and value.isdigit() for value in values))
        self.assertGreater(len(values), 1)


if __name__ == "__main__":
    unittest.main()
