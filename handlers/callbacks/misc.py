"""Miscellaneous callback handlers (not tied to a specific domain)."""
import asyncio
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.callbacks.base import domain_handler, _delete_ok_messages

logger = logging.getLogger(__name__)


@domain_handler
async def handle_misc_callbacks(query, context, data, user, chat_id, bot):
    if data == "noop":
        return True

    if data.startswith("status_ok_"):
        try:
            command_message_id = int(data.split("_")[2])
        except (IndexError, ValueError):
            command_message_id = 0
        await _delete_ok_messages(bot, chat_id, query.message.message_id, command_message_id)
        return True

    if data.startswith("rub_ok_"):
        await _delete_ok_messages(bot, chat_id, query.message.message_id)
        return True

    if data == "search_ok":
        await _delete_ok_messages(bot, chat_id, query.message.message_id)
        return True

    if data.startswith("lockdown_ok_"):
        try:
            command_message_id = int(data.split("_")[-1])
        except (IndexError, ValueError):
            command_message_id = 0
        await _delete_ok_messages(bot, chat_id, query.message.message_id, command_message_id)
        return True

    if data.startswith("allow_ok_"):
        try:
            command_message_id = int(data.split("_")[-1])
        except (IndexError, ValueError):
            command_message_id = 0
        await _delete_ok_messages(bot, chat_id, query.message.message_id, command_message_id)
        return True

    if data.startswith("disallow_ok_"):
        try:
            command_message_id = int(data.split("_")[-1])
        except (IndexError, ValueError):
            command_message_id = 0
        await _delete_ok_messages(bot, chat_id, query.message.message_id, command_message_id)
        return True

    if data.startswith("whitelist_ok_"):
        try:
            command_message_id = int(data.split("_")[-1])
        except (IndexError, ValueError):
            command_message_id = 0
        await _delete_ok_messages(bot, chat_id, query.message.message_id, command_message_id)
        return True

    if data == "milk_ok":
        await query.answer()
        logger.info(f"MILK OK: chat={chat_id}, msg={query.message.message_id}")
        await _delete_ok_messages(bot, chat_id, query.message.message_id)
        logger.info("MILK: сообщение удалено")
        return True

    if data == "go_menu":
        from handlers.session import finish_process
        from keyboards import show_main_menu
        await finish_process(bot, user.id, show_menu=False)
        from handlers.message_cache import main_menu_messages
        main_menu_messages[user.id] = query.message.message_id
        await show_main_menu(bot, user.id)
        return True

    if data == "open_rub":
        from db import db_get_summa
        from ai import _fetch_rub_direct, _fetch_usd_direct
        from handlers.session import register_message
        from utils import _pad
        msg = await bot.send_message(chat_id=chat_id, text=_pad("💱 Получаю курсы валют..."))
        register_message(user.id, chat_id, msg.message_id)
        ok_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("OK", callback_data=f"rub_ok_{msg.message_id}")
        ]])
        try:
            summa = await db_get_summa(user.id)

            rub_task = asyncio.wait_for(
                asyncio.to_thread(_fetch_rub_direct, summa), timeout=25.0
            )
            usd_task = asyncio.wait_for(
                asyncio.to_thread(_fetch_usd_direct, summa), timeout=25.0
            )
            rub_result, usd_result = await asyncio.gather(rub_task, usd_task, return_exceptions=True)

            parts = []
            if isinstance(rub_result, Exception):
                logger.error(f"RUB error: {rub_result}")
                parts.append(_pad("⚠️ RUB: не удалось получить курс"))
            else:
                parts.append(rub_result.strip())

            if isinstance(usd_result, Exception):
                logger.error(f"USD error: {usd_result}")
                parts.append(_pad("⚠️ USD: не удалось получить курс"))
            else:
                parts.append(usd_result.strip())

            final_text = "\n\n".join(parts)

            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg.message_id,
                text=final_text, parse_mode="Markdown", reply_markup=ok_markup
            )
        except asyncio.TimeoutError:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg.message_id,
                text=_pad("⏰ Сайт не ответил вовремя."), reply_markup=ok_markup
            )
        except Exception as e:
            logger.error(f"Currency error: {e}")
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg.message_id,
                text=_pad("⚠️ Не удалось получить курс."), reply_markup=ok_markup
            )
        return True

    if data == "open_summa":
        from db import db_get_summa
        from handlers.session import start_process
        from keyboards import btn_cancel, btn_menu
        from utils import _pad
        summa = await db_get_summa(user.id)
        if summa is not None:
            text = _pad(f"💰 *Текущая сумма:* `{int(summa):,}` сум".replace(",", " "))
            keyboard = [[InlineKeyboardButton("✏️ Изменить", callback_data="change_summa"), btn_menu()]]
        else:
            text = "💰 Сумма не задана. Введи сумму (в сумах):"
            keyboard = [[btn_cancel()]]
            start_process(user.id, chat_id, "summa", {"step": "waiting_summa"}, query.message.message_id)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    if data == "change_summa":
        from handlers.session import start_process
        from keyboards import btn_cancel
        from utils import _pad
        start_process(user.id, chat_id, "summa", {"step": "waiting_summa"}, query.message.message_id)
        await query.edit_message_text(_pad("✏️ Введи новую сумму (в сумах):"), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        return True

    if data == "open_search":
        from handlers.session import start_process
        from keyboards import btn_cancel
        from utils import _pad
        start_process(user.id, chat_id, "search", {"step": "waiting_query"}, query.message.message_id)
        await query.edit_message_text(_pad("🔍 Введи запрос для поиска:"), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        return True

    if data == "do_clean":
        from ai import history_clear
        from handlers.message_cache import cleanup_all_messages
        from keyboards import show_main_menu
        history_clear(user.id)
        from handlers.processors import processes
        if user.id in processes:
            del processes[user.id]
        await cleanup_all_messages(bot, user.id, chat_id)
        await show_main_menu(bot, user.id, "🧹 Чистота! История диалога очищена.")
        return True

    if data == "dismiss_summary":
        await _delete_ok_messages(bot, chat_id, query.message.message_id)
        return True

    if data == "dismiss_notify":
        await _delete_ok_messages(bot, chat_id, query.message.message_id)
        return True

    return False
