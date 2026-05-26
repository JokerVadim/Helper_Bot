"""List callback handlers."""
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    db_get_lists_for_user, db_get_items, db_get_list,
    db_delete_item_by_index, db_delete_list,
    db_unshare_list, db_get_list_members, db_get_shared_lists,
    db_toggle_item_checked_by_id, db_get_item_by_index,
    db_update_item_sort_order,
)
from utils import md, _pad
from utils.list_display import format_list_display
from keyboards import btn_menu, btn_cancel
from handlers.callbacks.base import domain_handler

logger = logging.getLogger(__name__)


async def _build_lists_menu_view(user_id: int, custom_text: str = None) -> tuple[str, list]:
    """Построить текст и клавиатуру меню списков."""
    from handlers.processors.lists import _get_list_menu_action_mode
    my_lists = await db_get_lists_for_user(user_id)
    shared_lists = await db_get_shared_lists(user_id)
    action_mode = _get_list_menu_action_mode(user_id)
    keyboard = []

    for lst in my_lists:
        items = await db_get_items(lst["list_id"])
        label = format_list_display(lst["name"], items)
        if action_mode == "edit":
            keyboard.append([InlineKeyboardButton(f"✏️ {label}", callback_data=f"editlistname_{lst['list_id']}")])
        elif action_mode == "delete":
            keyboard.append([InlineKeyboardButton(f"🗑 {label}", callback_data=f"dellist_{lst['list_id']}")])
        elif action_mode == "share":
            keyboard.append([InlineKeyboardButton(f"🔗 {label}", callback_data=f"share_list_{lst['list_id']}")])
        else:
            keyboard.append([InlineKeyboardButton(label, callback_data=f"openlist_{lst['list_id']}")])

    if shared_lists:
        for lst in shared_lists:
            items = await db_get_items(lst["list_id"])
            label = format_list_display(lst["name"], items)
            if action_mode == "delete":
                keyboard.append([InlineKeyboardButton(f"📤 {label}", callback_data=f"dellist_{lst['list_id']}")])
            elif action_mode == "share":
                keyboard.append([InlineKeyboardButton(label, callback_data=f"share_list_{lst['list_id']}")])
            else:
                keyboard.append([InlineKeyboardButton(label, callback_data=f"openlist_{lst['list_id']}")])

    edit_lbl = "✅ ✏️ Редактировать" if action_mode == "edit" else "✏️ Редактировать"
    delete_lbl = "✅ 🗑 Удалить" if action_mode == "delete" else "🗑 Удалить"
    share_lbl = "✅ 🔗 Поделиться" if action_mode == "share" else "🔗 Поделиться"
    keyboard.append([
        InlineKeyboardButton("✚ Добавить", callback_data="newlist_personal"),
        InlineKeyboardButton(share_lbl, callback_data="listmenumode_share"),
    ])
    keyboard.append([
        InlineKeyboardButton(edit_lbl, callback_data="listmenumode_edit"),
        InlineKeyboardButton(delete_lbl, callback_data="listmenumode_delete"),
    ])
    keyboard.append([btn_menu()])

    text = "📋 *Твои списки:*"
    if not my_lists and not shared_lists:
        text = "📭 Списков пока нет"
    elif shared_lists:
        text = "📋 *Твои списки* и *списки с тобой:*"
    if action_mode:
        _mode_labels = {"edit": "✏️ Редактировать", "delete": "🗑 Удалить", "share": "🔗 Поделиться"}
        text += f"\n\n*Режим:* ✅ {_mode_labels.get(action_mode, action_mode)}"
    if custom_text:
        text = custom_text
    text = _pad(text)

    return text, keyboard


async def _delete_ok_messages(bot, chat_id: int, *message_ids: int):
    """Try to delete messages, using bulk delete when possible."""
    ids = [mid for mid in message_ids if mid]
    if not ids:
        return
    if len(ids) > 1:
        try:
            await bot.delete_messages(chat_id=chat_id, message_ids=ids)
            return
        except Exception:
            pass
    for mid in ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass


@domain_handler
async def handle_list_callbacks(query, context, data, user, chat_id, bot):
    """Handle list-related callback queries."""
    if data == "noop":
        return True

    if data in ("open_my_lists", "back_to_lists"):
        text, keyboard = await _build_lists_menu_view(user.id)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    if data == "go_menu":
        from handlers.session import finish_process
        from handlers.session import main_menu_messages
        from keyboards import show_main_menu
        await finish_process(bot, user.id, show_menu=False)
        main_menu_messages[user.id] = query.message.message_id
        await show_main_menu(bot, user.id)
        return True

    if data == "newlist_personal":
        from handlers.session import start_process
        start_process(user.id, chat_id, "list", {"step": "creating_list_name"}, query.message.message_id)
        await query.edit_message_text(_pad("✏️ Введи название списка:"), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
        return True

    if data.startswith("editlistname_"):
        from handlers.session import start_process
        list_id = data.replace("editlistname_", "", 1)
        lst = await db_get_list(list_id)
        if not lst:
            return True
        start_process(user.id, chat_id, "edit_list_name", {"list_id": list_id, "old_name": lst["name"]}, query.message.message_id)
        await query.edit_message_text(
            _pad(f"✏️ *Переименовать список*\n\nТекущее название: `{md(lst['name'])}`\n\nВведи новое название:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("openlist_"):
        from handlers.processors.lists import _show_list_items
        list_id = data[9:]
        await _show_list_items(query, list_id)
        return True

    if data.startswith("viewitems_"):
        from handlers.processors.lists import _show_list_items
        await _show_list_items(query, data[10:])
        return True

    if data.startswith("additem_"):
        from handlers.session import start_process, processes
        list_id = data[8:]
        lst = await db_get_list(list_id)
        name = lst["name"] if lst else list_id
        if user.id not in processes or processes[user.id]["type"] != "list":
            start_process(user.id, chat_id, "list", {}, query.message.message_id)
        processes[user.id]["state"] = {"step": "adding_items", "list_id": list_id, "list_name": name}
        await query.edit_message_text(_pad(f"➕ Добавляю в *{md(name)}*\n\nОтправляй элементы по одному."), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Завершить ввод", callback_data=f"done_adding_{list_id}")],
            [btn_cancel()],
        ]))
        return True

    if data.startswith("export_list_"):
        list_id = data.replace("export_list_", "", 1)
        lst = await db_get_list(list_id)
        items = await db_get_items(list_id)
        name = lst["name"] if lst else list_id

        if not items:
            return True

        text_lines = []
        for i, item in enumerate(items, 1):
            item_text = item.get("item", "")
            text_lines.append(f"{i}. {item_text}")

        export_text = "\n".join(text_lines)

        full_text = f"📋 <b>{md(name)}</b>\n\n<pre>{export_text}</pre>"

        try:
            await query.message.reply_text(
                full_text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ OK", callback_data=f"export_ok_{list_id}")
                ]])
            )
        except Exception as e:
            logger.error(f"Export list error: {e}")
        return True

    if data.startswith("export_ok_"):
        await _delete_ok_messages(bot, chat_id, query.message.message_id)
        return True

    if data.startswith("done_adding_"):
        from handlers.session import processes
        list_id = data[12:]
        if user.id in processes:
            proc = processes[user.id]
            chat_id_proc = proc.get("chat_id", chat_id)
            for msg_id in proc.get("messages", []):
                try:
                    await bot.delete_message(chat_id=chat_id_proc, message_id=msg_id)
                except Exception:
                    pass
            del processes[user.id]

        from handlers.processors.lists import _show_list_items
        await _show_list_items(query, list_id)
        return True

    if data.startswith("sorttoggle_"):
        from handlers.processors.lists import _set_sort_mode, _set_action_mode, _show_list_items
        rest = data[11:]
        last_underscore = rest.rfind("_")
        if last_underscore == -1:
            return True
        list_id = rest[:last_underscore]
        mode = rest[last_underscore + 1:]
        target_mode = {"up": "up", "down": "down", "off": ""}[mode]
        _set_sort_mode(user.id, list_id, target_mode)
        if target_mode:
            _set_action_mode(user.id, list_id, "")
        await _show_list_items(query, list_id)
        return True

    if data.startswith("sortitem_"):
        from handlers.processors.lists import _show_list_items
        rest = data[9:]
        *list_id_parts, idx_str, direction = rest.rsplit("_", 2)
        list_id = "_".join(list_id_parts)
        idx = int(idx_str)
        items = await db_get_items(list_id)
        item_ids = [item["id"] for item in items]
        if idx < 0 or idx >= len(item_ids):
            return True
        if direction == "up" and idx > 0:
            item_ids[idx], item_ids[idx - 1] = item_ids[idx - 1], item_ids[idx]
        elif direction == "down" and idx < len(item_ids) - 1:
            item_ids[idx], item_ids[idx + 1] = item_ids[idx + 1], item_ids[idx]
        else:
            return True
        for i, it_id in enumerate(item_ids):
            await db_update_item_sort_order(list_id, it_id, i)
        await _show_list_items(query, list_id)
        return True

    if data.startswith("toggleitemtf_"):
        from handlers.processors.lists import _show_list_items
        rest = data[13:]
        first_underscore = rest.find("_")
        if first_underscore == -1:
            return True
        tag_filter_id = int(rest[:first_underscore])
        rest2 = rest[first_underscore + 1:]
        *list_id_parts, item_id_str, hide_done_str = rest2.rsplit("_", 2)
        list_id = "_".join(list_id_parts)
        item_id = int(item_id_str)
        hide_done = bool(int(hide_done_str))
        await db_toggle_item_checked_by_id(list_id, item_id)
        await _show_list_items(query, list_id, tag_filter_id=tag_filter_id, hide_done=hide_done)
        return True

    if data.startswith("toggleitem_"):
        from handlers.processors.lists import _show_list_items
        rest = data[11:]
        *list_id_parts, item_id_str, hide_done_str = rest.rsplit("_", 2)
        list_id = "_".join(list_id_parts)
        item_id = int(item_id_str)
        hide_done = bool(int(hide_done_str))
        await db_toggle_item_checked_by_id(list_id, item_id)
        await _show_list_items(query, list_id, hide_done=hide_done)
        return True

    if data.startswith("hideDone_"):
        from handlers.processors.lists import _show_list_items
        parts = data.split("_")
        if len(parts) >= 3:
            tf_val = int(parts[-1])
            tag_filter_id = tf_val if tf_val != 0 else None
            list_id = "_".join(parts[1:-1])
        else:
            list_id = "_".join(parts[1:])
            tag_filter_id = None
        await _show_list_items(query, list_id, hide_done=True, tag_filter_id=tag_filter_id)
        return True

    if data.startswith("showall_"):
        from handlers.processors.lists import _show_list_items
        parts = data.split("_")
        if len(parts) >= 3:
            tf_val = int(parts[-1])
            tag_filter_id = tf_val if tf_val != 0 else None
            list_id = "_".join(parts[1:-1])
        else:
            list_id = "_".join(parts[1:])
            tag_filter_id = None
        await _show_list_items(query, list_id, hide_done=False, tag_filter_id=tag_filter_id)
        return True

    if data.startswith("actionmode_toggle_"):
        from handlers.processors.lists import _get_action_mode, _set_action_mode, _show_list_items
        rest = data[18:]
        first_underscore = rest.find("_")
        if first_underscore == -1:
            return True
        mode = rest[:first_underscore]
        list_id = rest[first_underscore + 1:]
        current = _get_action_mode(user.id, list_id)
        if current == mode:
            _set_action_mode(user.id, list_id, "")
        else:
            _set_action_mode(user.id, list_id, mode)
        await _show_list_items(query, list_id)
        return True

    if data.startswith("edititem_"):
        from handlers.session import start_process
        rest = data[9:]
        *list_id_parts, idx_str = rest.rsplit("_", 1)
        list_id = "_".join(list_id_parts)
        index = int(idx_str)
        item = await db_get_item_by_index(list_id, index)
        if not item:
            return True
        start_process(user.id, chat_id, "edit_item", {"list_id": list_id, "item_id": item["id"], "item_text": item["item"], "index": index}, query.message.message_id)
        await query.edit_message_text(
            _pad(f"✏️ *Редактировать элемент*\n\nТекущий текст: `{item['item']}`\n\nВведи новый текст:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("delitem_X_"):
        from handlers.processors.lists import _show_list_items
        rest = data[10:]
        last_underscore = rest.rfind("_")
        if last_underscore == -1:
            return True
        list_id = rest[:last_underscore]
        idx = int(rest[last_underscore + 1:])
        item = await db_get_item_by_index(list_id, idx)
        if not item:
            return True
        await query.edit_message_text(
            _pad(f"🗑 Удалить `{md(item['item'])}`?"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirm_delitem_{list_id}_{idx}")],
                [InlineKeyboardButton("◀️ Отмена", callback_data=f"cancel_delitem_{list_id}")],
            ])
        )
        return True

    if data.startswith("confirm_delitem_"):
        from handlers.processors.lists import _show_list_items
        rest = data[16:]
        last_underscore = rest.rfind("_")
        if last_underscore == -1:
            return True
        list_id = rest[:last_underscore]
        idx = int(rest[last_underscore + 1:])
        await db_delete_item_by_index(list_id, idx)
        await _show_list_items(query, list_id)
        return True

    if data.startswith("cancel_delitem_"):
        from handlers.processors.lists import _show_list_items
        list_id = data[15:]
        await _show_list_items(query, list_id)
        return True

    if data.startswith("dellist_"):
        list_id = data.replace("dellist_", "", 1)
        lst = await db_get_list(list_id)
        if not lst:
            return True
        if lst["created_by"] == user.id:
            await query.edit_message_text(
                f"🗑 Удалить список *{md(lst['name'] if lst else list_id)}*?\nВсе элементы будут удалены.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirmdellist_{list_id}")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="open_my_lists")],
                ])
            )
        else:
            await query.edit_message_text(
                f"📤 Убрать список *{md(lst['name'] if lst else list_id)}* из своих списков?\nСписок останется у владельца.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Да, убрать", callback_data=f"confirmdellist_{list_id}")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="open_my_lists")],
                ])
            )
        return True

    if data.startswith("confirmdellist_"):
        from handlers.session import register_message
        list_id = data.replace("confirmdellist_", "", 1)
        lst = await db_get_list(list_id)
        if not lst:
            return True
        name = lst["name"]

        if lst["created_by"] == user.id:
            await db_delete_list(list_id)
            try:
                await bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
                if main_menu_messages.get(user.id) == query.message.message_id:
                    main_menu_messages.pop(user.id, None)
            except Exception as e:
                logger.debug(f"Не удалось удалить подтверждение: {e}")
            text, keyboard = await _build_lists_menu_view(user.id)
            msg = await bot.send_message(chat_id=user.id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            register_message(user.id, chat_id, msg.message_id)
        else:
            await db_unshare_list(list_id, user.id)
            try:
                await bot.delete_message(chat_id=chat_id, message_id=query.message.message_id)
            except Exception:
                pass
            text, keyboard = await _build_lists_menu_view(user.id)
            msg = await bot.send_message(chat_id=user.id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
            register_message(user.id, chat_id, msg.message_id)
        return True

    if data.startswith("share_list_"):
        list_id = data[11:]
        lst = await db_get_list(list_id)
        if not lst:
            await query.edit_message_text(_pad("❌ Список не найден."))
            return True

        if lst["created_by"] != user.id:
            await query.edit_message_text(_pad("❌ Только владелец может поделиться списком."))
            return True

        members = await db_get_list_members(list_id)

        share_link = f"https://t.me/{bot.username}?start=invite_{list_id}"

        members_text = "👥 *Участники:*\n"
        if not members:
            members_text += "_Пока нет участников_\n"

        for m in members:
            perm = m.get("permission", "read")
            perm_label = "владелец" if perm == "owner" else ("редактор" if perm == "write" else "читатель")
            name = m.get("name") or f"User {m['user_id']}"
            members_text += f"• {name} — {perm_label}\n"

        members_text += f"\n📎 *Ссылка для приглашения:*\n`{share_link}`"

        await query.edit_message_text(
            f"📋 *{md(lst['name'])}*\n\n{members_text}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Показать список", callback_data="open_my_lists")],
                [InlineKeyboardButton("◀️ Назад", callback_data="open_my_lists"), btn_menu()],
            ])
        )
        return True

    if data.startswith("unshare_"):
        parts = data.split("_")
        list_id = parts[1]
        target_user_id = int(parts[2])

        lst = await db_get_list(list_id)
        if not lst:
            await query.edit_message_text(_pad("❌ Список не найден."))
            return True

        if lst["created_by"] != user.id:
            await query.edit_message_text(_pad("❌ Только владелец может удалить участника."))
            return True

        await db_unshare_list(list_id, target_user_id)
        members = await db_get_list_members(list_id)

        members_text = "👥 *Участники:*\n"
        for m in members:
            perm = m.get("permission", "read")
            perm_label = "владелец" if perm == "owner" else ("редактор" if perm == "write" else "читатель")
            name = m.get("name") or f"User {m['user_id']}"
            members_text += f"• {name} — {perm_label}\n"

        await query.edit_message_text(
            f"📋 *{md(lst['name'])}*\n\n{members_text}\n✅ Участник удалён.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("◀️ Назад", callback_data="open_my_lists")],
            ])
        )
        return True

    if data.startswith("listmenumode_"):
        from handlers.processors.lists import _get_list_menu_action_mode, _set_list_menu_action_mode
        mode = data[13:]
        current = _get_list_menu_action_mode(user.id)
        if current == mode:
            _set_list_menu_action_mode(user.id, "")
        else:
            _set_list_menu_action_mode(user.id, mode)
        text, keyboard = await _build_lists_menu_view(user.id)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    return False


async def show_lists_menu(bot, user_id, custom_text=None):
    from handlers.message_cache import main_menu_messages
    from handlers.session import register_message
    chat_id = main_menu_messages.get(user_id, user_id)
    text, keyboard = await _build_lists_menu_view(user_id, custom_text)
    msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    register_message(user_id, chat_id, msg.message_id)


async def show_list_items_for_user(bot, user_id, list_id, custom_text=None):
    from db import db_get_list, db_get_items
    from handlers.message_cache import main_menu_messages
    from handlers.session import register_message
    from utils.list_display import format_list_display
    from utils import md, _pad
    chat_id = main_menu_messages.get(user_id, user_id)
    lst = await db_get_list(list_id)
    items = await db_get_items(list_id)
    name = lst["name"] if lst else list_id
    title = format_list_display(name, items)
    text = custom_text or _pad(f"📋 *{md(title)}*\n\nЭлементов: {len(items)}")
    keyboard = [[InlineKeyboardButton("📋 Открыть список", callback_data=f"openlist_{list_id}")]]
    msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    register_message(user_id, chat_id, msg.message_id)
