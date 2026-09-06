import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app as app_module


class SavedLooksContractTests(unittest.TestCase):
    def setUp(self):
        app_module.app.config.update(TESTING=True)
        self.actor = SimpleNamespace(email="member@example.com")

    def test_default_limit_is_100(self):
        self.assertEqual(app_module.SAVED_LOOK_LIMIT, 100)

    def test_create_rejects_only_at_configured_limit(self):
        query = MagicMock()
        query.filter_by.return_value.count.return_value = 100
        with app_module.app.test_request_context(
            "/api/members/member@example.com/saved-looks",
            method="POST",
            json={
                "style": "港風",
                "beforeImageUrl": "/media/render/0123456789abcdef0123456789abcdef/before",
                "afterImageUrl": "/media/render/0123456789abcdef0123456789abcdef",
            },
        ), patch.object(app_module, "require_actor", return_value=(self.actor, None)), patch.object(
            app_module, "require_self", return_value=(self.actor.email, None)
        ), patch.object(app_module.SavedLook, "query", query):
            response, status = app_module.create_saved_look(self.actor.email)

        self.assertEqual(status, 409)
        self.assertEqual(response.get_json()["error"]["code"], "SAVED_LOOK_LIMIT")
        self.assertIn("100", response.get_json()["error"]["message"])

    def test_delete_uses_hard_delete_and_commits(self):
        filtered = MagicMock()
        filtered.delete.return_value = 1
        query = MagicMock()
        query.filter_by.return_value = filtered
        with app_module.app.test_request_context(
            "/api/members/member@example.com/saved-looks/123", method="DELETE"
        ), patch.object(app_module, "require_actor", return_value=(self.actor, None)), patch.object(
            app_module, "require_self_or_admin", return_value=(self.actor.email, None)
        ), patch.object(app_module.SavedLook, "query", query), patch.object(
            app_module.db.session, "commit"
        ) as commit:
            response, status = app_module.delete_saved_look(self.actor.email, 123)

        self.assertEqual(status, 200)
        self.assertEqual(response.get_json()["action"], "saved_look_hard_deleted")
        filtered.delete.assert_called_once_with(synchronize_session=False)
        commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
