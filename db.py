"""Database module for SQLite operations."""
import sqlite3
import logging
from datetime import datetime
from typing import Any

DB_PATH = "bot.db"
logger = logging.getLogger(__name__)


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def init_db():
    with _conn() as con:
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
                created_at TEXT
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
                created_at TEXT,
                delivered INTEGER DEFAULT 0
            );
        """)
        _ensure_column(con, "reminders", "repeat_type", "TEXT DEFAULT 'none'")
        _ensure_column(con, "reminders", "created_at", "TEXT")
        _ensure_column(con, "reminders", "delivered", "INTEGER DEFAULT 0")
    logger.info("✅ SQLite БД инициализирована")


def _ensure_column(con: sqlite3.Connection, table: str, column: str, definition: str):
    columns = [row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# ─── Users ───────────────────────────────────────────────────────────────────

def db_get_user(user_id: int) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def db_upsert_user(user_id: int, name: str):
    with _conn() as con:
        con.execute(
            "INSERT INTO users(user_id, name) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET name=excluded.name",
            (user_id, name)
        )


def db_count_users() -> int:
    with _conn() as con:
        row = con.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return int(row["count"])


# ─── Lists ───────────────────────────────────────────────────────────────────

def db_create_list(list_id: str, ltype: str, name: str, created_by: int):
    with _conn() as con:
        con.execute(
            "INSERT INTO lists(list_id, type, name, created_by, created_at) VALUES(?,?,?,?,?)",
            (list_id, ltype, name, created_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
    logger.info(f"🧾 LIST SAVED: id={list_id} | type={ltype} | name={name}")


def db_get_lists_for_user(user_id: int) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM lists WHERE created_by=? ORDER BY created_at", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def db_get_list(list_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM lists WHERE list_id=?", (list_id,)).fetchone()
        return dict(row) if row else None


def db_delete_list(list_id: str):
    with _conn() as con:
        con.execute("DELETE FROM lists WHERE list_id=?", (list_id,))
        con.execute("DELETE FROM list_items WHERE list_id=?", (list_id,))


def db_count_lists() -> int:
    with _conn() as con:
        row = con.execute("SELECT COUNT(*) AS count FROM lists").fetchone()
        return int(row["count"])


# ─── List Items ───────────────────────────────────────────────────────────────

def db_add_item(list_id: str, user_id: int, item: str):
    with _conn() as con:
        con.execute(
            "INSERT INTO list_items(list_id, user_id, item, created_at) VALUES(?,?,?,?)",
            (list_id, user_id, item, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )


def db_get_items(list_id: str) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM list_items WHERE list_id=? ORDER BY id", (list_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def db_delete_item_by_index(list_id: str, index: int):
    with _conn() as con:
        rows = con.execute(
            "SELECT id FROM list_items WHERE list_id=? ORDER BY id", (list_id,)
        ).fetchall()
        if index >= len(rows):
            return
        row_id = rows[index]["id"]
        con.execute("DELETE FROM list_items WHERE id=?", (row_id,))


# ─── Summa ────────────────────────────────────────────────────────────────────

def db_get_summa(user_id: int) -> float | None:
    with _conn() as con:
        row = con.execute("SELECT value FROM summa WHERE user_id=?", (user_id,)).fetchone()
        return row["value"] if row else None


def db_set_summa(user_id: int, value: float):
    with _conn() as con:
        con.execute(
            "INSERT INTO summa(user_id, value) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET value=excluded.value",
            (user_id, value)
        )


# ─── Reminders ────────────────────────────────────────────────────────────────

def db_save_reminder(
    chat_id: int,
    rid: int,
    text: str,
    fire_at: datetime,
    is_timer: bool = False,
    repeat_type: str = "none",
):
    with _conn() as con:
        con.execute(
            """
            INSERT INTO reminders(chat_id, rid, text, fire_at, is_timer, repeat_type, created_at, delivered)
            VALUES(?,?,?,?,?,?,?,0)
            """,
            (
                chat_id, rid, text,
                fire_at.strftime("%Y-%m-%d %H:%M:%S"),
                int(is_timer), repeat_type,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
        )


def db_delete_reminder(chat_id: int, rid: int):
    with _conn() as con:
        con.execute("DELETE FROM reminders WHERE chat_id=? AND rid=?", (chat_id, rid))


def db_get_reminder(chat_id: int, rid: int) -> dict | None:
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM reminders WHERE chat_id=? AND rid=?", (chat_id, rid)
        ).fetchone()
        return dict(row) if row else None


def db_update_reminder(chat_id: int, rid: int, **fields: Any):
    allowed = {"text", "fire_at", "is_timer", "repeat_type", "delivered"}
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
    with _conn() as con:
        con.execute(
            f"UPDATE reminders SET {', '.join(updates)} WHERE chat_id=? AND rid=?",
            values
        )


def db_get_pending_reminders() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM reminders ORDER BY fire_at").fetchall()
        return [dict(r) for r in rows]


def db_get_reminder_counts() -> dict:
    with _conn() as con:
        rows = con.execute("""
            SELECT
                SUM(CASE WHEN is_timer=1 THEN 1 ELSE 0 END) AS timers,
                SUM(CASE WHEN is_timer=0 AND COALESCE(repeat_type,'none')='none' AND COALESCE(delivered,0)=0 THEN 1 ELSE 0 END) AS once,
                SUM(CASE WHEN is_timer=0 AND COALESCE(delivered,0)=1 THEN 1 ELSE 0 END) AS delivered,
                SUM(CASE WHEN is_timer=0 AND repeat_type='daily' THEN 1 ELSE 0 END) AS daily,
                SUM(CASE WHEN is_timer=0 AND repeat_type='monthly' THEN 1 ELSE 0 END) AS monthly,
                SUM(CASE WHEN is_timer=0 AND repeat_type='yearly' THEN 1 ELSE 0 END) AS yearly
            FROM reminders
        """).fetchone()
        return {key: int(rows[key] or 0) for key in rows.keys()}
