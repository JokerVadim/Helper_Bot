"""User data export helpers."""
import csv
import io
import json
import zipfile
from datetime import datetime
from typing import Any

from db import (
    db_get_all_memories,
    db_get_documents,
    db_get_items,
    db_get_lists_for_user,
    db_get_notes,
    db_get_pending_reminders,
    db_get_shared_lists,
)

EXPORT_SECTIONS = ("lists", "list_items", "notes", "reminders", "documents", "memories")


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    return str(value)


def _clean_row(row: dict) -> dict:
    return {
        key: _json_default(value) if isinstance(value, datetime) else value
        for key, value in dict(row).items()
    }


async def build_export_payload(user_id: int) -> dict:
    own_lists = await db_get_lists_for_user(user_id)
    shared_lists = await db_get_shared_lists(user_id)

    lists = []
    list_items = []
    seen_list_ids = set()
    for source, rows in (("own", own_lists), ("shared", shared_lists)):
        for row in rows:
            list_id = row["list_id"]
            if list_id in seen_list_ids:
                continue
            seen_list_ids.add(list_id)
            list_row = _clean_row(row)
            list_row["source"] = source
            lists.append(list_row)
            for item in await db_get_items(list_id):
                item_row = _clean_row(item)
                item_row["list_source"] = source
                list_items.append(item_row)

    reminders = [
        _clean_row(row)
        for row in await db_get_pending_reminders()
        if int(row.get("chat_id", 0)) == int(user_id)
    ]

    return {
        "metadata": {
            "user_id": user_id,
            "exported_at": datetime.now().isoformat(sep=" ", timespec="seconds"),
            "format_version": 1,
        },
        "lists": lists,
        "list_items": list_items,
        "notes": [_clean_row(row) for row in await db_get_notes(user_id)],
        "reminders": reminders,
        "documents": [_clean_row(row) for row in await db_get_documents(user_id)],
        "memories": [_clean_row(row) for row in await db_get_all_memories(user_id)],
    }


def payload_to_json_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default).encode("utf-8")


def _csv_bytes(rows: list[dict]) -> bytes:
    output = io.StringIO(newline="")
    if rows:
        fieldnames = sorted({key for row in rows for key in row.keys()})
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    else:
        output.write("")
    return output.getvalue().encode("utf-8-sig")


def payload_to_csv_zip_bytes(payload: dict) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", payload_to_json_bytes({"metadata": payload["metadata"]}))
        for section in EXPORT_SECTIONS:
            archive.writestr(f"{section}.csv", _csv_bytes(payload.get(section, [])))
    return output.getvalue()


def export_filename(user_id: int, ext: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"bot_export_{user_id}_{stamp}.{ext}"
