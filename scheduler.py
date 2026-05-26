"""Background jobs registration for the bot."""
import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

from db import db_cleanup_old_errors, db_get_documents_to_refresh
from handlers.processors.birthdays import check_birthdays
from handlers.processors.daily_summary import send_daily_summaries
from handlers.reminders import tag_existing_reminders
from handlers.session import register_message
from utils import _pad, fire_and_forget

logger = logging.getLogger(__name__)


def do_backup():
    """Создание backup базы данных."""
    db_path = "bot.db"
    if not os.path.exists(db_path):
        return
    backup_dir = "backups"
    os.makedirs(backup_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(backup_dir, f"bot_{timestamp}.db")
    try:
        shutil.copy2(db_path, backup_path)
        logger.info(f"Backup создан: {backup_path}")
    except Exception as e:
        logger.error(f"Backup failed: {e}")


def run_in_background(coro):
    """Запустить корутину из синхронного callback планировщика."""
    return fire_and_forget(coro)


def run_blocking_in_background(func, *args):
    """Выполнить блокирующую сервисную задачу, не останавливая event loop."""
    return run_in_background(asyncio.to_thread(func, *args))


def next_daily_time(hour: int, minute: int = 0, now: datetime | None = None):
    """Вернуть ближайшее время запуска ежедневной задачи."""
    now = now or datetime.now()
    run_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if run_at <= now:
        run_at += timedelta(days=1)
    return run_at.time()


async def check_documents_refresh(app: Application):
    """Проверяет и предлагает обновить файлы."""
    docs = await db_get_documents_to_refresh(None, days=25)
    if not docs:
        return

    user_docs = {}
    for doc in docs:
        user_docs.setdefault(doc["user_id"], []).append(doc)

    for user_id, user_doc_list in user_docs.items():
        count = len(user_doc_list)
        try:
            msg = await app.bot.send_message(
                chat_id=user_id,
                text=_pad(f"📁 У тебя {count} файл(ов), которые не обновлялись более 25 дней.\n\nХочешь обновить их сейчас?"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Обновить", callback_data="refresh_all_docs")],
                    [InlineKeyboardButton("❌ Позже", callback_data="snooze_docs_refresh")],
                ])
            )
            register_message(user_id, user_id, msg.message_id)
            logger.info(f"Отправлено напоминание обновить {count} файлов пользователю {user_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить напоминание пользователю {user_id}: {e}")


def register_jobs(app: Application, restore_reminders):
    """Зарегистрировать все фоновые задачи бота."""
    app.job_queue.run_once(lambda ctx: run_in_background(restore_reminders(app)), when=2)
    app.job_queue.run_once(lambda ctx: run_blocking_in_background(tag_existing_reminders), when=3)

    app.job_queue.run_daily(lambda ctx: run_blocking_in_background(do_backup), next_daily_time(3))
    app.job_queue.run_daily(lambda ctx: run_in_background(db_cleanup_old_errors(30)), next_daily_time(4))
    app.job_queue.run_daily(lambda ctx: run_in_background(check_documents_refresh(app)), next_daily_time(10))

    app.job_queue.run_repeating(lambda ctx: run_in_background(check_birthdays(app)), interval=60, first=10)
    app.job_queue.run_repeating(
        lambda ctx: run_in_background(send_daily_summaries(app)),
        interval=60,
        first=10,
    )
