import unittest

import ai


class AiMemoryPendingTests(unittest.TestCase):
    def tearDown(self):
        ai.pending_memo_suggestions.clear()

    def test_extract_memo_tags(self):
        tags = ai._extract_memo_tags("Ок\n[MEMO: курс usd = 12700]")

        self.assertEqual(tags, [{"key": "курс usd", "value": "12700", "category": "общее"}])

    def test_queue_and_pop_pending_memo_suggestions(self):
        ai._queue_memo_tags("[MEMO: молоко = 80]", 42)

        self.assertEqual(len(ai.peek_pending_memo_suggestions(42)), 1)
        self.assertEqual(ai.pop_pending_memo_suggestions(42)[0]["key"], "молоко")
        self.assertEqual(ai.peek_pending_memo_suggestions(42), [])


if __name__ == "__main__":
    unittest.main()
