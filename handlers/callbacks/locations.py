"""Location callback handlers."""
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.callbacks.base import domain_handler

logger = logging.getLogger(__name__)


@domain_handler
async def handle_locations_callbacks(query, context, data, user, chat_id, bot):
    if data == "open_locations":
        from handlers.processors.locations import _show_locations
        await _show_locations(query)
        return True

    if data == "add_location":
        from handlers.session import start_process
        from keyboards import btn_cancel
        start_process(user.id, chat_id, "location", {"step": "waiting_name"}, query.message.message_id)
        await query.edit_message_text(
            "📍 *Добавить локацию*\n\nВведи название (например: Дом, Работа):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("showloc_"):
        from db import db_get_locations
        from utils import md, _pad
        loc_id = int(data.split("_")[1])
        locs = await db_get_locations(user.id)
        loc = next((loc_item for loc_item in locs if loc_item["id"] == loc_id), None)
        if not loc:
            await query.edit_message_text(_pad("❌ Локация не найдена."))
            return True
        loc_msg = await bot.send_location(chat_id=chat_id, latitude=loc["latitude"], longitude=loc["longitude"])
        await bot.send_message(
            chat_id=chat_id,
            text=f"📍 *{md(loc['name'])}*\n\nЛокация отправлена",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("OK", callback_data=f"loc_ok_{loc_id}_{loc_msg.message_id}")],
            ])
        )
        return True

    if data.startswith("loc_ok_"):
        loc_msg_id = int(data.split("_")[3])
        from handlers.callbacks.base import _delete_ok_messages
        await _delete_ok_messages(bot, chat_id, loc_msg_id, query.message.message_id)
        return True

    if data.startswith("delloc_"):
        from db import db_get_locations
        from keyboards import btn_menu
        loc_id = int(data.split("_")[1])
        locs = await db_get_locations(user.id)
        loc = next((loc_item for loc_item in locs if loc_item["id"] == loc_id), None)
        if not loc:
            await query.answer("❌ Локация не найдена", show_alert=True)
            return True
        await query.edit_message_text(
            f"🗑 Удалить локацию?\n\n{loc['name']}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirmdelloc_{loc_id}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="open_locations"), btn_menu()],
            ])
        )
        return True

    if data.startswith("confirmdelloc_"):
        from db import db_delete_location
        from handlers.processors.locations import _show_locations
        loc_id = int(data.split("_")[1])
        await db_delete_location(user.id, loc_id)
        await _show_locations(query, "✅ Локация удалена")
        return True

    if data.startswith("loctogglemode_"):
        mode = data[14:]
        from handlers.processors.locations import _get_loc_action_mode, _set_loc_action_mode, _show_locations
        current = _get_loc_action_mode(user.id)
        if current == mode:
            _set_loc_action_mode(user.id, "")
        else:
            _set_loc_action_mode(user.id, mode)
        await _show_locations(query)
        return True

    if data.startswith("loctoggle_"):
        mode = data[10:]
        from handlers.processors.locations import _set_loc_sort_mode, _set_loc_action_mode, _show_locations
        target_mode = {"up": "up", "down": "down", "off": ""}[mode]
        _set_loc_sort_mode(user.id, target_mode)
        if target_mode:
            _set_loc_action_mode(user.id, "")
        await _show_locations(query)
        return True

    if data.startswith("editlocgeo_"):
        from handlers.session import start_process
        from keyboards import btn_cancel
        loc_id = int(data.split("_")[1])
        start_process(user.id, chat_id, "location_refresh", {"loc_id": loc_id}, query.message.message_id)
        await query.edit_message_text(
            "📍 *Обновить координаты*\n\nОтправь новую локацию (нажми скрепку → геолокация):",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("editlocname_"):
        from db import db_get_locations
        from handlers.session import start_process
        from keyboards import btn_cancel
        from utils import md, _pad
        loc_id = int(data.split("_")[1])
        locs = await db_get_locations(user.id)
        loc = next((loc_item for loc_item in locs if loc_item["id"] == loc_id), None)
        if not loc:
            await query.answer("❌ Локация не найдена", show_alert=True)
            return True
        start_process(user.id, chat_id, "location_rename", {"loc_id": loc_id}, query.message.message_id)
        await query.edit_message_text(
            _pad(f"✏️ *Редактировать название*\n\nТекущее: `{md(loc['name'])}`\n\nВведи новое название:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("locmove_"):
        from db import db_get_locations, db_update_loc_sort_order
        from handlers.processors.locations import _show_locations
        parts = data.split("_")
        loc_id = int(parts[1])
        direction = parts[2]
        locs = await db_get_locations(user.id)
        loc_ids = [loc_item['id'] for loc_item in locs]
        if loc_id not in loc_ids:
            await query.answer("❌ Локация не найдена", show_alert=True)
            return True
        idx = loc_ids.index(loc_id)
        if direction == "up" and idx > 0:
            loc_ids[idx], loc_ids[idx - 1] = loc_ids[idx - 1], loc_ids[idx]
        elif direction == "down" and idx < len(loc_ids) - 1:
            loc_ids[idx], loc_ids[idx + 1] = loc_ids[idx + 1], loc_ids[idx]
        for i, l_id in enumerate(loc_ids):
            await db_update_loc_sort_order(user.id, l_id, i)
        await _show_locations(query)
        return True

    if data.startswith("open_loctag_"):
        from db import db_get_locations_by_tag, db_get_location_tag
        from handlers.processors.locations import _get_loc_action_mode
        from keyboards import btn_menu
        from utils import _pad, md
        tag_id = int(data.split("_")[2])
        tag = await db_get_location_tag(user.id, tag_id)
        locs = await db_get_locations_by_tag(user.id, tag_id)
        action_mode = _get_loc_action_mode(user.id)
        text = f"📍 *Локации* / 🏷 *{md(tag['name'])}*"
        if action_mode:
            _mode_labels = {"delete": "🗑 Удалить", "rename": "✏️ Редактировать", "tags": "🏷 Теги", "location": "📍 Координаты"}
            text += f"\n\n*Режим:* ✅ {_mode_labels.get(action_mode, action_mode)}"
        keyboard = []
        for loc in locs:
            if action_mode == "delete":
                keyboard.append([InlineKeyboardButton(f"🗑 {loc['name']}", callback_data=f"delloc_{loc['id']}")])
            elif action_mode == "rename":
                keyboard.append([InlineKeyboardButton(f"✏️ {loc['name']}", callback_data=f"editlocname_{loc['id']}")])
            elif action_mode == "tags":
                keyboard.append([InlineKeyboardButton(f"🏷 {loc['name']}", callback_data=f"loctags_{loc['id']}")])
            elif action_mode == "location":
                keyboard.append([InlineKeyboardButton(f"📍 {loc['name']}", callback_data=f"editlocgeo_{loc['id']}")])
            else:
                keyboard.append([InlineKeyboardButton(f"{loc['name']}", callback_data=f"showloc_{loc['id']}")])
        keyboard.append([btn_menu()])
        await query.edit_message_text(_pad(text), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    return False


async def show_locations_menu(bot, user_id, custom_text=None):
    from db import db_get_locations, db_get_location_tags_with_counts
    from handlers.message_cache import main_menu_messages
    from handlers.processors.locations import _get_loc_action_mode, _get_loc_sort_mode
    from handlers.session import register_message
    from keyboards import btn_menu
    from utils import _pad
    chat_id = main_menu_messages.get(user_id, user_id)
    action_mode = _get_loc_action_mode(user_id)
    sort_mode = _get_loc_sort_mode(user_id)
    locs = await db_get_locations(user_id)
    keyboard = []
    for loc in locs:
        if sort_mode == "up":
            keyboard.append([InlineKeyboardButton(f"⬆️ {loc['name']}", callback_data=f"locmove_{loc['id']}_up")])
        elif sort_mode == "down":
            keyboard.append([InlineKeyboardButton(f"⬇️ {loc['name']}", callback_data=f"locmove_{loc['id']}_down")])
        elif action_mode == "delete":
            keyboard.append([InlineKeyboardButton(f"🗑 {loc['name']}", callback_data=f"delloc_{loc['id']}")])
        elif action_mode == "rename":
            keyboard.append([InlineKeyboardButton(f"✏️ {loc['name']}", callback_data=f"editlocname_{loc['id']}")])
        elif action_mode == "tags":
            keyboard.append([InlineKeyboardButton(f"🏷 {loc['name']}", callback_data=f"loctags_{loc['id']}")])
        elif action_mode == "location":
            keyboard.append([InlineKeyboardButton(f"📍 {loc['name']}", callback_data=f"editlocgeo_{loc['id']}")])
        else:
            keyboard.append([InlineKeyboardButton(f"{loc['name']}", callback_data=f"showloc_{loc['id']}")])
    text = "📍 *Твои локации:*"
    if action_mode:
        _mode_labels = {"delete": "🗑 Удалить", "rename": "✏️ Редактировать", "tags": "🏷 Теги", "location": "📍 Координаты"}
        text += f"\n\n*Режим:* ✅ {_mode_labels.get(action_mode, action_mode)}"
    if custom_text:
        text = custom_text
    if not locs:
        text = "📍 *Локации* — пока нет сохранённых локаций."
    delete_lbl = "✅ 🗑 Удалить" if action_mode == "delete" else "🗑 Удалить"
    rename_lbl = "✅ ✏️ Редактировать" if action_mode == "rename" else "✏️ Редактировать"
    tags_lbl = "✅ 🏷 Теги" if action_mode == "tags" else "🏷 Теги"
    loc_lbl = "✅ 📍 Координаты" if action_mode == "location" else "📍 Координаты"
    sort_btn_label, sort_btn_mode = {
        "": ("🔢 Сортировка", "up"),
        "up": ("⬆️ Сортировка", "down"),
        "down": ("⬇️ Сортировка", "off"),
    }[sort_mode]
    keyboard.append([InlineKeyboardButton("✚ Добавить", callback_data="add_location"), InlineKeyboardButton(delete_lbl, callback_data="loctogglemode_delete")])
    keyboard.append([InlineKeyboardButton(rename_lbl, callback_data="loctogglemode_rename"), InlineKeyboardButton(loc_lbl, callback_data="loctogglemode_location")])
    keyboard.append([InlineKeyboardButton(tags_lbl, callback_data="loctogglemode_tags"), InlineKeyboardButton(sort_btn_label, callback_data=f"loctoggle_{sort_btn_mode}")])
    keyboard.append([btn_menu()])
    all_tags = await db_get_location_tags_with_counts(user_id)
    all_tags = [t for t in all_tags if t["count"] > 0]
    if all_tags:
        tag_row = [InlineKeyboardButton("• Все", callback_data="open_locations")]
        for t in all_tags:
            tag_row.append(InlineKeyboardButton(t['name'], callback_data=f"open_loctag_{t['id']}"))
        for i in range(0, len(tag_row), 4):
            keyboard.append(tag_row[i:i + 4])
    msg = await bot.send_message(chat_id=chat_id, text=_pad(text), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    register_message(user_id, chat_id, msg.message_id)
