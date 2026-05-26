"""
Скрипт для обновления эмодзи всех существующих элементов списков.
Запустить один раз: python update_emojis.py
"""
import sys
import os

# Добавляем путь к проекту
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import _conn, init_db
from ai import init_ai, _suggest_emoji, groq_client
from dotenv import load_dotenv
import time

load_dotenv()

def main():
    import logging
    logging.basicConfig(level=logging.INFO)

    groq_key = os.getenv("GROQ_KEY")
    tavily_key = os.getenv("TAVILY_KEY", "")
    print(f"GROQ_KEY: {'*' * 10} (len={len(groq_key)})")
    print(f"TAVILY_KEY: {'*' * 5 if tavily_key else 'NOT SET'}")

    if not groq_key:
        print("❌ Не найден GROQ_KEY в .env")
        return

    init_ai(groq_key, tavily_key)
    print(f"Groq initialized: {groq_client}")
    if not groq_client:
        print("❌ Groq не инициализирован")
        return

    init_db()

    with _conn() as conn:
        items = conn.execute("SELECT id, item FROM list_items WHERE emoji IS NULL OR emoji = '📌'").fetchall()
        total = len(items)

        if total == 0:
            print("✅ Все элементы уже имеют эмодзи")
            return

        print(f"🔄 Найдено {total} элементов для обновления...")

        for i, row in enumerate(items):
            item_id = row["id"]
            item_text = row["item"]

            emoji = _suggest_emoji(item_text)
            conn.execute("UPDATE list_items SET emoji=? WHERE id=?", (emoji, item_id))
            print(f"  [{i+1}/{total}] {emoji} {item_text}")

            if (i + 1) % 10 == 0:
                conn.commit()
                print(f"  💾 Сохранено {i+1} записей...")

            time.sleep(0.5)  # Не спамить API

    print(f"✅ Готово! Обновлено {total} элементов")


if __name__ == "__main__":
    main()