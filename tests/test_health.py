import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

import ai
import health


class HealthTests(unittest.IsolatedAsyncioTestCase):
    def test_count_errors_last_day_ignores_old_and_bad_dates(self):
        errors = [
            {"created_at": "2026-05-26 12:00:00"},
            {"created_at": "2026-05-25 11:59:59"},
            {"created_at": "bad"},
            {},
        ]

        count = health._count_errors_last_day(errors, now=datetime(2026, 5, 26, 12, 0, 0))

        self.assertEqual(count, 1)

    async def test_build_status_text_includes_core_health_fields(self):
        old_ready = ai.ai_ready.copy()
        ai.ai_ready.update({"groq": True, "tavily": False, "fallback": False})
        try:
            with (
                patch("health.db_get_reminder_counts", new=AsyncMock(return_value={"once": 2, "delivered": 1})),
                patch("health.db_count_lists", new=AsyncMock(return_value=3)),
                patch("health.db_count_users", new=AsyncMock(return_value=4)),
                patch("health.db_get_pending_reminders", new=AsyncMock(return_value=[
                    {"delivered": 0, "is_timer": 0},
                    {"delivered": 0, "is_timer": 1},
                    {"delivered": 1, "is_timer": 0},
                ])),
                patch("health.db_get_unread_errors_count", new=AsyncMock(return_value=5)),
                patch("health.db_get_recent_errors", new=AsyncMock(return_value=[
                    {"created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                ])),
                patch("health.latest_backup", return_value=None),
                patch("health.os.path.exists", return_value=False),
            ):
                text = await health.build_status_text("document")
        finally:
            ai.ai_ready.clear()
            ai.ai_ready.update(old_ready)

        self.assertIn("*Статус бота*", text)
        self.assertIn("Groq: *OK*", text)
        self.assertIn("Tavily: *недоступен*", text)
        self.assertIn("Напоминания: *1* активных, *1* таймеров", text)
        self.assertIn("Списки: *3*", text)
        self.assertIn("Пользователи: *4*", text)
        self.assertIn("непрочитанных: *5*", text)
        self.assertIn("Текущий процесс: `document`", text)


if __name__ == "__main__":
    unittest.main()
