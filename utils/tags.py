"""Unified tag management system.

Предоставляет единый TagManager для всех доменов (документы, элементы списков,
заметки, напоминания, локации). Каждый экземпляр работает со своей парой таблиц:

    {tag_table}: id, user_id, name, normalized_name, created_at
    {link_table}: {fk_column}, tag_id (M:N связь)
"""

import sqlite3
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def normalize_tag_name(name: str) -> str:
    """Нормализовать название тега для сравнения уникальности."""
    value = " ".join(str(name or "").lower().replace("ё", "е").split())
    for suffix in ("ами", "ями", "ах", "ях", "ов", "ев", "ей",
                   "ые", "ие", "ый", "ий", "ая", "яя", "ое", "ее",
                   "ы", "и", "а", "я"):
        if len(value) > len(suffix) + 3 and value.endswith(suffix):
            return value[:-len(suffix)]
    return value or "разн"


def _get_connection():
    """Контекстный менеджер соединения с БД (импорт внутри для избежания циклов)."""
    from db import Database
    return Database._conn()


class TagManager:
    """Generic tag manager for any domain.

    Args:
        tag_table: Имя таблицы тегов (напр. 'note_tags')
        link_table: Имя таблицы связей (напр. 'note_tag_links')
        fk_column: Имя внешнего ключа в link_table (напр. 'note_id')
        user_fk_column: Имя колонки user_id в основной таблице (для ensure_default)
    """

    def __init__(self, tag_table: str, link_table: str, fk_column: str,
                 user_fk_column: str = "user_id"):
        self.tag_table = tag_table
        self.link_table = link_table
        self.fk_column = fk_column
        self.user_fk_column = user_fk_column

    # ── Нормализация ─────────────────────────────────────────────────────

    def normalize(self, name: str) -> str:
        return normalize_tag_name(name)

    # ── Внутренние методы (требуют con) ──────────────────────────────────

    def _get_or_create_tag(self, con: sqlite3.Connection, user_id: int, name: str) -> int:
        tag_name = " ".join(str(name or "").strip().split()) or "разное"
        normalized = self.normalize(tag_name)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = con.execute(
            f"INSERT OR IGNORE INTO {self.tag_table}(user_id, name, normalized_name, created_at) VALUES(?,?,?,?)",
            (user_id, tag_name, normalized, now)
        )
        if cur.lastrowid:
            return int(cur.lastrowid)
        row = con.execute(
            f"SELECT id FROM {self.tag_table} WHERE user_id=? AND normalized_name=?",
            (user_id, normalized)
        ).fetchone()
        return int(row["id"])

    def _ensure_has_tag(self, con: sqlite3.Connection, user_id: int, obj_id: int):
        row = con.execute(
            f"SELECT 1 FROM {self.link_table} WHERE {self.fk_column}=? LIMIT 1",
            (obj_id,)
        ).fetchone()
        if row:
            return
        tag_id = self._get_or_create_tag(con, user_id, "разное")
        con.execute(
            f"INSERT OR IGNORE INTO {self.link_table}({self.fk_column}, tag_id) VALUES(?,?)",
            (obj_id, tag_id)
        )

    def _set_tags(self, con: sqlite3.Connection, user_id: int, obj_id: int,
                  tags: list[str] | None):
        tag_names = [str(t).strip() for t in (tags or []) if str(t).strip()]
        if not tag_names:
            tag_names = ["разное"]
        con.execute(f"DELETE FROM {self.link_table} WHERE {self.fk_column}=?", (obj_id,))
        for tag_name in tag_names:
            tag_id = self._get_or_create_tag(con, user_id, tag_name)
            con.execute(
                f"INSERT OR IGNORE INTO {self.link_table}({self.fk_column}, tag_id) VALUES(?,?)",
                (obj_id, tag_id)
            )
        self._ensure_has_tag(con, user_id, obj_id)

    def _ensure_default_tags(self, con: sqlite3.Connection, main_table: str):
        """Пробежать все записи в main_table и гарантировать тег 'разное'."""
        rows = con.execute(
            f"SELECT id, {self.user_fk_column} FROM {main_table}"
        ).fetchall()
        for row in rows:
            self._ensure_has_tag(con, int(row[self.user_fk_column]), int(row["id"]))

    def cleanup_orphaned(self, con: sqlite3.Connection):
        con.execute(f"""
            DELETE FROM {self.tag_table} WHERE id NOT IN (
                SELECT DISTINCT tag_id FROM {self.link_table}
            )
        """)

    # ── Публичные методы ────────────────────────────────────────────────

    def set_tags(self, user_id: int, obj_id: int, tags: list[str] | None,
                 con: Optional[sqlite3.Connection] = None):
        if con is not None:
            self._set_tags(con, user_id, obj_id, tags)
        else:
            with _get_connection() as con:
                self._set_tags(con, user_id, obj_id, tags)

    def get_tags(self, user_id: int, obj_id: int) -> list[dict]:
        with _get_connection() as con:
            self._ensure_has_tag(con, user_id, obj_id)
            rows = con.execute(f"""
                SELECT t.* FROM {self.tag_table} t
                JOIN {self.link_table} tl ON tl.tag_id = t.id
                WHERE t.user_id=? AND tl.{self.fk_column}=?
                ORDER BY t.name
            """, (user_id, obj_id)).fetchall()
            return [dict(r) for r in rows]

    def get_tags_with_counts(self, user_id: int) -> list[dict]:
        with _get_connection() as con:
            rows = con.execute(f"""
                SELECT t.id, t.user_id, t.name, t.normalized_name, t.created_at,
                       COUNT(tl.{self.fk_column}) AS count
                FROM {self.tag_table} t
                LEFT JOIN {self.link_table} tl ON tl.tag_id = t.id
                WHERE t.user_id=?
                GROUP BY t.id
                ORDER BY LOWER(t.name)
            """, (user_id,)).fetchall()
            return [dict(r) for r in rows]

    def get_tags_by_ids(self, user_id: int, obj_ids: list[int]) -> dict[int, list[dict]]:
        """Получить теги для нескольких объектов одним запросом.
        Возвращает {obj_id: [tag, ...]}.
        """
        if not obj_ids:
            return {}
        with _get_connection() as con:
            placeholders = ",".join("?" for _ in obj_ids)
            rows = con.execute(f"""
                SELECT tl.{self.fk_column} AS obj_id,
                       t.id, t.user_id, t.name, t.normalized_name, t.created_at
                FROM {self.tag_table} t
                JOIN {self.link_table} tl ON tl.tag_id = t.id
                WHERE t.user_id=? AND tl.{self.fk_column} IN ({placeholders})
                ORDER BY t.name
            """, (user_id, *obj_ids)).fetchall()
            result: dict[int, list[dict]] = {}
            for row in rows:
                oid = int(row["obj_id"])
                if oid not in result:
                    result[oid] = []
                result[oid].append(dict(row))
            return result

    def add_tag(self, user_id: int, obj_id: int, tag_name: str):
        with _get_connection() as con:
            tag_id = self._get_or_create_tag(con, user_id, tag_name)
            con.execute(
                f"INSERT OR IGNORE INTO {self.link_table}({self.fk_column}, tag_id) VALUES(?,?)",
                (obj_id, tag_id)
            )

    def remove_tag(self, user_id: int, obj_id: int, tag_id: int):
        with _get_connection() as con:
            con.execute(
                f"DELETE FROM {self.link_table} WHERE {self.fk_column}=? AND tag_id=?",
                (obj_id, tag_id)
            )
            self._ensure_has_tag(con, user_id, obj_id)

    def get_tag(self, user_id: int, tag_id: int) -> dict | None:
        with _get_connection() as con:
            row = con.execute(
                f"SELECT * FROM {self.tag_table} WHERE id=? AND user_id=?",
                (tag_id, user_id)
            ).fetchone()
            return dict(row) if row else None

    def rename_tag(self, user_id: int, tag_id: int, new_name: str) -> dict | None:
        tag_name = " ".join(str(new_name or "").strip().split())
        if not tag_name:
            return None
        normalized = self.normalize(tag_name)
        with _get_connection() as con:
            current = con.execute(
                f"SELECT * FROM {self.tag_table} WHERE id=? AND user_id=?",
                (tag_id, user_id)
            ).fetchone()
            if not current:
                return None
            # Проверка дубликата normalized_name
            existing = con.execute(
                f"SELECT * FROM {self.tag_table} WHERE user_id=? AND normalized_name=? AND id<>?",
                (user_id, normalized, tag_id)
            ).fetchone()
            if existing:
                existing_id = int(existing["id"])
                rows = con.execute(
                    f"SELECT {self.fk_column} FROM {self.link_table} WHERE tag_id=?",
                    (tag_id,)
                ).fetchall()
                for row in rows:
                    con.execute(
                        f"INSERT OR IGNORE INTO {self.link_table}({self.fk_column}, tag_id) VALUES(?,?)",
                        (row[self.fk_column], existing_id)
                    )
                con.execute(f"DELETE FROM {self.link_table} WHERE tag_id=?", (tag_id,))
                con.execute(f"DELETE FROM {self.tag_table} WHERE id=? AND user_id=?",
                          (tag_id, user_id))
                return dict(existing)
            con.execute(
                f"UPDATE {self.tag_table} SET name=?, normalized_name=? WHERE id=? AND user_id=?",
                (tag_name, normalized, tag_id, user_id)
            )
            row = con.execute(
                f"SELECT * FROM {self.tag_table} WHERE id=? AND user_id=?",
                (tag_id, user_id)
            ).fetchone()
            return dict(row) if row else None

    def delete_tag(self, user_id: int, tag_id: int):
        """Полностью удалить тег и все его связи."""
        with _get_connection() as con:
            con.execute(f"DELETE FROM {self.link_table} WHERE tag_id=?", (tag_id,))
            con.execute(f"DELETE FROM {self.tag_table} WHERE id=? AND user_id=?", (tag_id, user_id))
