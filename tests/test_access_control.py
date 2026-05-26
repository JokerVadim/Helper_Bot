import unittest
from unittest.mock import patch

from utils import is_authorized


class AccessControlTests(unittest.TestCase):
    def test_admin_is_authorized_even_in_lockdown(self):
        with (
            patch("config.ADMIN_ID", 100),
            patch("config.ALLOWED_IDS", set()),
            patch("db.db.get_lockdown", return_value=True),
            patch("db.db.is_user_allowed", return_value=False),
        ):
            self.assertTrue(is_authorized(100))

    def test_everyone_is_authorized_when_lockdown_is_off(self):
        with (
            patch("config.ADMIN_ID", None),
            patch("config.ALLOWED_IDS", set()),
            patch("db.db.get_lockdown", return_value=False),
            patch("db.db.is_user_allowed", return_value=False),
        ):
            self.assertTrue(is_authorized(555))

    def test_lockdown_uses_static_allowed_ids_and_database_whitelist(self):
        with (
            patch("config.ADMIN_ID", None),
            patch("config.ALLOWED_IDS", {10}),
            patch("db.db.get_lockdown", return_value=True),
            patch("db.db.is_user_allowed", return_value=False),
        ):
            self.assertTrue(is_authorized(10))
            self.assertFalse(is_authorized(11))

        with (
            patch("config.ADMIN_ID", None),
            patch("config.ALLOWED_IDS", set()),
            patch("db.db.get_lockdown", return_value=True),
            patch("db.db.is_user_allowed", return_value=True),
        ):
            self.assertTrue(is_authorized(11))


if __name__ == "__main__":
    unittest.main()
