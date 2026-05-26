import unittest
from datetime import datetime, time
from unittest.mock import Mock, patch

import scheduler


class SchedulerTests(unittest.TestCase):
    def test_next_daily_time_returns_today_for_future_time(self):
        now = datetime(2026, 5, 26, 2, 30)

        self.assertEqual(scheduler.next_daily_time(3, now=now), time(3, 0))

    def test_next_daily_time_rolls_past_time_to_tomorrow_time(self):
        now = datetime(2026, 5, 26, 3, 30)

        self.assertEqual(scheduler.next_daily_time(3, now=now), time(3, 0))

    def test_register_jobs_adds_expected_jobs(self):
        app = Mock()
        app.job_queue = Mock()

        with patch("scheduler.next_daily_time", side_effect=lambda hour, minute=0: time(hour, minute)):
            scheduler.register_jobs(app, Mock())

        self.assertEqual(app.job_queue.run_once.call_count, 2)
        self.assertEqual(app.job_queue.run_daily.call_count, 3)
        self.assertEqual(app.job_queue.run_repeating.call_count, 2)


if __name__ == "__main__":
    unittest.main()
