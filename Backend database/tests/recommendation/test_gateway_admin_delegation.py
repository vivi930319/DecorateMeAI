import unittest
from unittest.mock import patch

import app as app_module


class GatewayAdminDelegationTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)

    def test_admin_marker_and_valid_gateway_key_are_both_required(self):
        with patch.object(app_module, "GATEWAY_API_KEY", "shared-secret"):
            with app_module.app.test_request_context(headers={"X-Admin-Request": "1"}):
                self.assertIsNotNone(app_module.require_admin())
            with app_module.app.test_request_context(headers={"X-Gateway-Key": "shared-secret"}):
                self.assertIsNotNone(app_module.require_admin())
            with app_module.app.test_request_context(headers={
                "X-Admin-Request": "1", "X-Gateway-Key": "wrong-secret",
            }):
                self.assertIsNotNone(app_module.require_admin())

    def test_trusted_gateway_can_read_member_directory_without_admin_marker(self):
        with patch.object(app_module, "GATEWAY_API_KEY", "shared-secret"):
            with app_module.app.test_request_context(
                "/api/members",
                method="GET",
                headers={"X-Gateway-Key": "shared-secret"},
            ):
                self.assertIsNone(app_module.require_member_directory_admin())

    def test_wrong_gateway_key_cannot_read_member_directory(self):
        with patch.object(app_module, "GATEWAY_API_KEY", "shared-secret"):
            with app_module.app.test_request_context(
                "/api/members",
                method="GET",
                headers={"X-Gateway-Key": "wrong-secret"},
            ):
                self.assertIsNotNone(app_module.require_member_directory_admin())

    def test_gateway_key_alone_never_authorizes_state_changes(self):
        with patch.object(app_module, "GATEWAY_API_KEY", "shared-secret"):
            with app_module.app.test_request_context(
                "/api/members/member@example.com",
                method="PATCH",
                headers={"X-Gateway-Key": "shared-secret"},
            ):
                self.assertIsNotNone(app_module.require_member_directory_admin())
                self.assertIsNotNone(app_module.require_admin())

    def test_valid_gateway_admin_headers_supply_non_pii_admin_actor(self):
        with patch.object(app_module, "GATEWAY_API_KEY", "shared-secret"):
            with app_module.app.test_request_context(headers={
                "X-Admin-Request": "1", "X-Gateway-Key": "shared-secret",
            }):
                self.assertIsNone(app_module.require_admin())
                actor, error = app_module.authenticated_member()
                self.assertIsNone(error)
                self.assertEqual(actor.member_role(), "admin")
                self.assertEqual(actor.email, "gateway-admin@service.invalid")

    def test_admin_delegation_is_disabled_when_service_key_is_unconfigured(self):
        with patch.object(app_module, "GATEWAY_API_KEY", None):
            with app_module.app.test_request_context(headers={
                "X-Admin-Request": "1", "X-Gateway-Key": "anything",
            }):
                self.assertIsNotNone(app_module.require_admin())


if __name__ == "__main__":
    unittest.main()
