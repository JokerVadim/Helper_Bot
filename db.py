"""Database module for SQLite operations.

Рефакторинг: функции сгруппированы в класс Database по доменам.
Все старые db_* функции сохранены для обратной совместимости.
"""
import json
import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime
from math import radians, sin, cos, sqrt, atan2
from typing import Any

from utils.tags import TagManager

DB_PATH = "bot.db"
logger = logging.getLogger(__name__)


class Database:
    """Central database class with domain-grouped methods."""

    # ─── Core ─────────────────────────────────────────────────────────────────

    @staticmethod
    @contextmanager
    def _conn():
        """Контекстный менеджер соединения с БД.

        Гарантирует commit при успехе, rollback при исключении и
        явное закрытие соединения в любом случае.

        Использование:
            with self._conn() as con:
                con.execute(...)
        """
        con = sqlite3.connect(DB_PATH)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def init_db(self):
        with self._conn() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id   INTEGER PRIMARY KEY,
                    name      TEXT
                );
                CREATE TABLE IF NOT EXISTS lists (
                    list_id    TEXT PRIMARY KEY,
                    type       TEXT,
                    name       TEXT,
                    created_by INTEGER,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS list_items (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    list_id    TEXT,
                    user_id    INTEGER,
                    item       TEXT,
                    emoji      TEXT DEFAULT '📌',
                    created_at TEXT,
                    sort_order INTEGER,
                    checked    INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS summa (
                    user_id    INTEGER PRIMARY KEY,
                    value      REAL
                );
                CREATE TABLE IF NOT EXISTS reminders (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id    INTEGER,
                    rid        INTEGER,
                    text       TEXT,
                    fire_at    TEXT,
                    is_timer   INTEGER DEFAULT 0,
                    repeat_type TEXT DEFAULT 'none',
                    minutes    INTEGER DEFAULT 0,
                    created_at TEXT,
                    delivered INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS list_shares (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    list_id    TEXT,
                    user_id    INTEGER,
                    permission TEXT DEFAULT 'read',
                    created_at TEXT,
                    FOREIGN KEY (list_id) REFERENCES lists(list_id) ON DELETE CASCADE,
                    UNIQUE(list_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS cards (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    number     TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    content    TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    file_id    TEXT,
                    file_name  TEXT,
                    file_type  TEXT DEFAULT 'document',
                    source_chat_id INTEGER,
                    source_message_id INTEGER,
                    created_at TEXT,
                    refreshed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS document_tags (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    normalized_name TEXT,
                    created_at TEXT,
                    UNIQUE(user_id, normalized_name)
                );
                CREATE TABLE IF NOT EXISTS document_tag_links (
                    document_id INTEGER,
                    tag_id      INTEGER,
                    PRIMARY KEY (document_id, tag_id),
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES document_tags(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS document_photos (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id INTEGER,
                    file_id    TEXT,
                    file_type  TEXT DEFAULT 'photo',
                    sort_order INTEGER DEFAULT 0,
                    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS item_tags (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    normalized_name TEXT,
                    created_at TEXT,
                    UNIQUE(user_id, normalized_name)
                );
                CREATE TABLE IF NOT EXISTS item_tag_links (
                    item_id INTEGER,
                    tag_id  INTEGER,
                    PRIMARY KEY (item_id, tag_id),
                    FOREIGN KEY (item_id) REFERENCES list_items(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES item_tags(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS note_tags (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    normalized_name TEXT,
                    created_at TEXT,
                    UNIQUE(user_id, normalized_name)
                );
                CREATE TABLE IF NOT EXISTS note_tag_links (
                    note_id INTEGER,
                    tag_id  INTEGER,
                    PRIMARY KEY (note_id, tag_id),
                    FOREIGN KEY (note_id) REFERENCES notes(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES note_tags(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS reminder_tags (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    normalized_name TEXT,
                    created_at TEXT,
                    UNIQUE(user_id, normalized_name)
                );
                CREATE TABLE IF NOT EXISTS reminder_tag_links (
                    reminder_id INTEGER,
                    tag_id      INTEGER,
                    PRIMARY KEY (reminder_id, tag_id),
                    FOREIGN KEY (reminder_id) REFERENCES reminders(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES reminder_tags(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS location_tags (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    normalized_name TEXT,
                    created_at TEXT,
                    UNIQUE(user_id, normalized_name)
                );
                CREATE TABLE IF NOT EXISTS location_tag_links (
                    location_id INTEGER,
                    tag_id      INTEGER,
                    PRIMARY KEY (location_id, tag_id),
                    FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES location_tags(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS locations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    latitude   REAL,
                    longitude  REAL,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS user_pins (
                    user_id  INTEGER PRIMARY KEY,
                    pin_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS birthdays (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    birth_date TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS birthday_settings (
                    user_id      INTEGER PRIMARY KEY,
                    notify_time  TEXT DEFAULT '10:00',
                    notify_advance INTEGER DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS user_memories (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    key        TEXT,
                    value      TEXT,
                    category   TEXT DEFAULT 'общее',
                    created_at TEXT,
                    updated_at TEXT,
                    UNIQUE(user_id, key)
                );
                CREATE TABLE IF NOT EXISTS access (
                    user_id    INTEGER PRIMARY KEY,
                    allowed_by INTEGER,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS summary_config (
                    user_id    INTEGER PRIMARY KEY,
                    sections   TEXT,
                    created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS weather_locations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    latitude   REAL,
                    longitude  REAL,
                    created_at TEXT,
                    is_primary INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS widget_settings (
                    user_id    INTEGER PRIMARY KEY,
                    time       TEXT DEFAULT '08:00',
                    last_sent_date TEXT
                );
                CREATE TABLE IF NOT EXISTS bot_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS error_logs (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    level      TEXT DEFAULT 'ERROR',
                    message    TEXT,
                    traceback  TEXT,
                    created_at TEXT,
                    is_read    INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS supply_tags (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    normalized_name TEXT,
                    created_at TEXT,
                    UNIQUE(user_id, normalized_name)
                );
                CREATE TABLE IF NOT EXISTS supply_tag_links (
                    supply_id INTEGER,
                    tag_id    INTEGER,
                    PRIMARY KEY (supply_id, tag_id),
                    FOREIGN KEY (supply_id) REFERENCES supplies(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES supply_tags(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS supplies (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER,
                    name       TEXT,
                    quantity   INTEGER DEFAULT 0,
                    min_quantity INTEGER DEFAULT 0,
                    photo_file_id TEXT,
                    photo_file_type TEXT DEFAULT 'photo',
                    sort_order INTEGER DEFAULT 0,
                    created_at TEXT
                );
            """)
            self._ensure_column(con, "reminders", "repeat_type", "TEXT DEFAULT 'none'")
            self._ensure_column(con, "reminders", "repeat_days", "TEXT DEFAULT ''")
            self._ensure_column(con, "reminders", "minutes", "INTEGER DEFAULT 0")
            self._ensure_column(con, "reminders", "created_at", "TEXT")
            self._ensure_column(con, "reminders", "delivered", "INTEGER DEFAULT 0")
            self._ensure_column(con, "weather_locations", "is_primary", "INTEGER DEFAULT 0")
            self._ensure_column(con, "list_items", "emoji", "TEXT DEFAULT '📌'")
            self._ensure_column(con, "list_items", "sort_order", "INTEGER")
            self._ensure_column(con, "list_items", "checked", "INTEGER DEFAULT 0")
            self._ensure_column(con, "documents", "source_chat_id", "INTEGER")
            self._ensure_column(con, "documents", "source_message_id", "INTEGER")
            self._ensure_column(con, "documents", "file_type", "TEXT DEFAULT 'document'")
            self._ensure_column(con, "documents", "sort_order", "INTEGER DEFAULT 0")
            self._ensure_column(con, "locations", "sort_order", "INTEGER DEFAULT 0")
            self._ensure_column(con, "supplies", "min_quantity", "INTEGER DEFAULT 0")
            self._ensure_column(con, "supplies", "normal_quantity", "INTEGER DEFAULT 0")
            self._ensure_column(con, "user_memories", "category", "TEXT DEFAULT 'общее'")
            self._ensure_default_document_tags(con)
            self._ensure_default_note_tags(con)
            self._ensure_default_reminder_tags(con)
            self._ensure_default_location_tags(con)
            self._ensure_default_supply_tags(con)
        logger.info("✅ SQLite БД инициализирована")

    # ─── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _ensure_column(con: sqlite3.Connection, table: str, column: str, definition: str):
        columns = [row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in columns:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _normalize_document_tag(name: str) -> str:
        from utils.tags import normalize_tag_name
        return normalize_tag_name(name)

    @staticmethod
    def _get_or_create_document_tag(con: sqlite3.Connection, user_id: int, name: str) -> int:
        return Database.tag_documents._get_or_create_tag(con, user_id, name)

    @staticmethod
    def _ensure_document_has_tag(con: sqlite3.Connection, user_id: int, doc_id: int):
        Database.tag_documents._ensure_has_tag(con, user_id, doc_id)

    @staticmethod
    def _ensure_default_document_tags(con: sqlite3.Connection):
        Database.tag_documents._ensure_default_tags(con, "documents")

    @staticmethod
    def _ensure_default_note_tags(con: sqlite3.Connection):
        Database.tag_notes._ensure_default_tags(con, "notes")

    @staticmethod
    def _ensure_default_reminder_tags(con: sqlite3.Connection):
        Database.tag_reminders._ensure_default_tags(con, "reminders")

    @staticmethod
    def _ensure_default_location_tags(con: sqlite3.Connection):
        Database.tag_locations._ensure_default_tags(con, "locations")

    @staticmethod
    def _ensure_default_supply_tags(con: sqlite3.Connection):
        Database.tag_supplies._ensure_default_tags(con, "supplies")

    @staticmethod
    def _haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371000
        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))
        return R * c

    # ─── Tag Managers ─────────────────────────────────────────────────────────

    tag_documents = TagManager("document_tags", "document_tag_links", "document_id")
    tag_items = TagManager("item_tags", "item_tag_links", "item_id")
    tag_notes = TagManager("note_tags", "note_tag_links", "note_id")
    tag_reminders = TagManager("reminder_tags", "reminder_tag_links", "reminder_id", user_fk_column="chat_id")
    tag_locations = TagManager("location_tags", "location_tag_links", "location_id")
    tag_supplies = TagManager("supply_tags", "supply_tag_links", "supply_id")

    # ─── Users ────────────────────────────────────────────────────────────────

    def get_user(self, user_id: int) -> dict | None:
        with self._conn() as con:
            row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
            return dict(row) if row else None

    def upsert_user(self, user_id: int, name: str):
        with self._conn() as con:
            con.execute(
                "INSERT INTO users(user_id, name) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name",
                (user_id, name)
            )

    def count_users(self) -> int:
        with self._conn() as con:
            row = con.execute("SELECT COUNT(*) AS count FROM users").fetchone()
            return int(row["count"])

    def get_all_users(self) -> list[dict]:
        """Получить список всех пользователей."""
        with self._conn() as con:
            rows = con.execute("SELECT * FROM users ORDER BY user_id").fetchall()
            return [dict(r) for r in rows]

    # ─── Lists ────────────────────────────────────────────────────────────────

    def create_list(self, list_id: str, ltype: str, name: str, created_by: int):
        with self._conn() as con:
            con.execute(
                "INSERT INTO lists(list_id, type, name, created_by, created_at) VALUES(?,?,?,?,?)",
                (list_id, ltype, name, created_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
        logger.info(f"🧾 LIST SAVED: id={list_id} | type={ltype} | name={name}")

    def get_lists_for_user(self, user_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM lists WHERE created_by=? ORDER BY created_at", (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_list(self, list_id: str) -> dict | None:
        with self._conn() as con:
            row = con.execute("SELECT * FROM lists WHERE list_id=?", (list_id,)).fetchone()
            return dict(row) if row else None

    def delete_list(self, list_id: str):
        with self._conn() as con:
            con.execute("DELETE FROM lists WHERE list_id=?", (list_id,))
            con.execute("DELETE FROM list_items WHERE list_id=?", (list_id,))
            # Clean up orphaned item_tags (no remaining links to any items)
            con.execute("""
                DELETE FROM item_tags WHERE id NOT IN (
                    SELECT DISTINCT tag_id FROM item_tag_links
                )
            """)

    def count_lists(self) -> int:
        with self._conn() as con:
            row = con.execute("SELECT COUNT(*) AS count FROM lists").fetchone()
            return int(row["count"])

    def list_exists(self, name: str, created_by: int) -> bool:
        with self._conn() as con:
            row = con.execute(
                "SELECT 1 FROM lists WHERE name=? AND created_by=? LIMIT 1", (name, created_by)
            ).fetchone()
            return row is not None

    # ─── List Items ───────────────────────────────────────────────────────────

    def add_item(self, list_id: str, user_id: int, item: str, emoji: str = "📌"):
        with self._conn() as con:
            con.execute(
                "INSERT INTO list_items(list_id, user_id, item, emoji, created_at) VALUES(?,?,?,?,?)",
                (list_id, user_id, item, emoji, datetime.now().strftime("%Y-%m-%d %H:%M"))
            )

    def item_exists(self, list_id: str, item: str) -> bool:
        with self._conn() as con:
            row = con.execute(
                "SELECT 1 FROM list_items WHERE list_id=? AND item=? LIMIT 1", (list_id, item)
            ).fetchone()
            return row is not None

    def get_items(self, list_id: str) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM list_items WHERE list_id=? ORDER BY COALESCE(sort_order, id)", (list_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_item_by_index(self, list_id: str, index: int):
        with self._conn() as con:
            rows = con.execute(
                "SELECT id FROM list_items WHERE list_id=? ORDER BY COALESCE(sort_order, id)", (list_id,)
            ).fetchall()
            if index >= len(rows):
                return
            row_id = rows[index]["id"]
            con.execute("DELETE FROM list_items WHERE id=?", (row_id,))

    def toggle_item_checked(self, list_id: str, index: int) -> int | None:
        with self._conn() as con:
            rows = con.execute(
                "SELECT id, checked FROM list_items WHERE list_id=? ORDER BY COALESCE(sort_order, id)", (list_id,)
            ).fetchall()
            if index >= len(rows):
                return None
            row = rows[index]
            new_checked = 1 if row["checked"] == 0 else 0
            con.execute("UPDATE list_items SET checked=? WHERE id=?", (new_checked, row["id"]))
            return new_checked

    def toggle_item_checked_by_id(self, list_id: str, item_id: int) -> int | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT id, checked FROM list_items WHERE id=? AND list_id=?", (item_id, list_id)
            ).fetchone()
            if not row:
                return None
            new_checked = 1 if row["checked"] == 0 else 0
            con.execute("UPDATE list_items SET checked=? WHERE id=?", (new_checked, item_id))
            return new_checked

    def get_item_by_index(self, list_id: str, index: int) -> dict | None:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM list_items WHERE list_id=? ORDER BY COALESCE(sort_order, id)", (list_id,)
            ).fetchall()
            if index >= len(rows):
                return None
            return dict(rows[index])

    def update_item_sort_order(self, list_id: str, item_id: int, new_order: int):
        with self._conn() as con:
            con.execute("UPDATE list_items SET sort_order=? WHERE id=? AND list_id=?", (new_order, item_id, list_id))

    # ─── Emoji Categories ────────────────────────────────────────────────────

    EMOJI_CATEGORIES = {
        "🍎": 1, "🍐": 1, "🍊": 1, "🍋": 1, "🍌": 1, "🍉": 1, "🍇": 1, "🍓": 1, "🫐": 1, "🍈": 1,
        "🍒": 1, "🍑": 1, "🥭": 1, "🍍": 1, "🥥": 1, "🥝": 1, "🍅": 1, "🥑": 1, "🍆": 1, "🥕": 1,
        "🌽": 1, "🌶️": 1, "🥒": 1, "🥬": 1, "🥦": 1, "🧄": 1, "🧅": 1, "🥔": 1, "🍠": 1, "🥐": 1,
        "🥯": 1, "🍞": 1, "🥖": 1, "🥨": 1, "🧀": 1, "🥚": 1, "🍳": 1, "🧈": 1, "🥞": 1, "🧇": 1,
        "🥓": 1, "🥩": 1, "🍗": 1, "🍖": 1, "🌭": 1, "🍔": 1, "🍟": 1, "🍕": 1, "🥪": 1, "🥙": 1,
        "🧆": 1, "🌮": 1, "🌯": 1, "🫔": 1, "🥗": 1, "🥘": 1, "🫕": 1, "🍝": 1, "🍜": 1, "🍲": 1,
        "🍛": 1, "🍣": 1, "🍱": 1, "🥟": 1, "🦪": 1, "🍤": 1, "🍙": 1, "🍚": 1, "🍘": 1, "🍥": 1,
        "🥠": 1, "🥮": 1, "🍢": 1, "🍡": 1, "🍧": 1, "🍨": 1, "🍦": 1, "🥧": 1, "🧁": 1, "🍰": 1,
        "🎂": 1, "🍮": 1, "🍭": 1, "🍬": 1, "🍫": 1, "🍿": 1, "🍩": 1, "🍪": 1, "🥜": 1, "🌰": 1,
        "🍯": 1, "🥛": 1, "🍼": 1, "☕": 1, "🍵": 1, "🧃": 1, "🥤": 1, "🧋": 1, "🍶": 1, "🍺": 1,
        "🍻": 1, "🥂": 1, "🍷": 1, "🥃": 1, "🍸": 1, "🍹": 1, "🧉": 1, "🍾": 1, "🧊": 1,
        "👕": 2, "👖": 2, "🧥": 2, "👗": 2, "👘": 2, "🩴": 2, "🩱": 2, "🩳": 2, "👙": 2, "👚": 2,
        "👛": 2, "👜": 2, "👝": 2, "🎒": 2, "👞": 2, "👟": 2, "🥾": 2, "🥿": 2, "👠": 2, "👡": 2,
        "👢": 2, "👑": 2, "👒": 2, "🎩": 2, "🧢": 2, "💄": 2, "💅": 2, "💍": 2, "💎": 2,
        "🏠": 3, "🏡": 3, "🛏": 3, "🛋": 3, "🪑": 3, "🚪": 3, "🛁": 3, "🚽": 3, "🧻": 3, "🧼": 3,
        "🧽": 3, "🪣": 3, "🧴": 3, "🔑": 3, "🔒": 3, "🔓": 3, "🔨": 3, "🪚": 3, "🔧": 3, "🔩": 3,
        "⚙️": 3, "🪛": 3, "🔗": 3, "🧰": 3, "🧲": 3,
        "🚗": 4, "🚕": 4, "🚙": 4, "🚌": 4, "🚎": 4, "🏎": 4, "🚓": 4, "🚑": 4, "🚒": 4, "🚐": 4,
        "🚚": 4, "🚛": 4, "🚜": 4, "🏍": 4, "🚲": 4, "🛴": 4, "🚨": 4, "🚦": 4, "🚧": 4, "⚓": 4,
        "⛵": 4, "🚤": 4, "🛳": 4, "✈️": 4, "🚁": 4, "🚂": 4, "🚃": 4, "🚄": 4, "🚅": 4, "🚇": 4,
        "🚉": 4, "🚊": 4,
        "📱": 5, "📲": 5, "💻": 5, "🖥": 5, "🖨": 5, "⌨️": 5, "🖱": 5, "💽": 5, "💾": 5, "💿": 5,
        "📀": 5, "📷": 5, "📸": 5, "📹": 5, "🎥": 5, "📞": 5, "☎️": 5, "📺": 5, "📻": 5, "🎙": 5,
        "🧭": 5, "⏱": 5, "⏲": 5, "⏰": 5, "🕰": 5, "⌛": 5, "⏳": 5, "📡": 5, "🔋": 5, "🔌": 5,
        "🔦": 5, "🕯": 5, "🧯": 5, "🛒": 5,
        "💊": 6, "💉": 6, "🩸": 6, "🩹": 6, "🩺": 6, "🏥": 6, "🏩": 6, "🧬": 6, "🦠": 6,
        "⚽": 7, "🏀": 7, "🏈": 7, "⚾": 7, "🥎": 7, "🎾": 7, "🏐": 7, "🏉": 7, "🥏": 7, "🎱": 7,
        "🏓": 7, "🏸": 7, "🏒": 7, "🏑": 7, "🥍": 7, "🏏": 7, "⛳": 7, "🏹": 7, "🎣": 7, "🤿": 7,
        "🥊": 7, "🥋": 7, "🎽": 7, "🛹": 7, "🛼": 7, "⛸": 7, "🥌": 7, "🎿": 7, "🏂": 7, "🪂": 7,
        "🏋️": 7, "🤼": 7, "🤸": 7, "⛹️": 7, "🤺": 7, "🤾": 7, "🏌️": 7, "🏇": 7, "🧘": 7, "🏄": 7,
        "🏊": 7, "🤽": 7, "🚣": 7, "🧗": 7,
        "💼": 8, "📁": 8, "📂": 8, "🗂": 8, "📅": 8, "📆": 8, "🗒": 8, "🗓": 8, "📇": 8, "📈": 8,
        "📉": 8, "📊": 8, "📋": 8, "📍": 8, "📎": 8, "🖇": 8, "📏": 8, "📐": 8, "✂️": 8,
        "🗃": 8, "🗳": 8, "💰": 8, "💵": 8, "💴": 8, "💶": 8, "💷": 8, "💸": 8, "💳": 8, "💹": 8,
        "📧": 8, "📨": 8, "📩": 8, "📤": 8, "📥": 8, "📦": 8, "📫": 8, "📪": 8, "📬": 8, "📭": 8,
        "📮": 8, "📯": 8, "📜": 8, "📃": 8, "📄": 8, "📑": 8, "🧾": 8, "📰": 8, "📚": 8,
        "🌸": 9, "💮": 9, "🌹": 9, "🥀": 9, "🌺": 9, "🌻": 9, "🌼": 9, "🌷": 9, "🌱": 9, "🌿": 9,
        "☘️": 9, "🍀": 9, "🍃": 9, "🍂": 9, "🍁": 9, "🌾": 9, "🌵": 9, "🌴": 9, "🌲": 9, "🌳": 9,
        "☀️": 9, "🌤️": 9, "⛅": 9, "🌥": 9, "🌦": 9, "🌧": 9, "⛈": 9, "🌩": 9, "🌨": 9, "❄️": 9,
        "☁️": 9, "🌋": 9, "🗻": 9, "🏔": 9,
        "🐶": 10, "🐱": 10, "🐭": 10, "🐹": 10, "🐰": 10, "🦊": 10, "🐻": 10, "🐼": 10, "🐨": 10,
        "🐯": 10, "🦁": 10, "🐮": 10, "🐷": 10, "🐸": 10, "🐵": 10, "🐔": 10, "🐧": 10, "🐦": 10,
        "🦆": 10, "🦅": 10, "🦉": 10, "🦇": 10, "🐺": 10, "🐴": 10, "🦄": 10, "🐝": 10, "🦋": 10,
        "🐌": 10, "🐞": 10, "🐢": 10, "🐍": 10, "🦎": 10, "🐙": 10, "🦑": 10, "🦐": 10, "🦀": 10,
        "🐡": 10, "🐠": 10, "🐟": 10, "🐬": 10, "🐳": 10, "🐋": 10, "🦈": 10, "🐊": 10, "🐆": 10,
        "🐅": 10, "🐘": 10, "🦏": 10, "🐪": 10, "🐫": 10, "🦒": 10, "🦍": 10, "🐑": 10, "🐐": 10,
        "🐎": 10, "🐕": 10, "🐈": 10,
        "📌": 99, "✅": 99, "❌": 99, "⭐": 99, "🔔": 99, "💡": 99,
    }
    DEFAULT_CATEGORY = 99

    @staticmethod
    def _get_emoji_category(emoji: str) -> int:
        return Database.EMOJI_CATEGORIES.get(emoji, Database.DEFAULT_CATEGORY)

    def sort_items_by_emoji(self, list_id: str) -> int:
        with self._conn() as con:
            items = con.execute(
                "SELECT id, emoji FROM list_items WHERE list_id=?", (list_id,)
            ).fetchall()
            if not items:
                return 0
            sorted_items = sorted(items, key=lambda x: (self._get_emoji_category(x["emoji"] or "📌"), x["id"]))
            for order, item in enumerate(sorted_items):
                con.execute("UPDATE list_items SET sort_order=? WHERE id=?", (order, item["id"]))
            return len(sorted_items)

    # ─── Summa ────────────────────────────────────────────────────────────────

    def get_summa(self, user_id: int) -> float | None:
        with self._conn() as con:
            row = con.execute("SELECT value FROM summa WHERE user_id=?", (user_id,)).fetchone()
            return row["value"] if row else None

    def set_summa(self, user_id: int, value: float):
        with self._conn() as con:
            con.execute(
                "INSERT INTO summa(user_id, value) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET value=excluded.value",
                (user_id, value)
            )

    # ─── Reminders ────────────────────────────────────────────────────────────

    def save_reminder(self, chat_id: int, rid: int, text: str, fire_at: datetime,
                      is_timer: bool = False, repeat_type: str = "none", minutes: int = 0, repeat_days: str = ""):
        with self._conn() as con:
            con.execute(
                "INSERT INTO reminders(chat_id, rid, text, fire_at, is_timer, repeat_type, repeat_days, minutes, created_at, delivered) VALUES(?,?,?,?,?,?,?,?,?,0)",
                (chat_id, rid, text, fire_at.strftime("%Y-%m-%d %H:%M:%S"),
                 int(is_timer), repeat_type, repeat_days, minutes, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )

    def delete_reminder(self, chat_id: int, rid: int):
        with self._conn() as con:
            row = con.execute("SELECT id FROM reminders WHERE chat_id=? AND rid=?", (chat_id, rid)).fetchone()
            if row:
                reminder_pk = int(row["id"])
                con.execute("DELETE FROM reminder_tag_links WHERE reminder_id=?", (reminder_pk,))
            con.execute("DELETE FROM reminders WHERE chat_id=? AND rid=?", (chat_id, rid))
            con.execute("""
                DELETE FROM reminder_tags WHERE id NOT IN (
                    SELECT DISTINCT tag_id FROM reminder_tag_links
                )
            """)

    def has_duplicate_reminder(self, chat_id: int, text: str, fire_at: datetime, repeat_type: str | None = None) -> bool:
        with self._conn() as con:
            sql = "SELECT 1 FROM reminders WHERE chat_id=? AND text=? AND fire_at=? AND delivered=0"
            params: list = [chat_id, text, fire_at.strftime("%Y-%m-%d %H:%M:%S")]
            if repeat_type is not None:
                sql += " AND repeat_type=?"
                params.append(repeat_type)
            row = con.execute(sql + " LIMIT 1", params).fetchone()
            return row is not None

    def get_reminder(self, chat_id: int, rid: int) -> dict | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT * FROM reminders WHERE chat_id=? AND rid=?", (chat_id, rid)
            ).fetchone()
            return dict(row) if row else None

    def update_reminder(self, chat_id: int, rid: int, **fields: Any):
        allowed = {"text", "fire_at", "is_timer", "repeat_type", "repeat_days", "delivered", "minutes"}
        updates = []
        values = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            updates.append(f"{key}=?")
            if key == "fire_at" and isinstance(value, datetime):
                value = value.strftime("%Y-%m-%d %H:%M:%S")
            elif key in ("is_timer", "delivered"):
                value = int(value)
            values.append(value)
        if not updates:
            return
        values.extend([chat_id, rid])
        with self._conn() as con:
            con.execute(f"UPDATE reminders SET {', '.join(updates)} WHERE chat_id=? AND rid=?", values)

    def get_pending_reminders(self) -> list[dict]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM reminders ORDER BY fire_at").fetchall()
            return [dict(r) for r in rows]

    def get_reminder_counts(self) -> dict:
        with self._conn() as con:
            row = con.execute("""
                SELECT
                    SUM(CASE WHEN is_timer=1 THEN 1 ELSE 0 END) AS timers,
                    SUM(CASE WHEN is_timer=0 AND COALESCE(repeat_type,'none')='none' AND COALESCE(delivered,0)=0 THEN 1 ELSE 0 END) AS once,
                    SUM(CASE WHEN is_timer=0 AND COALESCE(delivered,0)=1 THEN 1 ELSE 0 END) AS delivered,
                    SUM(CASE WHEN is_timer=0 AND repeat_type='daily' THEN 1 ELSE 0 END) AS daily,
                    SUM(CASE WHEN is_timer=0 AND repeat_type='monthly' THEN 1 ELSE 0 END) AS monthly,
                    SUM(CASE WHEN is_timer=0 AND repeat_type='yearly' THEN 1 ELSE 0 END) AS yearly,
                    SUM(CASE WHEN is_timer=0 AND repeat_type='weekly' THEN 1 ELSE 0 END) AS weekly
                FROM reminders
            """).fetchone()
            return {key: int(row[key] or 0) for key in row.keys()}

    # ─── List Sharing ─────────────────────────────────────────────────────────

    def share_list(self, list_id: str, user_id: int, permission: str = "write"):
        with self._conn() as con:
            con.execute(
                "INSERT INTO list_shares(list_id, user_id, permission, created_at) VALUES(?,?,?,?) "
                "ON CONFLICT(list_id, user_id) DO UPDATE SET permission=excluded.permission",
                (list_id, user_id, permission, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )

    def unshare_list(self, list_id: str, user_id: int):
        with self._conn() as con:
            con.execute("DELETE FROM list_shares WHERE list_id=? AND user_id=?", (list_id, user_id))

    def get_shared_lists(self, user_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute("""
                SELECT l.*, ls.permission, ls.user_id as shared_by
                FROM lists l JOIN list_shares ls ON l.list_id = ls.list_id
                WHERE ls.user_id=? ORDER BY l.created_at DESC
            """, (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_list_members(self, list_id: str) -> list[dict]:
        with self._conn() as con:
            rows = con.execute("""
                SELECT ls.user_id, ls.permission, ls.created_at, u.name
                FROM list_shares ls LEFT JOIN users u ON ls.user_id = u.user_id
                WHERE ls.list_id=?
            """, (list_id,)).fetchall()
            return [dict(r) for r in rows]

    def is_list_member(self, list_id: str, user_id: int) -> bool:
        with self._conn() as con:
            owner = con.execute("SELECT 1 FROM lists WHERE list_id=? AND created_by=?", (list_id, user_id)).fetchone()
            if owner:
                return True
            return con.execute("SELECT 1 FROM list_shares WHERE list_id=? AND user_id=?", (list_id, user_id)).fetchone() is not None

    def get_list_permission(self, list_id: str, user_id: int) -> str | None:
        with self._conn() as con:
            if con.execute("SELECT 1 FROM lists WHERE list_id=? AND created_by=?", (list_id, user_id)).fetchone():
                return "owner"
            row = con.execute("SELECT permission FROM list_shares WHERE list_id=? AND user_id=?", (list_id, user_id)).fetchone()
            return row["permission"] if row else None

    # ─── Cards ────────────────────────────────────────────────────────────────

    def save_card(self, user_id: int, name: str, number: str):
        with self._conn() as con:
            con.execute(
                "INSERT INTO cards(user_id, name, number, created_at) VALUES(?,?,?,?)",
                (user_id, name, number, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )

    def get_cards(self, user_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM cards WHERE user_id=? ORDER BY created_at", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def delete_card(self, user_id: int, card_id: int):
        with self._conn() as con:
            con.execute("DELETE FROM cards WHERE id=? AND user_id=?", (card_id, user_id))

    def update_card(self, user_id: int, card_id: int, name: str, number: str):
        with self._conn() as con:
            con.execute("UPDATE cards SET name=?, number=? WHERE id=? AND user_id=?", (name, number, card_id, user_id))

    def card_exists(self, user_id: int, name: str) -> bool:
        with self._conn() as con:
            return con.execute(
                "SELECT 1 FROM cards WHERE user_id=? AND name=? LIMIT 1", (user_id, name)
            ).fetchone() is not None

    # ─── Notes ────────────────────────────────────────────────────────────────

    def save_note(self, user_id: int, name: str, content: str):
        with self._conn() as con:
            con.execute(
                "INSERT INTO notes(user_id, name, content, created_at) VALUES(?,?,?,?)",
                (user_id, name, content, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )

    def get_notes(self, user_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute("SELECT * FROM notes WHERE user_id=? ORDER BY created_at", (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def delete_note(self, user_id: int, note_id: int):
        with self._conn() as con:
            con.execute("DELETE FROM note_tag_links WHERE note_id=?", (note_id,))
            con.execute("DELETE FROM notes WHERE id=? AND user_id=?", (note_id, user_id))
            con.execute("""
                DELETE FROM note_tags WHERE id NOT IN (
                    SELECT DISTINCT tag_id FROM note_tag_links
                )
            """)

    def update_note(self, user_id: int, note_id: int, name: str, content: str):
        with self._conn() as con:
            con.execute("UPDATE notes SET name=?, content=? WHERE id=? AND user_id=?", (name, content, note_id, user_id))

    def note_exists(self, user_id: int, name: str) -> bool:
        with self._conn() as con:
            return con.execute(
                "SELECT 1 FROM notes WHERE user_id=? AND name=? LIMIT 1", (user_id, name)
            ).fetchone() is not None

    # ─── Documents ────────────────────────────────────────────────────────────

    def save_document(self, user_id: int, name: str, file_id: str, file_name: str,
                      file_type: str = "document", source_chat_id: int = None,
                      source_message_id: int = None, tags: list[str] | None = None) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as con:
            existing = con.execute(
                "SELECT id FROM documents WHERE user_id=? AND name=?", (user_id, name)
            ).fetchone()
            if existing:
                doc_id = int(existing["id"])
                con.execute(
                    "UPDATE documents SET file_id=?, file_name=?, file_type=?, source_chat_id=?, source_message_id=?, refreshed_at=? WHERE user_id=? AND name=?",
                    (file_id, file_name, file_type, source_chat_id, source_message_id, now, user_id, name)
                )
            else:
                max_order = con.execute(
                    "SELECT COALESCE(MAX(sort_order), 0) FROM documents WHERE user_id=?", (user_id,)
                ).fetchone()[0]
                cur = con.execute(
                    "INSERT INTO documents(user_id, name, file_id, file_name, file_type, source_chat_id, source_message_id, created_at, refreshed_at, sort_order) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (user_id, name, file_id, file_name, file_type, source_chat_id, source_message_id, now, now, max_order + 1)
                )
                doc_id = int(cur.lastrowid)
            if tags is not None:
                self._set_document_tags(con, user_id, doc_id, tags)
            else:
                self._ensure_document_has_tag(con, user_id, doc_id)
            return doc_id

    def get_documents(self, user_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM documents WHERE user_id=? ORDER BY sort_order, name", (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_documents_by_tag(self, user_id: int, tag_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute("""
                SELECT d.* FROM documents d
                JOIN document_tag_links dtl ON dtl.document_id = d.id
                JOIN document_tags dt ON dt.id = dtl.tag_id
                WHERE d.user_id=? AND dt.user_id=? AND dt.id=?
                ORDER BY d.sort_order, d.name
            """, (user_id, user_id, tag_id)).fetchall()
            return [dict(r) for r in rows]

    def delete_document(self, user_id: int, doc_id: int):
        with self._conn() as con:
            con.execute("DELETE FROM document_photos WHERE document_id=?", (doc_id,))
            con.execute("DELETE FROM document_tag_links WHERE document_id=?", (doc_id,))
            con.execute("DELETE FROM documents WHERE id=? AND user_id=?", (doc_id, user_id))
            # Clean up orphaned document_tags (no remaining links to any documents)
            con.execute("""
                DELETE FROM document_tags WHERE id NOT IN (
                    SELECT DISTINCT tag_id FROM document_tag_links
                )
            """)

    def rename_document(self, user_id: int, doc_id: int, new_name: str):
        with self._conn() as con:
            con.execute("UPDATE documents SET name=? WHERE id=? AND user_id=?", (new_name, doc_id, user_id))

    def update_doc_sort_order(self, user_id: int, doc_id: int, new_order: int):
        with self._conn() as con:
            con.execute("UPDATE documents SET sort_order=? WHERE id=? AND user_id=?", (new_order, doc_id, user_id))

    def save_document_photos(self, user_id: int, doc_id: int, photos: list[dict]):
        """Сохранить несколько фото для файла.
        photos: [{"file_id": str, "file_type": str}, ...]
        """
        with self._conn() as con:
            # Сначала удаляем старые фото
            con.execute("DELETE FROM document_photos WHERE document_id=?", (doc_id,))
            # Сохраняем новые
            for i, photo in enumerate(photos):
                con.execute(
                    "INSERT INTO document_photos(document_id, file_id, file_type, sort_order) VALUES(?,?,?,?)",
                    (doc_id, photo["file_id"], photo.get("file_type", "photo"), i)
                )

    def get_document_photos(self, doc_id: int) -> list[dict]:
        """Получить все фото файла, отсортированные по порядку."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM document_photos WHERE document_id=? ORDER BY sort_order", (doc_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_document_photos(self, doc_id: int):
        """Удалить все фото файла."""
        with self._conn() as con:
            con.execute("DELETE FROM document_photos WHERE document_id=?", (doc_id,))

    def _set_document_tags(self, con: sqlite3.Connection, user_id: int, doc_id: int, tags: list[str] | None):
        self.tag_documents._set_tags(con, user_id, doc_id, tags)

    def get_or_create_document_tag(self, user_id: int, name: str) -> int:
        with self._conn() as con:
            return self.tag_documents._get_or_create_tag(con, user_id, name)

    def get_document_tags(self, user_id: int, doc_id: int) -> list[dict]:
        return self.tag_documents.get_tags(user_id, doc_id)

    def get_document_tags_with_counts(self, user_id: int) -> list[dict]:
        return self.tag_documents.get_tags_with_counts(user_id)

    def set_document_tags(self, user_id: int, doc_id: int, tags: list[str] | None):
        with self._conn() as con:
            if not con.execute("SELECT id FROM documents WHERE id=? AND user_id=?", (doc_id, user_id)).fetchone():
                return
            self.tag_documents._set_tags(con, user_id, doc_id, tags)

    def add_document_tag(self, user_id: int, doc_id: int, tag_name: str):
        self.tag_documents.add_tag(user_id, doc_id, tag_name)

    def remove_document_tag(self, user_id: int, doc_id: int, tag_id: int):
        self.tag_documents.remove_tag(user_id, doc_id, tag_id)

    def get_document_tag(self, user_id: int, tag_id: int) -> dict | None:
        return self.tag_documents.get_tag(user_id, tag_id)

    def rename_document_tag(self, user_id: int, tag_id: int, new_name: str) -> dict | None:
        return self.tag_documents.rename_tag(user_id, tag_id, new_name)

    def get_documents_to_refresh(self, user_id: int = None, days: int = 30) -> list[dict]:
        with self._conn() as con:
            if user_id is not None:
                rows = con.execute("""
                    SELECT * FROM documents
                    WHERE user_id=? AND (refreshed_at IS NULL OR date(refreshed_at) <= date('now', ? || ' days'))
                    ORDER BY name
                """, (user_id, f'-{days}')).fetchall()
            else:
                rows = con.execute("""
                    SELECT * FROM documents
                    WHERE refreshed_at IS NULL OR date(refreshed_at) <= date('now', ? || ' days')
                    ORDER BY name
                """, (f'-{days}',)).fetchall()
            return [dict(r) for r in rows]

    # ─── Item Tags ────────────────────────────────────────────────────────────

    def get_or_create_item_tag(self, user_id: int, name: str) -> int:
        with self._conn() as con:
            return self.tag_items._get_or_create_tag(con, user_id, name)

    def _ensure_item_has_tag(self, con: sqlite3.Connection, user_id: int, item_id: int):
        self.tag_items._ensure_has_tag(con, user_id, item_id)

    def get_item_tags(self, user_id: int, item_id: int) -> list[dict]:
        with self._conn() as con:
            # Определяем реального владельца элемента (для shared-списков)
            item = con.execute("SELECT user_id FROM list_items WHERE id=?", (item_id,)).fetchone()
            if not item:
                return []
            item_owner = int(item["user_id"])
            self.tag_items._ensure_has_tag(con, item_owner, item_id)
            rows = con.execute("""
                SELECT it.* FROM item_tags it
                JOIN item_tag_links itl ON itl.tag_id = it.id
                JOIN list_items li ON li.id = itl.item_id
                WHERE li.id=?
                ORDER BY it.name
            """, (item_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_item_tags_batch(self, item_ids: list[int]) -> dict[int, list[dict]]:
        """Получить теги для нескольких элементов одним запросом.

        Возвращает {item_id: [tag, ...]}. Элементы без тегов не включаются.
        Используется для устранения N+1 при отображении списков.
        """
        if not item_ids:
            return {}
        with self._conn() as con:
            placeholders = ",".join("?" for _ in item_ids)
            rows = con.execute(f"""
                SELECT itl.item_id, it.id, it.user_id, it.name,
                       it.normalized_name, it.created_at
                FROM item_tags it
                JOIN item_tag_links itl ON itl.tag_id = it.id
                WHERE itl.item_id IN ({placeholders})
                ORDER BY it.name
            """, item_ids).fetchall()
            result: dict[int, list[dict]] = {}
            for row in rows:
                iid = int(row["item_id"])
                result.setdefault(iid, []).append(dict(row))
            return result

    def get_item_tags_for_list(self, list_id: str) -> list[dict]:
        """Получить теги, которые есть в элементах конкретного списка.
        Группирует по normalized_name, чтобы объединить дубликаты от разных пользователей.
        """
        with self._conn() as con:
            rows = con.execute("""
                SELECT
                    MIN(it.id) AS id,
                    MIN(it.user_id) AS user_id,
                    MIN(it.name) AS name,
                    it.normalized_name,
                    MIN(it.created_at) AS created_at,
                    COUNT(li.id) AS count
                FROM item_tags it
                JOIN item_tag_links itl ON itl.tag_id = it.id
                JOIN list_items li ON li.id = itl.item_id
                WHERE li.list_id = ?
                GROUP BY it.normalized_name
                ORDER BY LOWER(MIN(it.name))
            """, (list_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_item_tags_with_counts(self, user_id: int) -> list[dict]:
        return self.tag_items.get_tags_with_counts(user_id)

    def _set_item_tags(self, con: sqlite3.Connection, user_id: int, item_id: int, tags: list[str] | None):
        # Определяем владельца элемента
        item = con.execute("SELECT user_id FROM list_items WHERE id=?", (item_id,)).fetchone()
        item_owner = int(item["user_id"]) if item else user_id
        self.tag_items._set_tags(con, item_owner, item_id, tags)

    def set_item_tags(self, user_id: int, item_id: int, tags: list[str] | None):
        with self._conn() as con:
            if not con.execute("SELECT id FROM list_items WHERE id=?", (item_id,)).fetchone():
                return
            self._set_item_tags(con, user_id, item_id, tags)

    def add_item_tag(self, user_id: int, item_id: int, tag_name: str):
        with self._conn() as con:
            item = con.execute("SELECT user_id FROM list_items WHERE id=?", (item_id,)).fetchone()
            if not item:
                return
            item_owner = int(item["user_id"])
            tag_id = self.tag_items._get_or_create_tag(con, item_owner, tag_name)
            con.execute("INSERT OR IGNORE INTO item_tag_links(item_id, tag_id) VALUES(?,?)", (item_id, tag_id))

    def remove_item_tag(self, user_id: int, item_id: int, tag_id: int):
        with self._conn() as con:
            item = con.execute("SELECT user_id FROM list_items WHERE id=?", (item_id,)).fetchone()
            if not item:
                return
            item_owner = int(item["user_id"])
            con.execute("DELETE FROM item_tag_links WHERE item_id=? AND tag_id=?", (item_id, tag_id))
            self.tag_items._ensure_has_tag(con, item_owner, item_id)

    def get_item_tag(self, user_id: int, tag_id: int) -> dict | None:
        return self.tag_items.get_tag(user_id, tag_id)

    def rename_item_tag(self, user_id: int, tag_id: int, new_name: str) -> dict | None:
        return self.tag_items.rename_tag(user_id, tag_id, new_name)

    # ─── Note Tags ───────────────────────────────────────────────────────────────

    def get_or_create_note_tag(self, user_id: int, name: str) -> int:
        with self._conn() as con:
            return self.tag_notes._get_or_create_tag(con, user_id, name)

    def get_note_tags(self, user_id: int, note_id: int) -> list[dict]:
        return self.tag_notes.get_tags(user_id, note_id)

    def get_note_tags_with_counts(self, user_id: int) -> list[dict]:
        return self.tag_notes.get_tags_with_counts(user_id)

    def get_notes_by_tag(self, user_id: int, tag_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute("""
                SELECT n.* FROM notes n
                JOIN note_tag_links ntl ON ntl.note_id = n.id
                WHERE n.user_id=? AND ntl.tag_id=?
                ORDER BY n.created_at
            """, (user_id, tag_id)).fetchall()
            return [dict(r) for r in rows]

    def set_note_tags(self, user_id: int, note_id: int, tags: list[str] | None):
        with self._conn() as con:
            if not con.execute("SELECT id FROM notes WHERE id=? AND user_id=?", (note_id, user_id)).fetchone():
                return
            self.tag_notes._set_tags(con, user_id, note_id, tags)

    def add_note_tag(self, user_id: int, note_id: int, tag_name: str):
        self.tag_notes.add_tag(user_id, note_id, tag_name)

    def remove_note_tag(self, user_id: int, note_id: int, tag_id: int):
        self.tag_notes.remove_tag(user_id, note_id, tag_id)

    def get_note_tag(self, user_id: int, tag_id: int) -> dict | None:
        return self.tag_notes.get_tag(user_id, tag_id)

    def rename_note_tag(self, user_id: int, tag_id: int, new_name: str) -> dict | None:
        return self.tag_notes.rename_tag(user_id, tag_id, new_name)

    def delete_note_tag(self, user_id: int, tag_id: int):
        self.tag_notes.delete_tag(user_id, tag_id)

    # ─── Reminder Tags ───────────────────────────────────────────────────────────

    def get_or_create_reminder_tag(self, user_id: int, name: str) -> int:
        with self._conn() as con:
            return self.tag_reminders._get_or_create_tag(con, user_id, name)

    def get_reminder_tags(self, user_id: int, reminder_id: int) -> list[dict]:
        return self.tag_reminders.get_tags(user_id, reminder_id)

    def get_reminder_tags_with_counts(self, user_id: int) -> list[dict]:
        return self.tag_reminders.get_tags_with_counts(user_id)

    def get_reminder_tags_with_active_counts(self, chat_id: int) -> list[dict]:
        """Get tag counts for only active (non-delivered, non-timer) reminders."""
        with self._conn() as con:
            rows = con.execute("""
                SELECT t.id, t.name, COUNT(rtl.reminder_id) AS count
                FROM reminder_tags t
                JOIN reminder_tag_links rtl ON rtl.tag_id = t.id
                JOIN reminders r ON r.id = rtl.reminder_id
                WHERE r.chat_id = ? AND r.delivered = 0 AND r.is_timer = 0
                GROUP BY t.id
                ORDER BY LOWER(t.name)
            """, (chat_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_reminders_by_tag(self, user_id: int, tag_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute("""
                SELECT r.* FROM reminders r
                JOIN reminder_tag_links rtl ON rtl.reminder_id = r.id
                WHERE r.chat_id=? AND rtl.tag_id=?
                ORDER BY r.fire_at
            """, (user_id, tag_id)).fetchall()
            return [dict(r) for r in rows]

    def set_reminder_tags(self, user_id: int, reminder_id: int, tags: list[str] | None):
        with self._conn() as con:
            self.tag_reminders._set_tags(con, user_id, reminder_id, tags)

    def add_reminder_tag(self, user_id: int, reminder_id: int, tag_name: str):
        self.tag_reminders.add_tag(user_id, reminder_id, tag_name)

    def remove_reminder_tag(self, user_id: int, reminder_id: int, tag_id: int):
        self.tag_reminders.remove_tag(user_id, reminder_id, tag_id)

    def get_reminder_tag(self, user_id: int, tag_id: int) -> dict | None:
        return self.tag_reminders.get_tag(user_id, tag_id)

    def rename_reminder_tag(self, user_id: int, tag_id: int, new_name: str) -> dict | None:
        return self.tag_reminders.rename_tag(user_id, tag_id, new_name)

    def delete_reminder_tag(self, user_id: int, tag_id: int):
        self.tag_reminders.delete_tag(user_id, tag_id)

    # ─── Location Tags ───────────────────────────────────────────────────────────

    def get_or_create_location_tag(self, user_id: int, name: str) -> int:
        with self._conn() as con:
            return self.tag_locations._get_or_create_tag(con, user_id, name)

    def get_location_tags(self, user_id: int, location_id: int) -> list[dict]:
        return self.tag_locations.get_tags(user_id, location_id)

    def get_location_tags_with_counts(self, user_id: int) -> list[dict]:
        return self.tag_locations.get_tags_with_counts(user_id)

    def get_locations_by_tag(self, user_id: int, tag_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute("""
                SELECT l.* FROM locations l
                JOIN location_tag_links ltl ON ltl.location_id = l.id
                WHERE l.user_id=? AND ltl.tag_id=?
                ORDER BY l.name
            """, (user_id, tag_id)).fetchall()
            return [dict(r) for r in rows]

    def set_location_tags(self, user_id: int, location_id: int, tags: list[str] | None):
        with self._conn() as con:
            if not con.execute("SELECT id FROM locations WHERE id=? AND user_id=?", (location_id, user_id)).fetchone():
                return
            self.tag_locations._set_tags(con, user_id, location_id, tags)

    def add_location_tag(self, user_id: int, location_id: int, tag_name: str):
        self.tag_locations.add_tag(user_id, location_id, tag_name)

    def remove_location_tag(self, user_id: int, location_id: int, tag_id: int):
        self.tag_locations.remove_tag(user_id, location_id, tag_id)

    def get_location_tag(self, user_id: int, tag_id: int) -> dict | None:
        return self.tag_locations.get_tag(user_id, tag_id)

    def rename_location_tag(self, user_id: int, tag_id: int, new_name: str) -> dict | None:
        return self.tag_locations.rename_tag(user_id, tag_id, new_name)

    def delete_location_tag(self, user_id: int, tag_id: int):
        self.tag_locations.delete_tag(user_id, tag_id)

    # ─── PIN ─────────────────────────────────────────────────────────────────
    
    def set_pin(self, user_id: int, pin: str):
        import hashlib
        pin_hash = hashlib.sha256(pin.encode()).hexdigest()
        with self._conn() as con:
            con.execute(
                "INSERT INTO user_pins(user_id, pin_hash) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET pin_hash=excluded.pin_hash",
                (user_id, pin_hash)
            )

    def verify_pin(self, user_id: int, pin: str) -> bool:
        import hashlib
        pin_hash = hashlib.sha256(pin.encode()).hexdigest()
        with self._conn() as con:
            row = con.execute("SELECT pin_hash FROM user_pins WHERE user_id=?", (user_id,)).fetchone()
            return row is not None and row["pin_hash"] == pin_hash

    def has_pin(self, user_id: int) -> bool:
        with self._conn() as con:
            row = con.execute("SELECT 1 FROM user_pins WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
            return row is not None

    def delete_pin(self, user_id: int):
        with self._conn() as con:
            con.execute("DELETE FROM user_pins WHERE user_id=?", (user_id,))

    # ─── Memories ───────────────────────────────────────────────────────────

    def save_memory(self, user_id: int, key: str, value: str, category: str = "общее"):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        category = (category or "общее").strip() or "общее"
        with self._conn() as con:
            con.execute(
                "INSERT INTO user_memories(user_id, key, value, category, created_at, updated_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value, category=excluded.category, updated_at=excluded.updated_at",
                (user_id, key.lower().strip(), value.strip(), category, now, now)
            )

    def get_memory(self, user_id: int, key: str) -> dict | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT * FROM user_memories WHERE user_id=? AND key=?",
                (user_id, key.lower().strip())
            ).fetchone()
            return dict(row) if row else None

    def get_all_memories(self, user_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM user_memories WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def search_memories(self, user_id: int, query: str) -> list[dict]:
        """Поиск по ключу или значению (LIKE)."""
        like = f"%{query}%"
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM user_memories WHERE user_id=? AND (key LIKE ? OR value LIKE ? OR category LIKE ?) ORDER BY updated_at DESC",
                (user_id, like, like, like)
            ).fetchall()
            return [dict(r) for r in rows]

    def update_memory_by_id(self, user_id: int, memory_id: int, key: str, value: str) -> bool:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as con:
            cur = con.execute(
                "UPDATE user_memories SET key=?, value=?, updated_at=? WHERE id=? AND user_id=?",
                (key.lower().strip(), value.strip(), now, memory_id, user_id)
            )
            return cur.rowcount > 0

    def set_memory_category(self, user_id: int, memory_id: int, category: str) -> bool:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        category = (category or "общее").strip() or "общее"
        with self._conn() as con:
            cur = con.execute(
                "UPDATE user_memories SET category=?, updated_at=? WHERE id=? AND user_id=?",
                (category, now, memory_id, user_id)
            )
            return cur.rowcount > 0

    def delete_memory(self, user_id: int, key: str):
        with self._conn() as con:
            con.execute(
                "DELETE FROM user_memories WHERE user_id=? AND key=?",
                (user_id, key.lower().strip())
            )

    def delete_memory_by_id(self, user_id: int, memory_id: int):
        with self._conn() as con:
            con.execute(
                "DELETE FROM user_memories WHERE id=? AND user_id=?", (memory_id, user_id)
            )

    def clear_memories(self, user_id: int):
        with self._conn() as con:
            con.execute("DELETE FROM user_memories WHERE user_id=?", (user_id,))

    def count_memories(self, user_id: int) -> int:
        with self._conn() as con:
            row = con.execute(
                "SELECT COUNT(*) AS count FROM user_memories WHERE user_id=?", (user_id,)
            ).fetchone()
            return int(row["count"])

    # ─── Access Control ────────────────────────────────────────────────────

    def allow_user(self, user_id: int, allowed_by: int):
        with self._conn() as con:
            con.execute(
                "INSERT INTO access(user_id, allowed_by, created_at) VALUES(?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET allowed_by=excluded.allowed_by, created_at=excluded.created_at",
                (user_id, allowed_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )

    def disallow_user(self, user_id: int):
        with self._conn() as con:
            con.execute("DELETE FROM access WHERE user_id=?", (user_id,))

    def is_user_allowed(self, user_id: int) -> bool:
        with self._conn() as con:
            row = con.execute("SELECT 1 FROM access WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
            return row is not None

    def get_allowed_users(self) -> list[dict]:
        with self._conn() as con:
            rows = con.execute("""
                SELECT a.user_id, a.allowed_by, a.created_at, u.name
                FROM access a
                LEFT JOIN users u ON u.user_id = a.user_id
                ORDER BY a.created_at
            """).fetchall()
            return [dict(r) for r in rows]

    # ─── Lockdown / Access mode ───────────────────────────────────────────

    def get_lockdown(self) -> bool:
        """Проверить, включён ли режим ограничения доступа."""
        with self._conn() as con:
            row = con.execute(
                "SELECT value FROM bot_settings WHERE key='lockdown'"
            ).fetchone()
            return row is not None and row["value"] == "1"

    def set_lockdown(self, enabled: bool):
        """Включить/выключить режим ограничения доступа."""
        with self._conn() as con:
            con.execute(
                "INSERT INTO bot_settings(key, value) VALUES('lockdown', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                ("1" if enabled else "0",)
            )

    # ─── Supplies ───────────────────────────────────────────────────────

    def save_supply(self, user_id: int, name: str, quantity: int = 0, min_quantity: int = 0, normal_quantity: int = 0) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as con:
            existing = con.execute(
                "SELECT id FROM supplies WHERE user_id=? AND name=?", (user_id, name)
            ).fetchone()
            if existing:
                con.execute("UPDATE supplies SET quantity=?, min_quantity=?, normal_quantity=?, sort_order=(SELECT COALESCE(MAX(sort_order),0)+1 FROM supplies WHERE user_id=?) WHERE id=?", (quantity, min_quantity, normal_quantity, user_id, int(existing["id"])))
                return int(existing["id"])
            max_order = con.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM supplies WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            cur = con.execute(
                "INSERT INTO supplies(user_id, name, quantity, min_quantity, normal_quantity, sort_order, created_at) VALUES(?,?,?,?,?,?,?)",
                (user_id, name, quantity, min_quantity, normal_quantity, max_order + 1, now)
            )
            return int(cur.lastrowid)

    def get_supplies(self, user_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM supplies WHERE user_id=? ORDER BY sort_order, name", (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_supply(self, user_id: int, supply_id: int) -> dict | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT * FROM supplies WHERE id=? AND user_id=?", (supply_id, user_id)
            ).fetchone()
            return dict(row) if row else None

    def update_supply_name(self, user_id: int, supply_id: int, new_name: str):
        with self._conn() as con:
            con.execute("UPDATE supplies SET name=? WHERE id=? AND user_id=?", (new_name, supply_id, user_id))

    def update_supply_quantity(self, user_id: int, supply_id: int, quantity: int):
        with self._conn() as con:
            con.execute("UPDATE supplies SET quantity=? WHERE id=? AND user_id=?", (quantity, supply_id, user_id))

    def update_supply_photo(self, user_id: int, supply_id: int, file_id: str, file_type: str = 'photo'):
        with self._conn() as con:
            con.execute("UPDATE supplies SET photo_file_id=?, photo_file_type=? WHERE id=? AND user_id=?", (file_id, file_type, supply_id, user_id))

    def update_supply_min_quantity(self, user_id: int, supply_id: int, min_quantity: int):
        with self._conn() as con:
            con.execute("UPDATE supplies SET min_quantity=? WHERE id=? AND user_id=?", (min_quantity, supply_id, user_id))

    def update_supply_normal_quantity(self, user_id: int, supply_id: int, normal_quantity: int):
        with self._conn() as con:
            con.execute("UPDATE supplies SET normal_quantity=? WHERE id=? AND user_id=?", (normal_quantity, supply_id, user_id))

    def delete_supply(self, user_id: int, supply_id: int):
        with self._conn() as con:
            con.execute("DELETE FROM supplies WHERE id=? AND user_id=?", (supply_id, user_id))

    def supply_exists(self, user_id: int, name: str) -> bool:
        with self._conn() as con:
            return con.execute(
                "SELECT 1 FROM supplies WHERE user_id=? AND name=? LIMIT 1", (user_id, name)
            ).fetchone() is not None

    def update_supply_sort_order(self, user_id: int, supply_id: int, sort_order: int):
        with self._conn() as con:
            con.execute("UPDATE supplies SET sort_order=? WHERE id=? AND user_id=?", (sort_order, supply_id, user_id))

    # ─── Supply Tags ───────────────────────────────────────────────────────────

    def get_or_create_supply_tag(self, user_id: int, name: str) -> int:
        with self._conn() as con:
            return self.tag_supplies._get_or_create_tag(con, user_id, name)

    def get_supply_tags(self, user_id: int, supply_id: int) -> list[dict]:
        return self.tag_supplies.get_tags(user_id, supply_id)

    def get_supply_tags_with_counts(self, user_id: int) -> list[dict]:
        return self.tag_supplies.get_tags_with_counts(user_id)

    def get_supplies_by_tag(self, user_id: int, tag_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute("""
                SELECT s.* FROM supplies s
                JOIN supply_tag_links stl ON stl.supply_id = s.id
                WHERE s.user_id=? AND stl.tag_id=?
                ORDER BY s.sort_order, s.name
            """, (user_id, tag_id)).fetchall()
            return [dict(r) for r in rows]

    def add_supply_tag(self, user_id: int, supply_id: int, tag_name: str):
        self.tag_supplies.add_tag(user_id, supply_id, tag_name)

    def remove_supply_tag(self, user_id: int, supply_id: int, tag_id: int):
        self.tag_supplies.remove_tag(user_id, supply_id, tag_id)

    def get_supply_tag(self, user_id: int, tag_id: int) -> dict | None:
        return self.tag_supplies.get_tag(user_id, tag_id)

    # ─── Error Logs ────────────────────────────────────────────────────────

    def log_error(self, user_id: int, level: str, message: str, traceback: str = ""):
        """Log an error to the database."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as con:
            con.execute(
                "INSERT INTO error_logs(user_id, level, message, traceback, created_at) VALUES(?,?,?,?,?)",
                (user_id, level, message[:500], traceback[:2000], now)
            )

    def get_unread_errors_count(self) -> int:
        """Get count of unread errors."""
        with self._conn() as con:
            row = con.execute("SELECT COUNT(*) AS cnt FROM error_logs WHERE is_read=0").fetchone()
            return int(row["cnt"]) if row else 0

    def get_recent_errors(self, limit: int = 20) -> list[dict]:
        """Get recent errors, newest first."""
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM error_logs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_errors_read(self):
        """Mark all unread errors as read."""
        with self._conn() as con:
            con.execute("UPDATE error_logs SET is_read=1 WHERE is_read=0")

    def cleanup_old_errors(self, days: int = 30):
        """Delete error logs older than N days."""
        with self._conn() as con:
            con.execute(
                "DELETE FROM error_logs WHERE created_at < datetime('now', ?) AND is_read=1",
                (f'-{days} days',)
            )

    # ─── Birthdays ─────────────────────────────────────────────────────────

    def get_birthdays(self, user_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM birthdays WHERE user_id=? ORDER BY birth_date, name", (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def save_birthday(self, user_id: int, name: str, birth_date: str) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as con:
            existing = con.execute(
                "SELECT id FROM birthdays WHERE user_id=? AND name=?", (user_id, name)
            ).fetchone()
            if existing:
                con.execute(
                    "UPDATE birthdays SET birth_date=? WHERE id=?", (birth_date, int(existing["id"]))
                )
                return int(existing["id"])
            cur = con.execute(
                "INSERT INTO birthdays(user_id, name, birth_date, created_at) VALUES(?,?,?,?)",
                (user_id, name, birth_date, now)
            )
            return int(cur.lastrowid)

    def update_birthday(self, user_id: int, bday_id: int, name: str, birth_date: str):
        """Обновить имя и/или дату дня рождения по id."""
        with self._conn() as con:
            con.execute(
                "UPDATE birthdays SET name=?, birth_date=? WHERE id=? AND user_id=?",
                (name, birth_date, bday_id, user_id)
            )

    def delete_birthday(self, user_id: int, bday_id: int):
        with self._conn() as con:
            con.execute("DELETE FROM birthdays WHERE id=? AND user_id=?", (bday_id, user_id))

    def birthday_exists(self, user_id: int, name: str) -> bool:
        with self._conn() as con:
            return con.execute(
                "SELECT 1 FROM birthdays WHERE user_id=? AND name=? LIMIT 1", (user_id, name)
            ).fetchone() is not None

    def get_birthday_time(self, user_id: int) -> str:
        """Получить время уведомления о днях рождения. По умолчанию 10:00."""
        with self._conn() as con:
            row = con.execute(
                "SELECT notify_time FROM birthday_settings WHERE user_id=?", (user_id,)
            ).fetchone()
            return row["notify_time"] if row else "10:00"

    def set_birthday_time(self, user_id: int, time_str: str):
        """Установить время уведомления о днях рождения."""
        with self._conn() as con:
            self._ensure_column(con, "birthday_settings", "notify_advance", "INTEGER DEFAULT 1")
            con.execute(
                "INSERT INTO birthday_settings(user_id, notify_time) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET notify_time=excluded.notify_time",
                (user_id, time_str)
            )

    def get_birthday_advance(self, user_id: int) -> bool:
        """Получить, включено ли предварительное уведомление за день до ДР."""
        with self._conn() as con:
            self._ensure_column(con, "birthday_settings", "notify_advance", "INTEGER DEFAULT 1")
            row = con.execute(
                "SELECT notify_advance FROM birthday_settings WHERE user_id=?", (user_id,)
            ).fetchone()
            return bool(row["notify_advance"]) if row else True

    def set_birthday_advance(self, user_id: int, enabled: bool):
        """Включить/выключить предварительное уведомление за день до ДР."""
        with self._conn() as con:
            self._ensure_column(con, "birthday_settings", "notify_advance", "INTEGER DEFAULT 1")
            # Проверяем, есть ли уже запись
            existing = con.execute(
                "SELECT notify_time FROM birthday_settings WHERE user_id=?", (user_id,)
            ).fetchone()
            if existing:
                con.execute(
                    "UPDATE birthday_settings SET notify_advance=? WHERE user_id=?",
                    (int(enabled), user_id)
                )
            else:
                con.execute(
                    "INSERT INTO birthday_settings(user_id, notify_time, notify_advance) VALUES(?,?,?)",
                    (user_id, "10:00", int(enabled))
                )

    def get_all_birthday_user_ids(self) -> list[int]:
        """Получить список всех user_id, у которых есть дни рождения."""
        with self._conn() as con:
            rows = con.execute("SELECT DISTINCT user_id FROM birthdays").fetchall()
            return [int(r["user_id"]) for r in rows]

    # ─── Locations ────────────────────────────────────────────────────────────

    def save_location(self, user_id: int, name: str, latitude: float, longitude: float):
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as con:
            max_order = con.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM locations WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            con.execute(
                "INSERT INTO locations(user_id, name, latitude, longitude, created_at, sort_order) VALUES(?,?,?,?,?,?)",
                (user_id, name, latitude, longitude, now, max_order + 1)
            )

    def get_locations(self, user_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM locations WHERE user_id=? ORDER BY sort_order, name", (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_location(self, user_id: int, loc_id: int):
        with self._conn() as con:
            con.execute("DELETE FROM location_tag_links WHERE location_id=?", (loc_id,))
            con.execute("DELETE FROM locations WHERE id=? AND user_id=?", (loc_id, user_id))
            con.execute("""
                DELETE FROM location_tags WHERE id NOT IN (
                    SELECT DISTINCT tag_id FROM location_tag_links
                )
            """)

    def rename_location(self, user_id: int, loc_id: int, new_name: str):
        with self._conn() as con:
            con.execute("UPDATE locations SET name=? WHERE id=? AND user_id=?", (new_name, loc_id, user_id))

    def update_loc_sort_order(self, user_id: int, loc_id: int, new_order: int):
        with self._conn() as con:
            con.execute("UPDATE locations SET sort_order=? WHERE id=? AND user_id=?", (new_order, loc_id, user_id))

    # ─── Summary Config ────────────────────────────────────────────────────

    def get_summary_config(self, user_id: int) -> list[str]:
        with self._conn() as con:
            row = con.execute(
                "SELECT sections FROM summary_config WHERE user_id=?", (user_id,)
            ).fetchone()
            if row:
                try:
                    data = json.loads(row["sections"])
                    if isinstance(data, dict):
                        return data.get("sections", [])
                    return data
                except (json.JSONDecodeError, TypeError):
                    pass
        return ["reminders", "timers", "birthdays", "weather", "summa", "rate", "supplies", "lists"]

    def save_summary_config(self, user_id: int, sections: list[str]):
        with self._conn() as con:
            row = con.execute(
                "SELECT sections FROM summary_config WHERE user_id=?", (user_id,)
            ).fetchone()
            sort_mode = ""
            if row:
                try:
                    data = json.loads(row["sections"])
                    if isinstance(data, dict):
                        sort_mode = data.get("sort_mode", "")
                except (json.JSONDecodeError, TypeError):
                    pass
            if sort_mode:
                data = {"sections": sections, "sort_mode": sort_mode}
            else:
                data = sections
            con.execute(
                "INSERT INTO summary_config(user_id, sections, created_at) VALUES(?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET sections=excluded.sections",
                (user_id, json.dumps(data), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )

    def get_summary_sort_mode(self, user_id: int) -> str:
        with self._conn() as con:
            row = con.execute(
                "SELECT sections FROM summary_config WHERE user_id=?", (user_id,)
            ).fetchone()
            if row:
                try:
                    data = json.loads(row["sections"])
                    if isinstance(data, dict):
                        return data.get("sort_mode", "")
                except (json.JSONDecodeError, TypeError):
                    pass
        return ""

    def save_summary_sort_mode(self, user_id: int, sort_mode: str):
        with self._conn() as con:
            row = con.execute(
                "SELECT sections FROM summary_config WHERE user_id=?", (user_id,)
            ).fetchone()
            if row:
                try:
                    data = json.loads(row["sections"])
                    if isinstance(data, list):
                        data = {"sections": data, "sort_mode": sort_mode}
                    elif isinstance(data, dict):
                        data["sort_mode"] = sort_mode
                    else:
                        data = {"sections": [], "sort_mode": sort_mode}
                except (json.JSONDecodeError, TypeError):
                    data = {"sections": [], "sort_mode": sort_mode}
            else:
                data = {"sections": ["reminders", "timers", "birthdays", "weather", "summa", "rate", "supplies", "lists"], "sort_mode": sort_mode}
            con.execute(
                "INSERT INTO summary_config(user_id, sections, created_at) VALUES(?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET sections=excluded.sections",
                (user_id, json.dumps(data), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )

    # ─── Weather Locations ────────────────────────────────────────────────────

    def save_weather_location(self, user_id: int, name: str, latitude: float, longitude: float, is_primary: bool = False) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._conn() as con:
            if is_primary:
                con.execute("UPDATE weather_locations SET is_primary=0 WHERE user_id=?", (user_id,))
            cur = con.execute(
                "INSERT INTO weather_locations(user_id, name, latitude, longitude, created_at, is_primary) VALUES(?,?,?,?,?,?)",
                (user_id, name, latitude, longitude, now, int(is_primary))
            )
            return int(cur.lastrowid)

    def get_weather_locations(self, user_id: int) -> list[dict]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT * FROM weather_locations WHERE user_id=? ORDER BY is_primary DESC, created_at", (user_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_weather_location(self, user_id: int, loc_id: int):
        with self._conn() as con:
            con.execute("DELETE FROM weather_locations WHERE id=? AND user_id=?", (loc_id, user_id))

    def rename_weather_location(self, user_id: int, loc_id: int, new_name: str):
        with self._conn() as con:
            con.execute("UPDATE weather_locations SET name=? WHERE id=? AND user_id=?", (new_name, loc_id, user_id))

    def update_weather_location_coords(self, user_id: int, loc_id: int, latitude: float, longitude: float):
        with self._conn() as con:
            con.execute(
                "UPDATE weather_locations SET latitude=?, longitude=? WHERE id=? AND user_id=?",
                (latitude, longitude, loc_id, user_id)
            )

    def set_primary_weather_location(self, user_id: int, loc_id: int):
        """Сделать локацию основной (снять primary с остальных)."""
        with self._conn() as con:
            con.execute("UPDATE weather_locations SET is_primary=0 WHERE user_id=?", (user_id,))
            con.execute("UPDATE weather_locations SET is_primary=1 WHERE id=? AND user_id=?", (loc_id, user_id))

    # ─── Widget Settings ───────────────────────────────────────────────────

    def get_widget_settings(self, user_id: int) -> dict | None:
        with self._conn() as con:
            row = con.execute(
                "SELECT * FROM widget_settings WHERE user_id=?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    def set_widget_time(self, user_id: int, time_str: str):
        """Установить время отправки виджета для пользователя.
        Сбрасывает last_sent_date, чтобы сводка отправилась повторно сегодня.
        """
        with self._conn() as con:
            con.execute(
                "INSERT INTO widget_settings(user_id, time) VALUES(?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET time=excluded.time, last_sent_date=NULL",
                (user_id, time_str)
            )

    def get_widget_last_sent_date(self, user_id: int) -> str | None:
        """Получить дату последней отправки виджета."""
        with self._conn() as con:
            row = con.execute(
                "SELECT last_sent_date FROM widget_settings WHERE user_id=?", (user_id,)
            ).fetchone()
            return row["last_sent_date"] if row else None

    def set_widget_last_sent_date(self, user_id: int, date_str: str):
        """Записать дату отправки виджета."""
        with self._conn() as con:
            con.execute(
                "INSERT INTO widget_settings(user_id, last_sent_date) VALUES(?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET last_sent_date=excluded.last_sent_date",
                (user_id, date_str)
            )

    def get_all_widget_users(self) -> list[dict]:
        """Получить всех пользователей с настройками виджета."""
        with self._conn() as con:
            rows = con.execute("SELECT * FROM widget_settings").fetchall()
            return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# Global singleton instance
# ═══════════════════════════════════════════════════════════════════════════════
db = Database()


# ═══════════════════════════════════════════════════════════════════════════════
# Async db_* wrapper functions
#
# Все db_* функции теперь асинхронные — используют asyncio.to_thread
# для неблокирующего выполнения синхронных Database методов.
# ═══════════════════════════════════════════════════════════════════════════════

import asyncio

_db_executor = None

def _get_db_executor():
    global _db_executor
    if _db_executor is None:
        from concurrent.futures import ThreadPoolExecutor
        _db_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="db")
    return _db_executor


async def db_run(func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_get_db_executor(), lambda: func(*args, **kwargs))


def init_db():
    db.init_db()

# Users
async def db_get_user(user_id: int) -> dict | None: return await db_run(db.get_user, user_id)
async def db_upsert_user(user_id: int, name: str): await db_run(db.upsert_user, user_id, name)
async def db_count_users() -> int: return await db_run(db.count_users)
async def db_get_all_users() -> list[dict]: return await db_run(db.get_all_users)

# Lists
async def db_create_list(list_id: str, ltype: str, name: str, created_by: int): await db_run(db.create_list, list_id, ltype, name, created_by)
async def db_get_lists_for_user(user_id: int) -> list[dict]: return await db_run(db.get_lists_for_user, user_id)
async def db_get_list(list_id: str) -> dict | None: return await db_run(db.get_list, list_id)
async def db_delete_list(list_id: str): await db_run(db.delete_list, list_id)
async def db_count_lists() -> int: return await db_run(db.count_lists)
async def db_list_exists(name: str, created_by: int) -> bool: return await db_run(db.list_exists, name, created_by)

# List Items
async def db_add_item(list_id: str, user_id: int, item: str, emoji: str = "📌"): await db_run(db.add_item, list_id, user_id, item, emoji)
async def db_item_exists(list_id: str, item: str) -> bool: return await db_run(db.item_exists, list_id, item)
async def db_get_items(list_id: str) -> list[dict]: return await db_run(db.get_items, list_id)
async def db_delete_item_by_index(list_id: str, index: int): await db_run(db.delete_item_by_index, list_id, index)
async def db_toggle_item_checked(list_id: str, index: int) -> int | None: return await db_run(db.toggle_item_checked, list_id, index)
async def db_toggle_item_checked_by_id(list_id: str, item_id: int) -> int | None: return await db_run(db.toggle_item_checked_by_id, list_id, item_id)
async def db_get_item_by_index(list_id: str, index: int) -> dict | None: return await db_run(db.get_item_by_index, list_id, index)
async def db_sort_items_by_emoji(list_id: str) -> int: return await db_run(db.sort_items_by_emoji, list_id)
async def db_update_item_sort_order(list_id: str, item_id: int, new_order: int): await db_run(db.update_item_sort_order, list_id, item_id, new_order)

# Summa
async def db_get_summa(user_id: int) -> float | None: return await db_run(db.get_summa, user_id)
async def db_set_summa(user_id: int, value: float): await db_run(db.set_summa, user_id, value)

# Reminders
async def db_save_reminder(chat_id: int, rid: int, text: str, fire_at: datetime,
                           is_timer: bool = False, repeat_type: str = "none", minutes: int = 0, repeat_days: str = ""):
    await db_run(db.save_reminder, chat_id, rid, text, fire_at, is_timer, repeat_type, minutes, repeat_days)
async def db_delete_reminder(chat_id: int, rid: int): await db_run(db.delete_reminder, chat_id, rid)
async def db_has_duplicate_reminder(chat_id: int, text: str, fire_at: datetime, repeat_type: str | None = None) -> bool:
    return await db_run(db.has_duplicate_reminder, chat_id, text, fire_at, repeat_type)
async def db_get_reminder(chat_id: int, rid: int) -> dict | None: return await db_run(db.get_reminder, chat_id, rid)
async def db_update_reminder(chat_id: int, rid: int, **fields: Any): await db_run(lambda: db.update_reminder(chat_id, rid, **fields))
async def db_get_pending_reminders() -> list[dict]: return await db_run(db.get_pending_reminders)
async def db_get_reminder_counts() -> dict: return await db_run(db.get_reminder_counts)

# List Sharing
async def db_share_list(list_id: str, user_id: int, permission: str = "write"): await db_run(db.share_list, list_id, user_id, permission)
async def db_unshare_list(list_id: str, user_id: int): await db_run(db.unshare_list, list_id, user_id)
async def db_get_shared_lists(user_id: int) -> list[dict]: return await db_run(db.get_shared_lists, user_id)
async def db_get_list_members(list_id: str) -> list[dict]: return await db_run(db.get_list_members, list_id)
async def db_is_list_member(list_id: str, user_id: int) -> bool: return await db_run(db.is_list_member, list_id, user_id)
async def db_get_list_permission(list_id: str, user_id: int) -> str | None: return await db_run(db.get_list_permission, list_id, user_id)

# Cards
async def db_save_card(user_id: int, name: str, number: str): await db_run(db.save_card, user_id, name, number)
async def db_get_cards(user_id: int) -> list[dict]: return await db_run(db.get_cards, user_id)
async def db_delete_card(user_id: int, card_id: int): await db_run(db.delete_card, user_id, card_id)
async def db_update_card(user_id: int, card_id: int, name: str, number: str): await db_run(db.update_card, user_id, card_id, name, number)
async def db_card_exists(user_id: int, name: str) -> bool: return await db_run(db.card_exists, user_id, name)

# Notes
async def db_save_note(user_id: int, name: str, content: str): await db_run(db.save_note, user_id, name, content)
async def db_get_notes(user_id: int) -> list[dict]: return await db_run(db.get_notes, user_id)
async def db_delete_note(user_id: int, note_id: int): await db_run(db.delete_note, user_id, note_id)
async def db_update_note(user_id: int, note_id: int, name: str, content: str): await db_run(db.update_note, user_id, note_id, name, content)
async def db_note_exists(user_id: int, name: str) -> bool: return await db_run(db.note_exists, user_id, name)

# Documents
async def db_save_document(user_id: int, name: str, file_id: str, file_name: str,
                           file_type: str = "document", source_chat_id: int = None,
                           source_message_id: int = None, tags: list[str] | None = None) -> int:
    return await db_run(db.save_document, user_id, name, file_id, file_name, file_type, source_chat_id, source_message_id, tags)
async def db_get_documents(user_id: int) -> list[dict]: return await db_run(db.get_documents, user_id)
async def db_get_documents_by_tag(user_id: int, tag_id: int) -> list[dict]: return await db_run(db.get_documents_by_tag, user_id, tag_id)
async def db_delete_document(user_id: int, doc_id: int): await db_run(db.delete_document, user_id, doc_id)
async def db_rename_document(user_id: int, doc_id: int, new_name: str): await db_run(db.rename_document, user_id, doc_id, new_name)
async def db_update_doc_sort_order(user_id: int, doc_id: int, new_order: int): await db_run(db.update_doc_sort_order, user_id, doc_id, new_order)
async def db_get_or_create_document_tag(user_id: int, name: str) -> int: return await db_run(db.get_or_create_document_tag, user_id, name)
async def db_get_document_tags(user_id: int, doc_id: int) -> list[dict]: return await db_run(db.get_document_tags, user_id, doc_id)
async def db_get_document_tags_with_counts(user_id: int) -> list[dict]: return await db_run(db.get_document_tags_with_counts, user_id)
async def db_set_document_tags(user_id: int, doc_id: int, tags: list[str] | None): await db_run(db.set_document_tags, user_id, doc_id, tags)
async def db_add_document_tag(user_id: int, doc_id: int, tag_name: str): await db_run(db.add_document_tag, user_id, doc_id, tag_name)
async def db_remove_document_tag(user_id: int, doc_id: int, tag_id: int): await db_run(db.remove_document_tag, user_id, doc_id, tag_id)
async def db_get_document_tag(user_id: int, tag_id: int) -> dict | None: return await db_run(db.get_document_tag, user_id, tag_id)
async def db_rename_document_tag(user_id: int, tag_id: int, new_name: str) -> dict | None: return await db_run(db.rename_document_tag, user_id, tag_id, new_name)
async def db_get_documents_to_refresh(user_id: int = None, days: int = 30) -> list[dict]: return await db_run(db.get_documents_to_refresh, user_id, days)
async def db_save_document_photos(user_id: int, doc_id: int, photos: list[dict]): await db_run(db.save_document_photos, user_id, doc_id, photos)
async def db_get_document_photos(doc_id: int) -> list[dict]: return await db_run(db.get_document_photos, doc_id)
async def db_delete_document_photos(doc_id: int): await db_run(db.delete_document_photos, doc_id)

# Item Tags
async def db_get_or_create_item_tag(user_id: int, name: str) -> int: return await db_run(db.get_or_create_item_tag, user_id, name)
async def db_get_item_tags(user_id: int, item_id: int) -> list[dict]: return await db_run(db.get_item_tags, user_id, item_id)
async def db_get_item_tags_batch(item_ids: list[int]) -> dict[int, list[dict]]: return await db_run(db.get_item_tags_batch, item_ids)
async def db_get_item_tags_with_counts(user_id: int) -> list[dict]: return await db_run(db.get_item_tags_with_counts, user_id)
async def db_get_item_tags_for_list(list_id: str) -> list[dict]: return await db_run(db.get_item_tags_for_list, list_id)
async def db_set_item_tags(user_id: int, item_id: int, tags: list[str] | None): await db_run(db.set_item_tags, user_id, item_id, tags)
async def db_add_item_tag(user_id: int, item_id: int, tag_name: str): await db_run(db.add_item_tag, user_id, item_id, tag_name)
async def db_remove_item_tag(user_id: int, item_id: int, tag_id: int): await db_run(db.remove_item_tag, user_id, item_id, tag_id)
async def db_get_item_tag(user_id: int, tag_id: int) -> dict | None: return await db_run(db.get_item_tag, user_id, tag_id)
async def db_rename_item_tag(user_id: int, tag_id: int, new_name: str) -> dict | None: return await db_run(db.rename_item_tag, user_id, tag_id, new_name)

# Note Tags
async def db_get_or_create_note_tag(user_id: int, name: str) -> int: return await db_run(db.get_or_create_note_tag, user_id, name)
async def db_get_note_tags(user_id: int, note_id: int) -> list[dict]: return await db_run(db.get_note_tags, user_id, note_id)
async def db_get_note_tags_with_counts(user_id: int) -> list[dict]: return await db_run(db.get_note_tags_with_counts, user_id)
async def db_get_notes_by_tag(user_id: int, tag_id: int) -> list[dict]: return await db_run(db.get_notes_by_tag, user_id, tag_id)
async def db_set_note_tags(user_id: int, note_id: int, tags: list[str] | None): await db_run(db.set_note_tags, user_id, note_id, tags)
async def db_add_note_tag(user_id: int, note_id: int, tag_name: str): await db_run(db.add_note_tag, user_id, note_id, tag_name)
async def db_remove_note_tag(user_id: int, note_id: int, tag_id: int): await db_run(db.remove_note_tag, user_id, note_id, tag_id)
async def db_get_note_tag(user_id: int, tag_id: int) -> dict | None: return await db_run(db.get_note_tag, user_id, tag_id)
async def db_rename_note_tag(user_id: int, tag_id: int, new_name: str) -> dict | None: return await db_run(db.rename_note_tag, user_id, tag_id, new_name)
async def db_delete_note_tag(user_id: int, tag_id: int): await db_run(db.delete_note_tag, user_id, tag_id)

# Reminder Tags
async def db_get_or_create_reminder_tag(user_id: int, name: str) -> int: return await db_run(db.get_or_create_reminder_tag, user_id, name)
async def db_get_reminder_tags(user_id: int, reminder_id: int) -> list[dict]: return await db_run(db.get_reminder_tags, user_id, reminder_id)
async def db_get_reminder_tags_with_counts(user_id: int) -> list[dict]: return await db_run(db.get_reminder_tags_with_counts, user_id)
async def db_get_reminder_tags_with_active_counts(chat_id: int) -> list[dict]: return await db_run(db.get_reminder_tags_with_active_counts, chat_id)
async def db_get_reminders_by_tag(user_id: int, tag_id: int) -> list[dict]: return await db_run(db.get_reminders_by_tag, user_id, tag_id)
async def db_set_reminder_tags(user_id: int, reminder_id: int, tags: list[str] | None): await db_run(db.set_reminder_tags, user_id, reminder_id, tags)
async def db_add_reminder_tag(user_id: int, reminder_id: int, tag_name: str): await db_run(db.add_reminder_tag, user_id, reminder_id, tag_name)
async def db_remove_reminder_tag(user_id: int, reminder_id: int, tag_id: int): await db_run(db.remove_reminder_tag, user_id, reminder_id, tag_id)
async def db_get_reminder_tag(user_id: int, tag_id: int) -> dict | None: return await db_run(db.get_reminder_tag, user_id, tag_id)
async def db_rename_reminder_tag(user_id: int, tag_id: int, new_name: str) -> dict | None: return await db_run(db.rename_reminder_tag, user_id, tag_id, new_name)
async def db_delete_reminder_tag(user_id: int, tag_id: int): await db_run(db.delete_reminder_tag, user_id, tag_id)

# Location Tags
async def db_get_or_create_location_tag(user_id: int, name: str) -> int: return await db_run(db.get_or_create_location_tag, user_id, name)
async def db_get_location_tags(user_id: int, location_id: int) -> list[dict]: return await db_run(db.get_location_tags, user_id, location_id)
async def db_get_location_tags_with_counts(user_id: int) -> list[dict]: return await db_run(db.get_location_tags_with_counts, user_id)
async def db_get_locations_by_tag(user_id: int, tag_id: int) -> list[dict]: return await db_run(db.get_locations_by_tag, user_id, tag_id)
async def db_set_location_tags(user_id: int, location_id: int, tags: list[str] | None): await db_run(db.set_location_tags, user_id, location_id, tags)
async def db_add_location_tag(user_id: int, location_id: int, tag_name: str): await db_run(db.add_location_tag, user_id, location_id, tag_name)
async def db_remove_location_tag(user_id: int, location_id: int, tag_id: int): await db_run(db.remove_location_tag, user_id, location_id, tag_id)
async def db_get_location_tag(user_id: int, tag_id: int) -> dict | None: return await db_run(db.get_location_tag, user_id, tag_id)
async def db_rename_location_tag(user_id: int, tag_id: int, new_name: str) -> dict | None: return await db_run(db.rename_location_tag, user_id, tag_id, new_name)
async def db_delete_location_tag(user_id: int, tag_id: int): await db_run(db.delete_location_tag, user_id, tag_id)

# PIN
async def db_set_pin(user_id: int, pin: str): await db_run(db.set_pin, user_id, pin)
async def db_verify_pin(user_id: int, pin: str) -> bool: return await db_run(db.verify_pin, user_id, pin)
async def db_has_pin(user_id: int) -> bool: return await db_run(db.has_pin, user_id)
async def db_delete_pin(user_id: int): await db_run(db.delete_pin, user_id)

# Locations
async def db_save_location(user_id: int, name: str, latitude: float, longitude: float): await db_run(db.save_location, user_id, name, latitude, longitude)
async def db_get_locations(user_id: int) -> list[dict]: return await db_run(db.get_locations, user_id)
async def db_delete_location(user_id: int, loc_id: int): await db_run(db.delete_location, user_id, loc_id)
async def db_rename_location(user_id: int, loc_id: int, new_name: str): await db_run(db.rename_location, user_id, loc_id, new_name)
async def db_update_loc_sort_order(user_id: int, loc_id: int, new_order: int): await db_run(db.update_loc_sort_order, user_id, loc_id, new_order)

# Summary Config
async def db_get_summary_config(user_id: int) -> list[str]: return await db_run(db.get_summary_config, user_id)
async def db_save_summary_config(user_id: int, sections: list[str]): await db_run(db.save_summary_config, user_id, sections)
async def db_get_summary_sort_mode(user_id: int) -> str: return await db_run(db.get_summary_sort_mode, user_id)
async def db_save_summary_sort_mode(user_id: int, sort_mode: str): await db_run(db.save_summary_sort_mode, user_id, sort_mode)

# Weather Locations
async def db_save_weather_location(user_id: int, name: str, latitude: float, longitude: float, is_primary: bool = False) -> int:
    return await db_run(db.save_weather_location, user_id, name, latitude, longitude, is_primary)
async def db_get_weather_locations(user_id: int) -> list[dict]: return await db_run(db.get_weather_locations, user_id)
async def db_delete_weather_location(user_id: int, loc_id: int): await db_run(db.delete_weather_location, user_id, loc_id)
async def db_rename_weather_location(user_id: int, loc_id: int, new_name: str): await db_run(db.rename_weather_location, user_id, loc_id, new_name)
async def db_update_weather_location_coords(user_id: int, loc_id: int, latitude: float, longitude: float): await db_run(db.update_weather_location_coords, user_id, loc_id, latitude, longitude)
async def db_set_primary_weather_location(user_id: int, loc_id: int): await db_run(db.set_primary_weather_location, user_id, loc_id)

# Widget Settings
async def db_get_widget_settings(user_id: int) -> dict | None: return await db_run(db.get_widget_settings, user_id)
async def db_set_widget_time(user_id: int, time_str: str): await db_run(db.set_widget_time, user_id, time_str)
async def db_get_widget_last_sent_date(user_id: int) -> str | None: return await db_run(db.get_widget_last_sent_date, user_id)
async def db_set_widget_last_sent_date(user_id: int, date_str: str): await db_run(db.set_widget_last_sent_date, user_id, date_str)
async def db_get_all_widget_users() -> list[dict]: return await db_run(db.get_all_widget_users)

# Memories
async def db_save_memory(user_id: int, key: str, value: str, category: str = "общее"): await db_run(db.save_memory, user_id, key, value, category)
async def db_get_memory(user_id: int, key: str) -> dict | None: return await db_run(db.get_memory, user_id, key)
async def db_get_all_memories(user_id: int) -> list[dict]: return await db_run(db.get_all_memories, user_id)
async def db_search_memories(user_id: int, query: str) -> list[dict]: return await db_run(db.search_memories, user_id, query)
async def db_update_memory_by_id(user_id: int, memory_id: int, key: str, value: str) -> bool: return await db_run(db.update_memory_by_id, user_id, memory_id, key, value)
async def db_set_memory_category(user_id: int, memory_id: int, category: str) -> bool: return await db_run(db.set_memory_category, user_id, memory_id, category)
async def db_delete_memory(user_id: int, key: str): await db_run(db.delete_memory, user_id, key)
async def db_delete_memory_by_id(user_id: int, memory_id: int): await db_run(db.delete_memory_by_id, user_id, memory_id)
async def db_clear_memories(user_id: int): await db_run(db.clear_memories, user_id)
async def db_count_memories(user_id: int) -> int: return await db_run(db.count_memories, user_id)

# Access Control
async def db_allow_user(user_id: int, allowed_by: int): await db_run(db.allow_user, user_id, allowed_by)
async def db_disallow_user(user_id: int): await db_run(db.disallow_user, user_id)
async def db_is_user_allowed(user_id: int) -> bool: return await db_run(db.is_user_allowed, user_id)
async def db_get_allowed_users() -> list[dict]: return await db_run(db.get_allowed_users)
async def db_get_lockdown() -> bool: return await db_run(db.get_lockdown)
async def db_set_lockdown(enabled: bool): await db_run(db.set_lockdown, enabled)

# Error Logs
async def db_log_error(user_id: int, level: str, message: str, traceback: str = ""): await db_run(db.log_error, user_id, level, message, traceback)
async def db_get_unread_errors_count() -> int: return await db_run(db.get_unread_errors_count)
async def db_get_recent_errors(limit: int = 20) -> list[dict]: return await db_run(db.get_recent_errors, limit)
async def db_mark_errors_read(): await db_run(db.mark_errors_read)
async def db_cleanup_old_errors(days: int = 30): await db_run(db.cleanup_old_errors, days)

# Supplies
async def db_save_supply(user_id: int, name: str, quantity: int = 0, min_quantity: int = 0, normal_quantity: int = 0) -> int:
    return await db_run(db.save_supply, user_id, name, quantity, min_quantity, normal_quantity)
async def db_update_supply_min_quantity(user_id: int, supply_id: int, min_quantity: int): await db_run(db.update_supply_min_quantity, user_id, supply_id, min_quantity)
async def db_update_supply_normal_quantity(user_id: int, supply_id: int, normal_quantity: int): await db_run(db.update_supply_normal_quantity, user_id, supply_id, normal_quantity)
async def db_get_supplies(user_id: int) -> list[dict]: return await db_run(db.get_supplies, user_id)
async def db_get_supply(user_id: int, supply_id: int) -> dict | None: return await db_run(db.get_supply, user_id, supply_id)
async def db_update_supply_name(user_id: int, supply_id: int, new_name: str): await db_run(db.update_supply_name, user_id, supply_id, new_name)
async def db_update_supply_quantity(user_id: int, supply_id: int, quantity: int): await db_run(db.update_supply_quantity, user_id, supply_id, quantity)
async def db_update_supply_photo(user_id: int, supply_id: int, file_id: str, file_type: str = 'photo'): await db_run(db.update_supply_photo, user_id, supply_id, file_id, file_type)
async def db_delete_supply(user_id: int, supply_id: int): await db_run(db.delete_supply, user_id, supply_id)
async def db_supply_exists(user_id: int, name: str) -> bool: return await db_run(db.supply_exists, user_id, name)
async def db_update_supply_sort_order(user_id: int, supply_id: int, sort_order: int): await db_run(db.update_supply_sort_order, user_id, supply_id, sort_order)

# Supply Tags
async def db_get_or_create_supply_tag(user_id: int, name: str) -> int: return await db_run(db.get_or_create_supply_tag, user_id, name)
async def db_get_supply_tags(user_id: int, supply_id: int) -> list[dict]: return await db_run(db.get_supply_tags, user_id, supply_id)
async def db_get_supply_tags_with_counts(user_id: int) -> list[dict]: return await db_run(db.get_supply_tags_with_counts, user_id)
async def db_get_supplies_by_tag(user_id: int, tag_id: int) -> list[dict]: return await db_run(db.get_supplies_by_tag, user_id, tag_id)
async def db_add_supply_tag(user_id: int, supply_id: int, tag_name: str): await db_run(db.add_supply_tag, user_id, supply_id, tag_name)
async def db_remove_supply_tag(user_id: int, supply_id: int, tag_id: int): await db_run(db.remove_supply_tag, user_id, supply_id, tag_id)
async def db_get_supply_tag(user_id: int, tag_id: int) -> dict | None: return await db_run(db.get_supply_tag, user_id, tag_id)

# Birthdays
async def db_get_birthdays(user_id: int) -> list[dict]: return await db_run(db.get_birthdays, user_id)
async def db_save_birthday(user_id: int, name: str, birth_date: str) -> int: return await db_run(db.save_birthday, user_id, name, birth_date)
async def db_update_birthday(user_id: int, bday_id: int, name: str, birth_date: str): await db_run(db.update_birthday, user_id, bday_id, name, birth_date)
async def db_delete_birthday(user_id: int, bday_id: int): await db_run(db.delete_birthday, user_id, bday_id)
async def db_birthday_exists(user_id: int, name: str) -> bool: return await db_run(db.birthday_exists, user_id, name)
async def db_get_birthday_time(user_id: int) -> str: return await db_run(db.get_birthday_time, user_id)
async def db_set_birthday_time(user_id: int, time_str: str): await db_run(db.set_birthday_time, user_id, time_str)
async def db_get_birthday_advance(user_id: int) -> bool: return await db_run(db.get_birthday_advance, user_id)
async def db_set_birthday_advance(user_id: int, enabled: bool): await db_run(db.set_birthday_advance, user_id, enabled)
async def db_get_all_birthday_user_ids() -> list[int]: return await db_run(db.get_all_birthday_user_ids)
