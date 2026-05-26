import sqlite3
import unittest
from contextlib import contextmanager
from datetime import datetime

import db as db_module


class DatabaseCoreTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.old_conn = db_module.db._conn

        @contextmanager
        def test_conn():
            try:
                yield self.connection
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

        db_module.db._conn = test_conn
        db_module.db.init_db()

    def tearDown(self):
        db_module.db._conn = self.old_conn
        self.connection.close()

    def test_lists_store_items_and_detect_duplicates(self):
        db_module.db.create_list("groceries", "personal", "Покупки", 42)
        db_module.db.add_item("groceries", 42, "молоко", "🥛")

        items = db_module.db.get_items("groceries")

        self.assertTrue(db_module.db.list_exists("Покупки", 42))
        self.assertTrue(db_module.db.item_exists("groceries", "молоко"))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["item"], "молоко")
        self.assertEqual(items[0]["emoji"], "🥛")

    def test_documents_update_existing_record_by_name(self):
        first_id = db_module.db.save_document(
            42,
            "Паспорт",
            "file-old",
            "old.jpg",
            "photo",
            tags=["личное"],
        )
        second_id = db_module.db.save_document(
            42,
            "Паспорт",
            "file-new",
            "new.jpg",
            "photo",
            tags=["личное"],
        )

        docs = db_module.db.get_documents(42)

        self.assertEqual(first_id, second_id)
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["file_id"], "file-new")
        self.assertEqual(docs[0]["file_name"], "new.jpg")

    def test_memory_upsert_search_and_clear(self):
        db_module.db.save_memory(42, "Курс USD", "12600", "финансы")
        db_module.db.save_memory(42, "Курс USD", "12700", "финансы")
        db_module.db.save_memory(42, "Молоко", "80")

        memories = db_module.db.get_all_memories(42)
        found = db_module.db.search_memories(42, "usd")
        category_found = db_module.db.search_memories(42, "финансы")

        self.assertEqual(db_module.db.count_memories(42), 2)
        self.assertEqual(db_module.db.get_memory(42, "курс usd")["value"], "12700")
        self.assertEqual(len(found), 1)
        self.assertEqual(len(category_found), 1)
        self.assertEqual(memories[0]["user_id"], 42)

        db_module.db.clear_memories(42)
        self.assertEqual(db_module.db.count_memories(42), 0)

    def test_memory_update_and_category_by_id(self):
        db_module.db.save_memory(42, "Молоко", "80")
        memory_id = db_module.db.get_all_memories(42)[0]["id"]

        self.assertTrue(db_module.db.update_memory_by_id(42, memory_id, "Молоко цена", "90"))
        self.assertTrue(db_module.db.set_memory_category(42, memory_id, "покупки"))

        memory = db_module.db.get_memory(42, "молоко цена")
        self.assertEqual(memory["value"], "90")
        self.assertEqual(memory["category"], "покупки")
        self.assertFalse(db_module.db.update_memory_by_id(42, 999, "x", "y"))

    def test_duplicate_reminder_detection(self):
        fire_at = datetime(2026, 5, 26, 15, 30)
        db_module.db.save_reminder(42, 1, "чай", fire_at, False, "none")

        self.assertTrue(db_module.db.has_duplicate_reminder(42, "чай", fire_at, "none"))
        self.assertFalse(db_module.db.has_duplicate_reminder(42, "чай", fire_at, "daily"))
        self.assertFalse(db_module.db.has_duplicate_reminder(42, "кофе", fire_at, "none"))


if __name__ == "__main__":
    unittest.main()
