import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app as app_module


class VerifyPasswordResetOtpCompatibilityTests(unittest.TestCase):
    def test_shared_verify_endpoint_accepts_redis_reset_otp(self):
        registration_query = MagicMock()
        registration_query.filter.return_value.order_by.return_value.first.return_value = None
        member_query = MagicMock()
        member_query.filter_by.return_value.first.return_value = SimpleNamespace(email="member@example.com")
        redis_client = MagicMock()
        redis_client.get.return_value = b"hashed-reset-otp"
        redis_client.incr.return_value = 1

        with app_module.app.test_request_context(
            "/api/verify-otp",
            method="POST",
            json={"email": "member@example.com", "otp": "123456"},
        ), patch.object(
            app_module.OTPCode, "query", registration_query
        ), patch.object(
            app_module.Members, "query", member_query
        ), patch.object(
            app_module, "r", redis_client
        ), patch.object(
            app_module.bcrypt, "check_password_hash", return_value=True
        ):
            response, status = app_module.verify_otp()

        self.assertEqual(status, 200)
        self.assertTrue(response.get_json()["otpVerified"])
        self.assertEqual(response.get_json()["purpose"], "password_reset")


if __name__ == "__main__":
    unittest.main()
