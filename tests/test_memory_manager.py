import unittest

from memory_manager import (
    format_memory_rows,
    format_pending_memories,
    parse_memory_category,
    parse_memory_update,
)


class MemoryManagerTests(unittest.TestCase):
    def test_format_memory_rows_includes_ids_and_categories(self):
        text = format_memory_rows([
            {"id": 7, "category": "финансы", "key": "курс", "value": "12700"}
        ])

        self.assertIn("#7", text)
        self.assertIn("финансы", text)
        self.assertIn("курс", text)

    def test_parse_memory_update(self):
        parsed = parse_memory_update("память редактировать 7 курс = 12700")

        self.assertEqual(parsed, (7, "курс", "12700"))
        self.assertIsNone(parse_memory_update("память редактировать семь курс = 12700"))

    def test_format_pending_memories(self):
        text = format_pending_memories([
            {"category": "общее", "key": "молоко", "value": "80"}
        ])

        self.assertIn("память подтвердить", text)
        self.assertIn("молоко", text)

    def test_parse_memory_category(self):
        parsed = parse_memory_category("память категория 7 финансы")

        self.assertEqual(parsed, (7, "финансы"))
        self.assertIsNone(parse_memory_category("память категория"))


if __name__ == "__main__":
    unittest.main()
