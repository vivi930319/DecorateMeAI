import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app as app_module


class AdminPermissionTests(unittest.TestCase):
    @staticmethod
    def _admin_member():
        member = SimpleNamespace(
            name="Administrator",
            email="admin@example.invalid",
            phone_number="admin-test",
            age=None,
            role="admin",
            level="gold",
            status="active",
            email_verified=True,
            allowed_pages=["dashboard"],
            vip_requested=False,
            points=0,
            lifetime_points=0,
            total_earned_points=0,
            render_daily_limit=None,
            render_remaining=None,
            render_reset_at=None,
        )
        member.level_label = lambda: "管理員"
        member.member_role = lambda: member.role
        return member

    def test_admin_role_ignores_incomplete_saved_page_checklist(self):
        member = self._admin_member()

        payload = app_module.member_profile_payload(member)

        self.assertEqual(payload["role"], "admin")
        self.assertIn("admin", payload["allowedPages"])
        self.assertIn("analysisPro", payload["allowedPages"])
        self.assertIn("unlimitedRender", payload["allowedPages"])
        self.assertGreater(len(payload["allowedPages"]), 1)

    def test_saving_unchanged_admin_role_does_not_revoke_session(self):
        member = self._admin_member()
        actor = SimpleNamespace(email="admin@example.invalid")
        with app_module.app.test_request_context(
            "/api/members/admin@example.invalid",
            method="PATCH",
            json={"role": "admin", "status": "active", "allowedPages": ["dashboard"]},
        ), patch.object(app_module, "require_admin", return_value=None), patch.object(
            app_module, "require_actor", return_value=(actor, None)
        ), patch.object(app_module, "Members") as members_model, patch.object(
            app_module, "revoke_all_member_sessions"
        ) as revoke_sessions, patch.object(app_module, "log_audit") as log_audit, patch.object(
            app_module.db.session, "commit"
        ):
            members_model.query.filter_by.return_value.first.return_value = member

            response, status = app_module.update_member_api("admin@example.invalid")

        self.assertEqual(status, 200)
        self.assertEqual(response.get_json()["member"]["role"], "admin")
        self.assertIn("admin", member.allowed_pages)
        revoke_sessions.assert_not_called()
        log_audit.assert_not_called()

    def test_actual_role_change_still_revokes_sessions(self):
        member = self._admin_member()
        actor = SimpleNamespace(email="operator@example.invalid")
        with app_module.app.test_request_context(
            "/api/members/admin@example.invalid",
            method="PATCH",
            json={"role": "member"},
        ), patch.object(app_module, "require_admin", return_value=None), patch.object(
            app_module, "require_actor", return_value=(actor, None)
        ), patch.object(app_module, "Members") as members_model, patch.object(
            app_module, "revoke_all_member_sessions"
        ) as revoke_sessions, patch.object(app_module, "log_audit"), patch.object(
            app_module.db.session, "commit"
        ):
            members_model.query.filter_by.return_value.first.return_value = member

            _, status = app_module.update_member_api("admin@example.invalid")

        self.assertEqual(status, 200)
        self.assertEqual(member.role, "member")
        revoke_sessions.assert_called_once_with(member)


if __name__ == "__main__":
    unittest.main()
