import unittest

import app as app_module


class SessionTtlContractTests(unittest.TestCase):
    def test_member_session_matches_gateway_default(self):
        self.assertEqual(app_module.SESSION_MAX_AGE, 28800)


if __name__ == "__main__":
    unittest.main()
