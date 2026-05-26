"""Lists domain processor."""
import asyncio
import logging
import uuid

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    db_create_list, db_list_exists, db_add_item, db_item_exists,
    db_get_list, db_get_items, db_get_item_tags, db_get_item_tags_batch, db_get_item_tags_for_list, db_add_item_tag, db_remove_item_tag, db_get_or_create_item_tag,
)
from keyboards import btn_menu, btn_cancel
from handlers.session import register_message, start_process, finish_process, processes
from handlers.processors import register_message_handler, register_callback_handler
from utils import md
from utils.list_display import format_list_display
from utils import _pad

logger = logging.getLogger(__name__)

# ─── Action Mode ─────────────────────────────────────────────────────────────
# Хранит режим действий для каждого (user_id, list_id): "" | "edit" | "delete"
_list_action_modes: dict[str, str] = {}

def _get_action_mode(user_id: int, list_id: str) -> str:
    return _list_action_modes.get(f"{user_id}:{list_id}", "")

def _set_action_mode(user_id: int, list_id: str, mode: str):
    key = f"{user_id}:{list_id}"
    if mode:
        _list_action_modes[key] = mode
    else:
        _list_action_modes.pop(key, None)


# ─── Sort Mode ───────────────────────────────────────────────────────────────
# Хранит режим сортировки для каждого (user_id, list_id): "" | "up" | "down"
_list_sort_modes: dict[str, str] = {}

def _get_sort_mode(user_id: int, list_id: str) -> str:
    return _list_sort_modes.get(f"{user_id}:{list_id}", "")

def _set_sort_mode(user_id: int, list_id: str, mode: str):
    key = f"{user_id}:{list_id}"
    if mode:
        _list_sort_modes[key] = mode
    else:
        _list_sort_modes.pop(key, None)

# ─── List Menu Action Mode ───────────────────────────────────────────────────
# Хранит режим для меню списков (overview): "" | "edit" | "delete" | "share"
_list_menu_action_modes: dict[int, str] = {}

def _get_list_menu_action_mode(user_id: int) -> str:
    return _list_menu_action_modes.get(user_id, "")

def _set_list_menu_action_mode(user_id: int, mode: str):
    if mode:
        _list_menu_action_modes[user_id] = mode
    else:
        _list_menu_action_modes.pop(user_id, None)


# ─── Message Handlers ────────────────────────────────────────────────────────

@register_message_handler("list")
async def handle_list_message(update, context, proc, state):
    from ai import _suggest_emoji
    from telegram import InlineKeyboardMarkup

    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")

    if step == "creating_list_name":
        force_create = bool(state.pop("force_create", False))
        if await db_list_exists(text, user.id) and not force_create:
            state["pending_duplicate_name"] = text
            reply = await message.reply_text(
                _pad(f"⚠️ Список *{md(text)}* уже существует.\n\nСоздать ещё один с таким названием?"),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Всё равно создать", callback_data="list_force_create")],
                    [btn_cancel()],
                ])
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        list_id = str(uuid.uuid4())[:8]
        await db_create_list( list_id, "personal", text, user.id)
        state["step"] = "adding_items"
        state["list_id"] = list_id
        state["list_name"] = text

        reply = await message.reply_text(
            f"✅ Список *{md(text)}* создан!\n\nОтправляй элементы по одному.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Завершить ввод", callback_data=f"done_adding_{list_id}")],
                [btn_cancel()],
            ])
        )
        register_message(user.id, chat_id, reply.message_id)

    elif step == "adding_items":
        list_id = state.get("list_id")
        list_name = state.get("list_name", "список")

        if await db_item_exists(list_id, text):
            prev_confirm = state.get("last_confirm_id")
            if prev_confirm:
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=prev_confirm)
                except Exception:
                    pass
            reply = await message.reply_text(
                "⚠️ Этот элемент уже есть в списке!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Завершить ввод", callback_data=f"done_adding_{list_id}")],
                    [btn_cancel()],
                ])
            )
            register_message(user.id, chat_id, reply.message_id)
            state["last_confirm_id"] = reply.message_id
            return

        emoji = await asyncio.to_thread(_suggest_emoji, text)
        await db_add_item( list_id, user.id, text, emoji)

        prev_confirm = state.get("last_confirm_id")
        if prev_confirm:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=prev_confirm)
            except Exception:
                pass
            if prev_confirm in proc.get("messages", []):
                proc["messages"].remove(prev_confirm)

        reply = await message.reply_text(
            f"✅ *{md(text)}* добавлен в *{md(list_name)}*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Завершить ввод", callback_data=f"done_adding_{list_id}")],
                [btn_cancel()],
            ])
        )
        register_message(user.id, chat_id, reply.message_id)
        state["last_confirm_id"] = reply.message_id


@register_message_handler("edit_list_name")
async def handle_edit_list_name(update, context, proc, state):
    from db import db
    from telegram import InlineKeyboardMarkup

    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    list_id = state.get("list_id")
    old_name = state.get("old_name", "")

    new_name = text.strip()
    if not new_name:
        reply = await message.reply_text(_pad("❌ Название не может быть пустым."), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        register_message(user.id, chat_id, reply.message_id)
        return

    if await db_list_exists(new_name, user.id) and new_name != old_name:
        reply = await message.reply_text(_pad("⚠️ Список с таким названием уже существует!"), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        register_message(user.id, chat_id, reply.message_id)
        return

    with db._conn() as con:
        con.execute("UPDATE lists SET name=? WHERE list_id=?", (new_name, list_id))

    await finish_process(bot, user.id, show_menu=False)
    from handlers.callbacks.lists import show_lists_menu
    await show_lists_menu(context.bot, user.id, f"✅ Список переименован: {md(new_name)}")


@register_message_handler("edit_item")
async def handle_edit_item(update, context, proc, state):
    from db import db
    from telegram import InlineKeyboardMarkup

    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    list_id = state.get("list_id")
    item_id = state.get("item_id")

    new_text = text.strip()
    if not new_text:
        reply = await message.reply_text(_pad("❌ Текст не может быть пустым."), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        register_message(user.id, chat_id, reply.message_id)
        return

    with db._conn() as con:
        con.execute("UPDATE list_items SET item=? WHERE id=?", (new_text, item_id))

    await finish_process(bot, user.id, show_menu=False)
    from handlers.callbacks.lists import show_list_items_for_user
    await show_list_items_for_user(context.bot, user.id, list_id, f"✅ Элемент обновлён: {md(new_text)}")


@register_callback_handler("list_force_create")
async def cb_list_force_create(query, context, data, user, chat_id, bot):
    proc = processes.get(user.id)
    if not proc or proc.get("type") != "list":
        await query.answer("Сессия не найдена", show_alert=True)
        return
    state = proc["state"]
    name = state.get("pending_duplicate_name")
    if not name:
        await query.answer("Название не найдено", show_alert=True)
        return

    list_id = str(uuid.uuid4())[:8]
    await db_create_list(list_id, "personal", name, user.id)
    state["step"] = "adding_items"
    state["list_id"] = list_id
    state["list_name"] = name
    state.pop("pending_duplicate_name", None)

    await query.edit_message_text(
        _pad(f"✅ Список *{md(name)}* создан!\n\nОтправляй элементы по одному."),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Завершить ввод", callback_data=f"done_adding_{list_id}")],
            [btn_cancel()],
        ])
    )


# ─── Callback Handlers ────────────────────────────────────────────────────────


async def _show_list_items(query, list_id: str, hide_done: bool = False, tag_filter_id: int | None = None):
    """Показать элементы списка (редактирует текущее сообщение).
    Режимы (edit/delete) читаются из _list_action_modes."""


    user = query.from_user
    sort_mode = _get_sort_mode(user.id, list_id)
    action_mode = _get_action_mode(user.id, list_id)
    lst = await db_get_list( list_id)
    all_items = await db_get_items( list_id)
    name = lst["name"] if lst else list_id
    owner_id = lst["created_by"] if lst else user.id

    # Сохраняем полный список для статистики прогресс-бара
    all_items_for_stats = all_items

    # Фильтр по тегу
    tag = None
    if tag_filter_id is not None:
        from db import db
        with db._conn() as con:
            row = con.execute("SELECT * FROM item_tags WHERE id=?", (tag_filter_id,)).fetchone()
        tag = dict(row) if row else None
        if tag:
            # Загружаем теги для всех элементов одним запросом
            item_ids = [item["id"] for item in all_items]
            tags_by_item = await db_get_item_tags_batch( item_ids)
            filtered = []
            for item in all_items:
                item_tags = tags_by_item.get(item["id"], [])
                if any(
                    t["id"] == tag_filter_id
                    or t.get("normalized_name") == tag.get("normalized_name")
                    for t in item_tags
                ):
                    filtered.append(item)
            all_items = filtered

    # Фильтр hide_done
    if hide_done:
        all_items = [item for item in all_items if not item.get("checked", 0)]

    list_title = format_list_display(name, all_items_for_stats)
    keyboard = []

    if not all_items:
        if hide_done and all_items_for_stats:
            text = _pad("✅ *%s*\n\nВсе отмеченные скрыты." % md(list_title))
        elif tag:
            text = _pad("📭 Нет элементов с тегом *%s*." % md(tag["name"]))
        else:
            text = _pad("📭 *%s* — пуст." % md(list_title))
        if action_mode:
            text = _pad("📭 *%s*\n\nНет элементов." % md(list_title))
            _mode_labels = {"edit": "✏️ Редактировать", "delete": "🗑 Удалить"}
            text += f"\n\n*Режим:* ✅ {_mode_labels.get(action_mode, action_mode)}"
        # В пустом состоянии показываем полное меню как обычно
        edit_lbl = "✅ ✏️ Редактировать" if action_mode == "edit" else "✏️ Редактировать"
        delete_lbl = "✅ 🗑 Удалить" if action_mode == "delete" else "🗑 Удалить"
        keyboard.append([
            InlineKeyboardButton("✚ Добавить", callback_data=f"additem_{list_id}"),
            InlineKeyboardButton(delete_lbl, callback_data=f"actionmode_toggle_delete_{list_id}")
        ])
        keyboard.append([
            InlineKeyboardButton(edit_lbl, callback_data=f"actionmode_toggle_edit_{list_id}"),
            InlineKeyboardButton("📋 Скопировать", callback_data=f"export_list_{list_id}")
        ])
        sort_btn_label, sort_btn_mode = {
            "": ("🔢 Сортировка", "up"),
            "up": ("⬆️ Сортировка", "down"),
            "down": ("⬇️ Сортировка", "off"),
        }[sort_mode]
        keyboard.append([
            InlineKeyboardButton("🏷 Теги", callback_data=f"list_tags_{list_id}"),
            InlineKeyboardButton(sort_btn_label, callback_data=f"sorttoggle_{list_id}_{sort_btn_mode}"),
        ])
        hide_label = "👁 Показать все" if hide_done else "🙈 Скрыть"
        tf = tag_filter_id if tag_filter_id is not None else 0
        hide_data = f"showall_{list_id}_{tf}" if hide_done else f"hideDone_{list_id}_{tf}"
        keyboard.append([
            InlineKeyboardButton("◀️ Назад", callback_data="open_my_lists"),
            InlineKeyboardButton(hide_label, callback_data=hide_data),
        ])
        keyboard.append([btn_menu()])
        # Теги-фильтры (из полного списка)
        tags = await db_get_item_tags_for_list( list_id)
        visible_tags = [t for t in tags if t["count"] > 0]
        if visible_tags:
            hd = 1 if hide_done else 0
            tag_buttons = [InlineKeyboardButton("• Все" if tag is None else "Все", callback_data=f"listtag_{list_id}_all_{hd}")]
            for t in visible_tags:
                label = t["name"] if tag_filter_id != t["id"] else f"• {t['name']}"
                tag_buttons.append(InlineKeyboardButton(label, callback_data=f"listtag_{list_id}_{t['id']}_{hd}"))
            for i in range(0, len(tag_buttons), 4):
                keyboard.append(tag_buttons[i:i + 4])
        try:
            await query.edit_message_text(_pad(text), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            if "Message to edit not found" in str(e):
                await query.message.reply_text(_pad(text), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                raise
        return

    # Показываем элементы
    for idx, item in enumerate(all_items):
        checked = item.get("checked", 0)
        checkbox = "☑" if checked else "☐"

        if sort_mode == "up":
            keyboard.append([InlineKeyboardButton(f"⬆️ {item.get('emoji', '📌')} {item.get('item', '')}", callback_data=f"sortitem_{list_id}_{idx}_up")])
        elif sort_mode == "down":
            keyboard.append([InlineKeyboardButton(f"⬇️ {item.get('emoji', '📌')} {item.get('item', '')}", callback_data=f"sortitem_{list_id}_{idx}_down")])
        elif action_mode == "edit":
            keyboard.append([InlineKeyboardButton(f"✏️ {item.get('emoji', '📌')} {item.get('item', '')}", callback_data=f"edititem_{list_id}_{idx}")])
        elif action_mode == "delete":
            keyboard.append([InlineKeyboardButton(f"🗑 {item.get('emoji', '📌')} {item.get('item', '')}", callback_data=f"delitem_X_{list_id}_{idx}")])
        else:
            hd = 1 if hide_done else 0
            if tag_filter_id is not None:
                callback = f"toggleitemtf_{tag_filter_id}_{list_id}_{item['id']}_{hd}"
            else:
                callback = f"toggleitem_{list_id}_{item['id']}_{hd}"
            keyboard.append([InlineKeyboardButton(f"{checkbox} {item.get('emoji', '📌')} {item.get('item', '')}", callback_data=callback)])

    # Кнопки действий
    edit_lbl = "✅ ✏️ Редактировать" if action_mode == "edit" else "✏️ Редактировать"
    delete_lbl = "✅ 🗑 Удалить" if action_mode == "delete" else "🗑 Удалить"
    keyboard.append([
        InlineKeyboardButton("✚ Добавить", callback_data=f"additem_{list_id}"),
        InlineKeyboardButton(delete_lbl, callback_data=f"actionmode_toggle_delete_{list_id}")
    ])
    keyboard.append([
        InlineKeyboardButton(edit_lbl, callback_data=f"actionmode_toggle_edit_{list_id}"),
        InlineKeyboardButton("📋 Скопировать", callback_data=f"export_list_{list_id}")
    ])

    # Кнопка сортировки — циклический переключатель
    sort_btn_label, sort_btn_mode = {
        "": ("🔢 Сортировка", "up"),
        "up": ("⬆️ Сортировка", "down"),
        "down": ("⬇️ Сортировка", "off"),
    }[sort_mode]
    keyboard.append([
        InlineKeyboardButton("🏷 Теги", callback_data=f"list_tags_{list_id}"),
        InlineKeyboardButton(sort_btn_label, callback_data=f"sorttoggle_{list_id}_{sort_btn_mode}"),
    ])

    hide_label = "👁 Показать все" if hide_done else "🙈 Скрыть"
    tf = tag_filter_id if tag_filter_id is not None else 0
    hide_data = f"showall_{list_id}_{tf}" if hide_done else f"hideDone_{list_id}_{tf}"
    keyboard.append([
        InlineKeyboardButton("◀️ Назад", callback_data="open_my_lists"),
        InlineKeyboardButton(hide_label, callback_data=hide_data),
    ])
    keyboard.append([btn_menu()])

    # Строка тегов-фильтров — только теги из элементов этого списка
    tags = await db_get_item_tags_for_list( list_id)
    visible_tags = [t for t in tags if t["count"] > 0]
    if visible_tags:
        hd = 1 if hide_done else 0
        tag_buttons = [InlineKeyboardButton("• Все" if tag is None else "Все", callback_data=f"listtag_{list_id}_all_{hd}")]
        for t in visible_tags:
            label = t["name"] if tag_filter_id != t["id"] else f"• {t['name']}"
            tag_buttons.append(InlineKeyboardButton(label, callback_data=f"listtag_{list_id}_{t['id']}_{hd}"))
        for i in range(0, len(tag_buttons), 4):
            keyboard.append(tag_buttons[i:i + 4])

    text = "*%s*" % md(list_title)
    if action_mode:
        _mode_labels = {"edit": "✏️ Редактировать", "delete": "🗑 Удалить"}
        text += f"\n\n*Режим:* ✅ {_mode_labels.get(action_mode, action_mode)}"
    text = _pad(text)
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        if "Message to edit not found" in str(e):
            await query.message.reply_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            raise


async def _show_item_tag_picker(query, list_id: str, item_id: int, selected_tag_ids: set[int] | None = None, message: str | None = None):
    """Показать пикер тегов для элемента списка."""
    user = query.from_user
    # Показываем теги, которые есть в этом списке (независимо от user_id),
    # чтобы в shared-списках все видели все теги, привязанные к элементам.
    tags = await db_get_item_tags_for_list( list_id)
    selected_tag_ids = selected_tag_ids or set()
    # Получаем текущие теги элемента для корректной проверки маркера
    # (после dedup по normalized_name tag_id может не совпадать)
    current_tags = await db_get_item_tags( user.id, item_id)
    current_normalized = {t.get("normalized_name") for t in current_tags}

    keyboard = []
    for tag in tags:
        is_selected = tag["id"] in selected_tag_ids or tag.get("normalized_name") in current_normalized
        marker = "☑️" if is_selected else "☐"
        keyboard.append([InlineKeyboardButton(f"{marker} {tag['name']} ({tag['count']})", callback_data=f"itemtag_{list_id}_{item_id}_{tag['id']}")])

    keyboard.append([InlineKeyboardButton("➕ Новый тег", callback_data=f"itemtagnew_{list_id}_{item_id}")])
    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data=f"list_tags_{list_id}"), btn_cancel()])

    text = _pad("🏷 *Теги элемента*")
    if message:
        text += f"\n\n{message}"
    if not tags:
        text += "\n\nТегов пока нет. Можно создать новый или продолжить с тегом *разное*."

    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        if "Message is not modified" not in str(e):
            raise
        # Игнорируем - сообщение уже актуально


@register_callback_handler("list_tags_")
async def cb_list_tags(query, context, data, user, chat_id, bot):
    """Показать меню управления тегами для списка."""
    list_id = data.replace("list_tags_", "", 1)
    lst = await db_get_list( list_id)
    name = lst["name"] if lst else list_id
    items = await db_get_items( list_id)

    # Загружаем теги для всех элементов одним запросом вместо N
    item_ids = [item["id"] for item in items]
    tags_by_item = await db_get_item_tags_batch( item_ids)

    keyboard = []
    for item in items:
        item_tags = tags_by_item.get(item["id"], [])
        tag_text = ", ".join(t["name"] for t in item_tags if t["name"].lower() != "разное")
        tag_text = tag_text or "разное"
        keyboard.append([InlineKeyboardButton(
            f"🏷 {item.get('item', '')} — {tag_text}",
            callback_data=f"itemtags_{list_id}_{item['id']}"
        )])

    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data=f"openlist_{list_id}"), btn_menu()])

    await query.edit_message_text(
        _pad("🏷 *Теги элементов*\n\nВыбери элемент, чтобы изменить его теги:"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


@register_callback_handler("listtag_")
async def cb_list_tag_filter(query, context, data, user, chat_id, bot):
    """Фильтр элементов списка по тегу."""
    parts = data.split("_", 3)  # listtag_{list_id}_{tag_id or "all"}_{hide_done}
    list_id = parts[1]
    tag_value = parts[2]
    hide_done = bool(int(parts[3])) if len(parts) > 3 else False
    if tag_value == "all":
        await _show_list_items(query, list_id, hide_done=hide_done)
    else:
        tag_id = int(tag_value)
        await _show_list_items(query, list_id, tag_filter_id=tag_id, hide_done=hide_done)

@register_callback_handler("itemtags_")
async def cb_item_tags(query, context, data, user, chat_id, bot):
    """Показать пикер тегов для конкретного элемента."""
    parts = data.split("_")
    list_id = parts[1]
    item_id = int(parts[2])
    current_tags = await db_get_item_tags( user.id, item_id)
    selected = {t["id"] for t in current_tags}
    await _show_item_tag_picker(query, list_id, item_id, selected)


@register_callback_handler("itemtagnew_")
async def cb_item_tag_new(query, context, data, user, chat_id, bot):
    """Создать новый тег для элемента."""
    parts = data.split("_")
    list_id = parts[1]
    item_id = int(parts[2])
    start_process(user.id, chat_id, "item_new_tag", {
        "step": "waiting_tag_name",
        "list_id": list_id,
        "item_id": item_id,
    }, query.message.message_id)
    await query.edit_message_text(
        _pad("🏷 Введи название нового тега:"),
        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
    )

@register_callback_handler("itemtag_")
async def cb_item_tag_toggle(query, context, data, user, chat_id, bot):
    """Переключить тег на элементе."""
    from db import db
    parts = data.split("_")  # itemtag_{list_id}_{item_id}_{tag_id}
    list_id = parts[1]
    item_id = int(parts[2])
    tag_id = int(parts[3])
    current_tags = await db_get_item_tags( user.id, item_id)
    selected_ids = {t["id"] for t in current_tags}

    # Определяем normalized_name тега (теги могли дублироваться по user_id)
    with db._conn() as con:
        row = con.execute("SELECT name, normalized_name FROM item_tags WHERE id=?", (tag_id,)).fetchone()
    tag_normalized = row["normalized_name"] if row else None
    tag_name = row["name"] if row else None

    if not tag_normalized or not tag_name:
        return

    # Проверяем, есть ли на элементе теги с таким normalized_name
    matching_current = [t for t in current_tags if t.get("normalized_name") == tag_normalized]

    if matching_current:
        # Удаляем ВСЕ теги с таким normalized_name (могли быть от разных пользователей)
        for t in matching_current:
            await db_remove_item_tag( user.id, item_id, t["id"])
        selected_ids.difference_update(t["id"] for t in matching_current)
    else:
        # Добавляем тег (db_add_item_tag resolve'ит владельца элемента внутри себя)
        await db_add_item_tag( user.id, item_id, tag_name)
        selected_ids.add(tag_id)

    current_tags = await db_get_item_tags( user.id, item_id)
    await _show_item_tag_picker(query, list_id, item_id, {t["id"] for t in current_tags})


@register_message_handler("item_new_tag")
async def handle_item_new_tag(update, context, proc, state):
    """Создать новый тег для элемента списка."""
    from telegram import InlineKeyboardMarkup
    
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    list_id = state.get("list_id")
    item_id = state.get("item_id")

    if not text:
        reply = await message.reply_text(
            _pad("❌ Название тега не может быть пустым."),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        from handlers.session import register_message
        register_message(user.id, chat_id, reply.message_id)
        return
    
    # Создаём тег через DB
    from db import db_add_item_tag
    tag_id = await db_get_or_create_item_tag( user.id, text)
    
    # Привязываем к элементу
    await db_add_item_tag( user.id, item_id, text)
    
    await finish_process(bot, user.id, show_menu=False)
    
    # Возвращаемся к меню тегов
    from handlers.session import register_message
    msg = await bot.send_message(
        chat_id=user.id,
        text=_pad(f"✅ Тег *{md(text)}* создан и привязан!"),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏷 К тегам", callback_data=f"list_tags_{list_id}")
        ]])
    )
    register_message(user.id, chat_id, msg.message_id)
