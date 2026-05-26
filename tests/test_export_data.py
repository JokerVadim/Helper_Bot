import json
import zipfile
from io import BytesIO
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from export_data import build_export_payload, payload_to_csv_zip_bytes, payload_to_json_bytes


class ExportDataTests(IsolatedAsyncioTestCase):
    async def test_build_export_payload_collects_user_data(self):
        with (
            patch("export_data.db_get_lists_for_user", new=AsyncMock(return_value=[
                {"list_id": "own", "name": "Покупки", "created_by": 42},
            ])),
            patch("export_data.db_get_shared_lists", new=AsyncMock(return_value=[
                {"list_id": "shared", "name": "Общее", "created_by": 7},
            ])),
            patch("export_data.db_get_items", new=AsyncMock(side_effect=[
                [{"id": 1, "list_id": "own", "item": "молоко"}],
                [{"id": 2, "list_id": "shared", "item": "хлеб"}],
            ])),
            patch("export_data.db_get_pending_reminders", new=AsyncMock(return_value=[
                {"chat_id": 42, "rid": 1, "text": "моё"},
                {"chat_id": 7, "rid": 2, "text": "чужое"},
            ])),
            patch("export_data.db_get_notes", new=AsyncMock(return_value=[{"id": 1, "name": "n"}])),
            patch("export_data.db_get_documents", new=AsyncMock(return_value=[{"id": 1, "name": "doc"}])),
            patch("export_data.db_get_all_memories", new=AsyncMock(return_value=[{"id": 1, "key": "k"}])),
        ):
            payload = await build_export_payload(42)

        self.assertEqual(payload["metadata"]["user_id"], 42)
        self.assertEqual(len(payload["lists"]), 2)
        self.assertEqual(len(payload["list_items"]), 2)
        self.assertEqual(len(payload["reminders"]), 1)
        self.assertEqual(payload["reminders"][0]["text"], "моё")

    def test_json_export_is_utf8_json(self):
        data = payload_to_json_bytes({"metadata": {"user_id": 42}, "lists": [{"name": "Покупки"}]})

        parsed = json.loads(data.decode("utf-8"))

        self.assertEqual(parsed["lists"][0]["name"], "Покупки")

    def test_csv_export_is_zip_with_sections(self):
        payload = {
            "metadata": {"user_id": 42},
            "lists": [{"list_id": "x", "name": "Покупки"}],
            "list_items": [],
            "notes": [],
            "reminders": [],
            "documents": [],
            "memories": [],
        }

        data = payload_to_csv_zip_bytes(payload)

        with zipfile.ZipFile(BytesIO(data)) as archive:
            self.assertIn("metadata.json", archive.namelist())
            self.assertIn("lists.csv", archive.namelist())
            self.assertIn("Покупки", archive.read("lists.csv").decode("utf-8-sig"))
