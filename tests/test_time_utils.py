import unittest
from datetime import datetime

from utils.time_utils import next_repeat_time, parse_clock, parse_duration_seconds


class TimeUtilsTests(unittest.TestCase):
    def test_parse_duration_seconds_accepts_minutes_and_hour_minute(self):
        self.assertEqual(parse_duration_seconds("5"), 300)
        self.assertEqual(parse_duration_seconds("1h30m"), 5400)
        self.assertEqual(parse_duration_seconds("45m"), 2700)

    def test_parse_duration_seconds_rejects_empty_duration(self):
        self.assertIsNone(parse_duration_seconds(""))
        self.assertIsNone(parse_duration_seconds("0m"))
        self.assertIsNone(parse_duration_seconds("later"))

    def test_parse_clock_validates_clock_range(self):
        self.assertEqual(parse_clock("напомни в 09:05"), (9, 5))
        self.assertIsNone(parse_clock("24:00"))
        self.assertIsNone(parse_clock("12:99"))

    def test_next_repeat_time_weekly_uses_selected_weekdays(self):
        current = datetime(2026, 5, 25, 9, 0)  # Monday
        now = datetime(2026, 5, 26, 10, 0)     # Tuesday

        next_time = next_repeat_time(current, "weekly", now=now, repeat_days="2,4")

        self.assertEqual(next_time, datetime(2026, 5, 27, 9, 0))

    def test_next_repeat_time_minutes_catches_up_from_missed_time(self):
        current = datetime(2026, 5, 26, 8, 0)
        now = datetime(2026, 5, 26, 10, 5)

        next_time = next_repeat_time(current, "minutes", now=now, minutes=30)

        self.assertEqual(next_time, datetime(2026, 5, 26, 10, 30))


if __name__ == "__main__":
    unittest.main()
