"""Command handlers."""
import asyncio
import io
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    db_upsert_user, db_get_lists_for_user, db_get_items, db_get_list,
    db_get_summa, db_share_list, db_get_shared_lists, db_get_list_members,
    db_is_list_member, db_get_user,
)
from handlers.session import (
    register_message, start_process, finish_process,
    processes,
)

from keyboards import btn_menu, btn_cancel, show_main_menu
from utils.time_utils import (
    parse_duration_seconds,
)
from utils.list_display import format_list_display
from ai import (
    do_search, _fetch_rub_direct,
    _fetch_usd_direct,
)
from shortcuts import SHORTCUTS
from export_data import (
    build_export_payload,
    export_filename,
    payload_to_csv_zip_bytes,
    payload_to_json_bytes,
)
from health import build_status_text
from utils import md, _pad, fire_and_forget

logger = logging.getLogger(__name__)


# ─── Auth helper ──────────────────────────────────────────────────────────────

async def _check_auth(update) -> bool:
    """Вернуть True если пользователь авторизован, иначе ответить и вернуть False."""
    from utils import is_authorized
    user = update.effective_user
    chat_id = update.effective_chat.id
    if is_authorized(user.id):
        return True
    if update.message:
        msg = await update.message.reply_text(_pad("❌ Доступ запрещён. Обратитесь к администратору."))
        register_message(user.id, chat_id, msg.message_id)
    return False


# ─── Commands ─────────────────────────────────────────────────────────────────

async def cmd_start(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    await db_upsert_user(user.id, user.first_name)
    if update.message:
        register_message(user.id, chat_id, update.message.message_id)

    # Проверяем, есть ли параметр start ( invite)
    args = context.args
    if args and args[0].startswith("invite_"):
        list_id = args[0][7:]  # Убираем "invite_"
        lst = await db_get_list(list_id)

        if not lst:
            await show_main_menu(context.bot, user.id, "❌ Приглашение недействительно.")
            return

        # Проверяем, не является ли пользователь владельцем
        if lst["created_by"] == user.id:
            await show_main_menu(context.bot, user.id, "ℹ️ Это ваш список.")
            return

        # Проверяем, не уже есть ли доступ
        if await db_is_list_member(list_id, user.id):
            await show_main_menu(context.bot, user.id, f"ℹ️ У вас уже есть доступ к списку *{md(lst['name'])}*.")
            return

        # Добавляем доступ
        await db_share_list(list_id, user.id, "write")
        owner = await db_get_user(lst["created_by"])
        owner_name = owner.get("name", "Владелец") if owner else "Владелец"
        await show_main_menu(context.bot, user.id,
            f"✅ Вам предоставлен доступ к списку *{md(lst['name'])}* от {owner_name}.\n\n"
            f"Используйте /shared чтобы увидеть список.")
        return

    await finish_process(context.bot, user.id, show_menu=True)


async def cmd_cancel(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if update.message:
        register_message(user.id, chat_id, update.message.message_id)
    await finish_process(context.bot, user.id, show_menu=True, menu_text="✅ Действие отменено.")


async def cmd_status(update, context):
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    command_message_id = update.message.message_id if update.message else 0
    if update.message:
        register_message(user.id, chat_id, update.message.message_id)
    active_process = processes.get(user.id, {}).get("type", "нет")
    text = await build_status_text(active_process)
    await update.message.reply_text(
        _pad(text), parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("OK", callback_data=f"status_ok_{command_message_id}")
        ]])
    )


async def cmd_addlist(update, context):
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    await db_upsert_user(user.id, user.first_name)
    register_message(user.id, chat_id, update.message.message_id)
    start_process(user.id, chat_id, "list", {"step": "creating_list_name"}, update.message.message_id)
    msg = await update.message.reply_text(_pad("✏️ Введи название нового списка:"),
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )
    register_message(user.id, chat_id, msg.message_id)


async def cmd_showlists(update, context):
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    await db_upsert_user(user.id, user.first_name)
    register_message(user.id, chat_id, update.message.message_id)
    my_lists = await db_get_lists_for_user(user.id)
    shared_lists = await db_get_shared_lists(user.id)

    if not my_lists and not shared_lists:
        msg = await update.message.reply_text(_pad("📭 Списков пока нет. Создай через /al"))
        register_message(user.id, chat_id, msg.message_id)
        fire_and_forget(_auto_cleanup(context.bot, user.id, chat_id, msg.message_id, delay=5))
        return

    keyboard = []
    for lst in my_lists:
        items = await db_get_items(lst["list_id"])
        keyboard.append([InlineKeyboardButton(format_list_display(lst["name"], items), callback_data=f"openlist_{lst['list_id']}")])

    if shared_lists:
        for lst in shared_lists:
            items = await db_get_items(lst["list_id"])
            keyboard.append([InlineKeyboardButton(format_list_display(lst["name"], items), callback_data=f"openlist_{lst['list_id']}")])

    msg = await update.message.reply_text(
        _pad("📋 *Твои списки* и *списки с тобой:*"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    register_message(user.id, chat_id, msg.message_id)


async def cmd_shared(update, context):
    """Показать списки, которыми поделились со мной."""
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    await db_upsert_user(user.id, user.first_name)
    register_message(user.id, chat_id, update.message.message_id)

    lists = await db_get_shared_lists(user.id)

    if not lists:
        msg = await update.message.reply_text(
            _pad("📭 Списков, которыми с тобой поделились, пока нет."),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, msg.message_id)
        return

    keyboard = []
    for lst in lists:
        perm_icon = "📝" if lst["permission"] == "write" else "👁"
        owner_info = f" (от @{lst.get('shared_by', 'unknown')})"
        items = await db_get_items(lst["list_id"])
        keyboard.append([InlineKeyboardButton(
            f"{format_list_display(lst['name'], items)} {perm_icon}{owner_info}",
            callback_data=f"openlist_{lst['list_id']}"
        )])

    msg = await update.message.reply_text(
        _pad("📋 *Списки, которыми поделились с тобой:*"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    register_message(user.id, chat_id, msg.message_id)


async def cmd_share(update, context):
    """Поделиться списком с другим пользователем."""
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    if update.message:
        register_message(user.id, chat_id, update.message.message_id)

    # Проверяем, находимся ли мы в процессе выбора пользователя
    from handlers.session import processes
    proc = processes.get(user.id)
    if proc and proc.get("type") == "share" and update.message:
        # Пользователь отправил username для шеринга
        target_username = update.message.text.strip()
        list_id = proc.get("list_id")

        # Ищем пользователя по username (упрощённо — через username в БД)
        # TODO: можно добавить поиск по username или через Telegram API
        await update.message.reply_text(
            _pad("🤝 Запрос на добавление пользователя отправлен.\n"
                 "Пользователь должен также запустить бота командой /start."),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        from handlers.session import finish_process
        await finish_process(context.bot, user.id, show_menu=True)
        return

    # Парсим аргументы: /share [имя_списка] [имя_пользователя]
    args = context.args
    if len(args) < 1:
        msg = await update.message.reply_text(
            _pad("❌ Укажи название списка. Пример: /share Покупки @username"),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, msg.message_id)
        return

    list_name = " ".join(args[:-1]) if len(args) > 1 else args[0]
    target_username = args[-1] if len(args) > 1 else None

    # Ищем список
    lists = await db_get_lists_for_user(user.id)
    target_list = None
    for lst in lists:
        if lst["name"].lower() == list_name.lower():
            target_list = lst
            break

    if not target_list:
        msg = await update.message.reply_text(
            f"❌ Список \"{list_name}\" не найден.",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, msg.message_id)
        return

    if target_username:
        msg = await update.message.reply_text(
            f"🤝 Для шеринга с @{target_username} нужно, чтобы пользователь "
            f"также использовал бота. После этого список станет доступен.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Показать список", callback_data=f"openlist_{target_list['list_id']}")],
                [btn_cancel()],
            ])
        )
        register_message(user.id, chat_id, msg.message_id)
    else:
        members = await db_get_list_members(target_list["list_id"])
        members_text = "👥 *Участники списка:*\n\n"
        for m in members:
            name = m.get("name") or "Неизвестный"
            perm = m.get("permission", "read")
            perm_label = "владелец" if perm == "owner" else ("редактор" if perm == "write" else "читатель")
            members_text += f"• {name} — {perm_label}\n"

        msg = await update.message.reply_text(
            f"📋 *{md(target_list['name'])}*\n\n{members_text}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Добавить участника", callback_data=f"share_add_{target_list['list_id']}")],
                [InlineKeyboardButton("Назад", callback_data=f"openlist_{target_list['list_id']}")],
            ])
        )
        register_message(user.id, chat_id, msg.message_id)


async def cmd_unshare(update, context):
    """Отозвать доступ к списку."""
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    register_message(user.id, chat_id, update.message.message_id)

    args = context.args
    if not args:
        msg = await update.message.reply_text(
            "❌ Укажи название списка. Пример: /unshare Покупки",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, msg.message_id)
        return

    list_name = " ".join(args)

    # Ищем список среди своих
    lists = await db_get_lists_for_user(user.id)
    target_list = None
    for lst in lists:
        if lst["name"].lower() == list_name.lower():
            target_list = lst
            break

    if not target_list:
        msg = await update.message.reply_text(
            f"❌ Список \"{list_name}\" не найден.",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, msg.message_id)
        return

    members = await db_get_list_members(target_list["list_id"])
    # Фильтруем — только не владелец
    members = [m for m in members if m.get("permission") != "owner"]

    if not members:
        msg = await update.message.reply_text(
            "👥 Нет участников для удаления (только ты — владелец).",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, msg.message_id)
        return

    keyboard = []
    for m in members:
        name = m.get("name") or f"User {m['user_id']}"
        keyboard.append([InlineKeyboardButton(
            f"❌ Удалить {name}",
            callback_data=f"unshare_{target_list['list_id']}_{m['user_id']}"
        )])
    keyboard.append([btn_cancel()])

    msg = await update.message.reply_text(
        f"📋 *{md(target_list['name'])}* — выбери участника для удаления:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    register_message(user.id, chat_id, msg.message_id)


async def cmd_done(update, context):
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    register_message(user.id, chat_id, update.message.message_id)
    await finish_process(context.bot, user.id, show_menu=True, menu_text="✅ Готово!")


async def cmd_new(update, context):
    user = update.effective_user
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text(_pad("🧹 Используй /new для чистого старта"))
    register_message(user.id, chat_id, update.message.message_id)
    register_message(user.id, chat_id, msg.message_id)
    await asyncio.sleep(3)
    await finish_process(context.bot, user.id, show_menu=True)


async def cmd_rub(update, context):
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text(_pad("💱 Получаю курсы валют..."))
    register_message(user.id, chat_id, update.message.message_id)
    register_message(user.id, chat_id, msg.message_id)
    try:
        summa = await db_get_summa(user.id)

        # Запускаем оба запроса параллельно
        rub_task = asyncio.wait_for(
            asyncio.to_thread(_fetch_rub_direct, summa), timeout=25.0
        )
        usd_task = asyncio.wait_for(
            asyncio.to_thread(_fetch_usd_direct, summa), timeout=25.0
        )
        rub_result, usd_result = await asyncio.gather(rub_task, usd_task, return_exceptions=True)

        # Собираем результат
        parts = []
        if isinstance(rub_result, Exception):
            logger.error(f"RUB error: {rub_result}")
            parts.append("⚠️ RUB: не удалось получить курс")
        else:
            parts.append(rub_result)

        if isinstance(usd_result, Exception):
            logger.error(f"USD error: {usd_result}")
            parts.append("⚠️ USD: не удалось получить курс")
        else:
            parts.append(usd_result)

        final = "\n\n".join(parts)
        await msg.edit_text(final, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("OK", callback_data=f"rub_ok_{msg.message_id}")
        ]]))
    except asyncio.TimeoutError:
        await msg.edit_text(_pad("⏰ Сайты не ответили вовремя."))
    except Exception as e:
        logger.error(f"Currency rate error: {e}")
        await msg.edit_text(_pad("⚠️ Не удалось получить курсы валют."))


async def cmd_timer(update, context):
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id

    if not context.args:
        msg = await update.message.reply_text(_pad("❌ Укажи время в минутах. Пример: /t 10"))
        register_message(user.id, chat_id, update.message.message_id)
        register_message(user.id, chat_id, msg.message_id)
        fire_and_forget(_auto_cleanup(context.bot, user.id, chat_id, msg.message_id, delay=5))
        return

    seconds = parse_duration_seconds(context.args[0])
    if seconds is None:
        msg = await update.message.reply_text(_pad("❌ Укажи время в минутах. Пример: /t 10"))
        register_message(user.id, chat_id, update.message.message_id)
        register_message(user.id, chat_id, msg.message_id)
        fire_and_forget(_auto_cleanup(context.bot, user.id, chat_id, msg.message_id, delay=5))
        return

    # Запускаем процесс таймера с указанным временем
    from handlers.session import start_process
    start_process(user.id, chat_id, "timer", {"step": "waiting_text", "seconds": seconds}, update.message.message_id)

    mins, secs = divmod(seconds, 60)
    duration = f"{mins}м {secs}с" if mins else f"{secs}с"
    reply = await update.message.reply_text(
        f"⏱ Таймер: *{duration}*\n\n📝 Введи подпись таймера (или `-` чтобы пропустить):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )
    register_message(user.id, chat_id, reply.message_id)
async def cmd_setpin(update, context):
    """Установить или сменить PIN-код для защиты карт и файлов."""
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    register_message(user.id, chat_id, update.message.message_id)

    from db import db_has_pin
    has_pin = await db_has_pin(user.id)

    if has_pin:
        # Сначала нужно ввести старый PIN
        start_process(user.id, chat_id, "setpin", {"step": "waiting_old_pin"}, update.message.message_id)
        msg = await update.message.reply_text(
            _pad("🔐 *Смена PIN-кода*\n\nСначала введи текущий PIN:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, msg.message_id)
    else:
        start_process(user.id, chat_id, "setpin", {"step": "waiting_pin"}, update.message.message_id)
        msg = await update.message.reply_text(
            _pad("🔐 *Установка PIN-кода*\n\nВведи PIN-код (4 цифры):"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, msg.message_id)


async def cmd_lock(update, context):
    """Заблокировать доступ к картам и файлам сейчас."""
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    register_message(user.id, chat_id, update.message.message_id)

    from handlers.session import lock_pin
    lock_pin(user.id)

    await show_main_menu(context.bot, user.id, "🔒 Доступ к картам и файлам заблокирован.")


async def cmd_milk(update, context):
    """Информация о молочнике (приезжает через день в 8 утра)."""
    if not await _check_auth(update):
        return
    from datetime import datetime

    user = update.effective_user
    chat_id = update.effective_chat.id
    register_message(user.id, chat_id, update.message.message_id)

    now = datetime.now()
    today = now.date()
    day_number = today.day  # День месяца (1-31)

    # Молочник приезжает по нечётным дням месяца (1, 3, 5, 7...)
    is_milk_day = day_number % 2 == 1

    current_hour = now.hour

    if is_milk_day:
        if current_hour < 8:
            text = "🥛 Молочник приедет сегодня в 8 утра. Успеешь!"
        elif current_hour < 9:
            text = "🥛 Молочник уже продаёт! Успей купить!"
        else:
            text = "🥛 Молочник уже уехал. Приедет послезавтра."
    else:
        # Вчера был (день -2 или -4 и т.д. от нечётного)
        if day_number == 2 or (day_number > 2 and (day_number - 1) % 4 == 0):
            text = "🥛 Молочник был вчера. Приедет завтра в 8 утра."
        else:
            text = "🥛 Молочник был вчера. Приедет завтра в 8 утра."

    msg = await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("OK", callback_data="milk_ok")
        ]])
    )
    register_message(user.id, chat_id, msg.message_id)
    # Удаляем команду пользователя
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=update.message.message_id)
    except Exception:
        pass
    fire_and_forget(_auto_cleanup(context.bot, user.id, chat_id, msg.message_id, delay=10))


async def cmd_allow(update, context):
    """Разрешить доступ пользователю (только для админа)."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    from config import ADMIN_ID
    if user.id != ADMIN_ID:
        msg = await update.message.reply_text(_pad("❌ Только администратор может использовать эту команду."))
        register_message(user.id, chat_id, update.message.message_id)
        register_message(user.id, chat_id, msg.message_id)
        return
    register_message(user.id, chat_id, update.message.message_id)

    args = context.args
    if not args:
        msg = await update.message.reply_text(_pad(
            "❌ Укажи ID пользователя. Пример:\n"
            "/allow 123456789\n"
            "/allow @username"
        ),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, msg.message_id)
        return

    target = args[0].lstrip("@")
    try:
        target_id = int(target)
    except ValueError:
        msg = await update.message.reply_text(
            "❌ Укажи числовой ID пользователя (не username).\n"
            "Пользователь должен написать боту хотя бы /start, чтобы появился ID.",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, msg.message_id)
        return

    if target_id == ADMIN_ID:
        msg = await update.message.reply_text(_pad("ℹ️ Это ваш ID. У вас уже есть доступ."))
        register_message(user.id, chat_id, msg.message_id)
        return

    from db import db_allow_user
    await db_allow_user(target_id, user.id)
    msg = await update.message.reply_text(_pad(f"✅ Пользователю *{target_id}* разрешён доступ к боту."), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton("OK", callback_data=f"allow_ok_{update.message.message_id}")
    ]]))
    register_message(user.id, chat_id, msg.message_id)


async def cmd_disallow(update, context):
    """Запретить доступ пользователю (только для админа)."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    from config import ADMIN_ID
    if user.id != ADMIN_ID:
        msg = await update.message.reply_text(_pad("❌ Только администратор может использовать эту команду."))
        register_message(user.id, chat_id, update.message.message_id)
        register_message(user.id, chat_id, msg.message_id)
        return
    register_message(user.id, chat_id, update.message.message_id)

    args = context.args
    if not args:
        msg = await update.message.reply_text(
            "❌ Укажи ID пользователя. Пример: /disallow 123456789",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        register_message(user.id, chat_id, msg.message_id)
        return

    target = args[0]
    try:
        target_id = int(target)
    except ValueError:
        msg = await update.message.reply_text(_pad("❌ ID должен быть числом."), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        register_message(user.id, chat_id, msg.message_id)
        return

    from db import db_disallow_user
    await db_disallow_user(target_id)
    msg = await update.message.reply_text(_pad(f"✅ Пользователю *{target_id}* запрещён доступ к боту."), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton("OK", callback_data=f"disallow_ok_{update.message.message_id}")
    ]]))
    register_message(user.id, chat_id, msg.message_id)


async def cmd_whitelist(update, context):
    """Показать список разрешённых пользователей (только для админа)."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    from config import ADMIN_ID
    if user.id != ADMIN_ID:
        msg = await update.message.reply_text(_pad("❌ Только администратор может использовать эту команду."))
        register_message(user.id, chat_id, update.message.message_id)
        register_message(user.id, chat_id, msg.message_id)
        return
    register_message(user.id, chat_id, update.message.message_id)

    from db import db_get_allowed_users
    users = await db_get_allowed_users()

    if not users:
        text = "📋 *Белый список:*\n\nНет разрешённых пользователей (кроме вас)."
    else:
        lines = ["📋 *Белый список:*\n"]
        for u in users:
            name = u.get("name") or "—"
            uid = u["user_id"]
            lines.append(f"• *{uid}* — {md(name)}")
        text = "\n".join(lines)

    msg = await update.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton("OK", callback_data=f"whitelist_ok_{update.message.message_id}")
    ]]))
    register_message(user.id, chat_id, msg.message_id)


async def cmd_lockdown(update, context):
    """Включить/выключить режим ограничения доступа (только для админа).
    
    Без параметра — показывает текущий статус.
    /lockdown on — включить
    /lockdown off — выключить
    """
    user = update.effective_user
    chat_id = update.effective_chat.id
    command_message_id = update.message.message_id if update.message else 0
    from config import ADMIN_ID
    if user.id != ADMIN_ID:
        msg = await update.message.reply_text(_pad("❌ Только администратор может использовать эту команду."))
        register_message(user.id, chat_id, update.message.message_id)
        register_message(user.id, chat_id, msg.message_id)
        return
    register_message(user.id, chat_id, update.message.message_id)

    from db import db_get_lockdown, db_set_lockdown

    ok_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("OK", callback_data=f"lockdown_ok_{command_message_id}")
    ]])

    # Определяем новое состояние
    args = context.args
    new_state = None
    if args:
        arg = args[0].lower()
        if arg in ("on", "1", "yes", "вкл", "да"):
            new_state = True
        elif arg in ("off", "0", "no", "выкл", "нет"):
            new_state = False
        else:
            msg = await update.message.reply_text(
                "❌ Использование: /lockdown [on|off]\n\n"
                "Без параметра — показать текущий статус.",
                reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
            )
            register_message(user.id, chat_id, msg.message_id)
            return

    current = await db_get_lockdown()

    if new_state is not None:
        if new_state == current:
            status = "включён" if current else "выключен"
            msg = await update.message.reply_text(_pad(f"ℹ️ Режим ограничения уже *{status}*. Без изменений."), parse_mode="Markdown", reply_markup=ok_markup)
        else:
            await db_set_lockdown(new_state)
            if new_state:
                msg = await update.message.reply_text(
                    "🔒 *Режим ограничения включён!*\n\n"
                    "Теперь доступ к боту есть только у:\n"
                    "• Администратора\n"
                    "• Пользователей из ALLOWED_IDS (.env)\n"
                    "• Пользователей, добавленных через /allow",
                    parse_mode="Markdown",
                    reply_markup=ok_markup
                )
            else:
                msg = await update.message.reply_text(
                    "🔓 *Режим ограничения выключен.*\n\n"
                    "Теперь доступ к боту есть у всех пользователей.",
                    parse_mode="Markdown",
                    reply_markup=ok_markup
                )
    else:
        status = "🔒 *включён*" if current else "🔓 *выключен*"
        msg = await update.message.reply_text(
            f"Режим ограничения доступа: {status}\n\n"
            "Используй `/lockdown on` или `/lockdown off` чтобы изменить.",
            parse_mode="Markdown",
            reply_markup=ok_markup
        )
    register_message(user.id, chat_id, msg.message_id)




async def cmd_logs(update, context):
    """Показать логи ошибок (только для админа)."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    from config import ADMIN_ID
    if user.id != ADMIN_ID:
        msg = await update.message.reply_text(_pad("❌ Только администратор может использовать эту команду."))
        register_message(user.id, chat_id, update.message.message_id)
        register_message(user.id, chat_id, msg.message_id)
        return
    register_message(user.id, chat_id, update.message.message_id)

    from db import db_get_recent_errors, db_mark_errors_read

    limit = 20
    args = context.args
    if args:
        try:
            limit = int(args[0])
            limit = max(1, min(100, limit))
        except ValueError:
            pass

    errors = await db_get_recent_errors(limit)

    if not errors:
        msg = await update.message.reply_text(
            _pad("✅ Лог ошибок пуст. Молодец!"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("OK", callback_data=f"logs_ok_{update.message.message_id}")
            ]])
        )
        register_message(user.id, chat_id, msg.message_id)
        return

    await db_mark_errors_read()

    lines = [f"⚠️ *Лог ошибок* (последние {len(errors)}):\n"]
    for e in errors:
        created = e.get("created_at", "?")
        level = e.get("level", "ERROR")
        msg_text = e.get("message", "?")[:80]
        uid = e.get("user_id", 0)
        read_status = "📖" if e.get("is_read") else "🔴"
        lines.append(f"{read_status} `{created}` *{level}* (user={uid}): {msg_text}")

    text = "\n".join(lines)

    # Если текст слишком длинный — режем на части
    if len(text) > 4000:
        for chunk in [text[i:i+4000] for i in range(0, len(text), 4000)]:
            msg = await update.message.reply_text(
                _pad(chunk), parse_mode="Markdown"
            )
            register_message(user.id, chat_id, msg.message_id)
    else:
        msg = await update.message.reply_text(
            _pad(text),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("OK", callback_data=f"logs_ok_{update.message.message_id}")
            ]])
        )
        register_message(user.id, chat_id, msg.message_id)


async def cmd_export(update, context):
    """Экспортировать данные пользователя в JSON или CSV zip."""
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    if update.message:
        register_message(user.id, chat_id, update.message.message_id)

    fmt = (context.args[0].lower() if context.args else "json").strip()
    if fmt not in {"json", "csv"}:
        msg = await update.message.reply_text(
            _pad("❌ Формат не понял. Используй `/export` или `/export csv`."),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_menu()]])
        )
        register_message(user.id, chat_id, msg.message_id)
        return

    payload = await build_export_payload(user.id)
    if fmt == "csv":
        data = payload_to_csv_zip_bytes(payload)
        filename = export_filename(user.id, "zip")
        caption = "📦 Экспорт CSV готов."
    else:
        data = payload_to_json_bytes(payload)
        filename = export_filename(user.id, "json")
        caption = "📦 Экспорт JSON готов."

    document = io.BytesIO(data)
    document.name = filename
    msg = await update.message.reply_document(
        document=document,
        filename=filename,
        caption=caption,
        reply_markup=InlineKeyboardMarkup([[btn_menu()]])
    )
    register_message(user.id, chat_id, msg.message_id)


async def shortcut_handler(update, context):
    if not await _check_auth(update):
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    cmd = update.message.text.strip().lstrip("/").split()[0]
    query = SHORTCUTS.get(cmd)
    register_message(user.id, chat_id, update.message.message_id)
    if query:
        await do_search(update, query, user.id, chat_id, context.bot)
    else:
        msg = await update.message.reply_text(_pad("❌ Неизвестная команда"))
        register_message(user.id, chat_id, msg.message_id)
        fire_and_forget(_auto_cleanup(context.bot, user.id, chat_id, msg.message_id, delay=3))


# ─── Utilities ────────────────────────────────────────────────────────────────

async def _auto_cleanup(bot, user_id: int, chat_id: int, message_id: int, delay: int = 5):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


def _format_reminder_time(r: dict) -> str:
    if r.get("delivered"):
        return "сработало"
    t = r["time"]
    now = datetime.now()
    if t.date() == now.date():
        return t.strftime("%H:%M")
    elif t.date() == (now + timedelta(days=1)).date():
        return f"завтра {t.strftime('%H:%M')}"
    else:
        return t.strftime("%d.%m %H:%M")


from datetime import datetime, timedelta
