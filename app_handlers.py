"""Telegram command and update handler registration."""
import logging
import traceback

from telegram import BotCommand
from telegram.ext import CallbackQueryHandler, CommandHandler, MessageHandler, filters

from handlers.callbacks import button_handler
from handlers.commands import (
    cmd_addlist,
    cmd_allow,
    cmd_cancel,
    cmd_disallow,
    cmd_done,
    cmd_export,
    cmd_lock,
    cmd_lockdown,
    cmd_logs,
    cmd_milk,
    cmd_new,
    cmd_rub,
    cmd_setpin,
    cmd_share,
    cmd_shared,
    cmd_showlists,
    cmd_start,
    cmd_status,
    cmd_timer,
    cmd_unshare,
    cmd_whitelist,
    shortcut_handler,
)
from handlers.inline import inline_handler
from shortcuts import SHORTCUTS

logger = logging.getLogger(__name__)


async def set_commands(app):
    commands = [
        BotCommand("start", "Запустить бота и очистить чат"),
        BotCommand("help", "Помощь"),
        BotCommand("rub", "Курс рубля"),
        BotCommand("t", "Таймер (секунды)"),
        BotCommand("al", "Создать список"),
        BotCommand("sls", "Мои списки"),
        BotCommand("shared", "Списки со мной"),
        BotCommand("share", "Поделиться списком"),
        BotCommand("unshare", "Отозвать доступ"),
        BotCommand("status", "Статус бота"),
        BotCommand("export", "Экспорт данных"),
        BotCommand("cancel", "Отменить текущее действие"),
        BotCommand("done", "Завершить текущий процесс"),
        BotCommand("milk", "Молочник"),
        BotCommand("setpin", "Установить PIN-код"),
        BotCommand("lock", "Заблокировать доступ"),
        BotCommand("allow", "Разрешить доступ пользователю"),
        BotCommand("disallow", "Запретить доступ пользователю"),
        BotCommand("whitelist", "Список разрешённых пользователей"),
        BotCommand("lockdown", "Вкл/выкл режим ограничения доступа"),
    ]
    await app.bot.delete_my_commands()
    await app.bot.set_my_commands(commands)


async def error_handler(update, context):
    """Log unhandled exceptions and keep callback queries quiet."""
    logger.error("Exception while handling an update:", exc_info=context.error)

    user_id = 0
    if update and hasattr(update, "effective_user") and update.effective_user:
        user_id = update.effective_user.id

    err_text = str(context.error)[:500]
    tb_text = "".join(
        traceback.format_exception(
            type(context.error),
            context.error,
            context.error.__traceback__,
        )
    )[:2000]

    from db import db_log_error
    await db_log_error(user_id, "ERROR", err_text, tb_text)

    if update and hasattr(update, "callback_query") and update.callback_query:
        try:
            await update.callback_query.answer("⚠️ Ошибка", show_alert=False)
        except Exception:
            pass


def register_handlers(app, handle_message):
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_start))
    app.add_handler(CommandHandler("rub", cmd_rub))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("t", cmd_timer))
    app.add_handler(CommandHandler("timer", cmd_timer))
    app.add_handler(CommandHandler("al", cmd_addlist))
    app.add_handler(CommandHandler("sls", cmd_showlists))
    app.add_handler(CommandHandler("shared", cmd_shared))
    app.add_handler(CommandHandler("share", cmd_share))
    app.add_handler(CommandHandler("unshare", cmd_unshare))
    app.add_handler(CommandHandler("milk", cmd_milk))
    app.add_handler(CommandHandler("setpin", cmd_setpin))
    app.add_handler(CommandHandler("lock", cmd_lock))
    app.add_handler(CommandHandler("allow", cmd_allow))
    app.add_handler(CommandHandler("disallow", cmd_disallow))
    app.add_handler(CommandHandler("whitelist", cmd_whitelist))
    app.add_handler(CommandHandler("lockdown", cmd_lockdown))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CallbackQueryHandler(button_handler))

    for command in SHORTCUTS:
        app.add_handler(CommandHandler(command, shortcut_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(
        filters.PHOTO
        | filters.Document.ALL
        | filters.FORWARDED
        | filters.VOICE
        | filters.VIDEO
        | filters.AUDIO
        | filters.ANIMATION
        | filters.Sticker.ALL
        | filters.VIDEO_NOTE,
        handle_message,
    ))
    app.add_handler(MessageHandler(filters.LOCATION, handle_message))
    app.add_handler(inline_handler)
    app.add_error_handler(error_handler)
