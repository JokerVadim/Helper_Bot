"""Document callback handlers."""
import asyncio
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from handlers.callbacks.base import domain_handler, _delete_ok_messages

logger = logging.getLogger(__name__)


def _format_doc_button(user_id, doc):
    return doc["name"]


async def _build_documents_view(user_id, message=None, tag_id=None):
    from handlers.processors.documents import _get_doc_sort_mode, _get_doc_action_mode
    from db import db_get_documents, db_get_documents_by_tag, db_get_document_tag, db_get_document_tags_with_counts
    from utils import md, _pad
    from keyboards import btn_menu

    sort_mode = _get_doc_sort_mode(user_id)
    action_mode = _get_doc_action_mode(user_id)

    tag = None
    all_docs = await db_get_documents(user_id)
    if tag_id is not None:
        tag = await db_get_document_tag(user_id, tag_id)
        docs = await db_get_documents_by_tag(user_id, tag_id) if tag else []
    else:
        docs = all_docs

    tags = await db_get_document_tags_with_counts(user_id)
    visible_tags = [doc_tag for doc_tag in tags if doc_tag["count"] > 0]
    title = f"📁 *Файлы* / 📁 *{md(tag['name'])}*" if tag else f"📁 *Файлы* / *Все* ({len(docs)})"
    text = title
    if action_mode:
        _mode_labels = {"delete": "🗑 Удалить", "rename": "✏️ Название", "file": "✏️ Файл", "tags": "🏷 Теги"}
        text += f"\n\n*Режим:* ✅ {_mode_labels.get(action_mode, action_mode)}"
    if message:
        text += f"\n\n{message}"
    if not docs:
        text += "\n\nПока нет сохранённых файлов." if tag is None else "\n\nВ этой категории пока нет файлов."
    text = _pad(text)

    keyboard = []
    for doc in docs:
        if sort_mode == "up":
            keyboard.append([InlineKeyboardButton(f"⬆️ {_format_doc_button(user_id, doc)}", callback_data=f"docsortitem_{doc['id']}_up")])
        elif sort_mode == "down":
            keyboard.append([InlineKeyboardButton(f"⬇️ {_format_doc_button(user_id, doc)}", callback_data=f"docsortitem_{doc['id']}_down")])
        elif action_mode == "delete":
            keyboard.append([InlineKeyboardButton(f"🗑 {_format_doc_button(user_id, doc)}", callback_data=f"deldoc_{doc['id']}")])
        elif action_mode == "rename":
            keyboard.append([InlineKeyboardButton(f"✏️ {_format_doc_button(user_id, doc)}", callback_data=f"editdocname_{doc['id']}")])
        elif action_mode == "file":
            keyboard.append([InlineKeyboardButton(f"🔄 {_format_doc_button(user_id, doc)}", callback_data=f"refreshdoc_{doc['id']}")])
        elif action_mode == "tags":
            keyboard.append([InlineKeyboardButton(_format_doc_button(user_id, doc), callback_data=f"edittags_{doc['id']}")])
        else:
            keyboard.append([InlineKeyboardButton(_format_doc_button(user_id, doc), callback_data=f"showdoc_{doc['id']}")])

    delete_lbl = "✅ 🗑 Удалить" if action_mode == "delete" else "🗑 Удалить"
    rename_lbl = "✅ ✏️ Название" if action_mode == "rename" else "✏️ Название"
    file_lbl = "✅ ✏️ Файл" if action_mode == "file" else "✏️ Файл"
    tags_lbl = "✅ 🏷 Теги" if action_mode == "tags" else "🏷 Теги"
    keyboard.append([
        InlineKeyboardButton("✚ Добавить", callback_data="add_document"),
        InlineKeyboardButton(delete_lbl, callback_data="doctogglemode_delete"),
    ])
    keyboard.append([
        InlineKeyboardButton(rename_lbl, callback_data="doctogglemode_rename"),
        InlineKeyboardButton(file_lbl, callback_data="doctogglemode_file"),
    ])

    sort_btn_label, sort_btn_mode = {
        "": ("🔢 Сортировка", "up"),
        "up": ("⬆️ Сортировка", "down"),
        "down": ("⬇️ Сортировка", "off"),
    }[sort_mode]
    keyboard.append([
        InlineKeyboardButton(tags_lbl, callback_data="doctogglemode_tags"),
        InlineKeyboardButton(sort_btn_label, callback_data=f"doctoggle_{sort_btn_mode}"),
    ])
    keyboard.append([InlineKeyboardButton("🔒 Закрыть", callback_data="lock_now")])
    keyboard.append([btn_menu()])

    if visible_tags:
        tag_buttons = [InlineKeyboardButton("Все" if tag is not None else "• Все", callback_data="open_documents")]
        for doc_tag in visible_tags:
            label = doc_tag["name"] if tag_id != doc_tag["id"] else f"• {doc_tag['name']}"
            tag_buttons.append(InlineKeyboardButton(label, callback_data=f"opendoctag_{doc_tag['id']}"))
        for i in range(0, len(tag_buttons), 4):
            keyboard.append(tag_buttons[i:i + 4])
    return text, keyboard


async def _show_document_tag_picker(query, selected_tag_ids=None, doc_id=None, message=None):
    from db import db_get_document_tags_with_counts
    from keyboards import btn_cancel, btn_menu
    from utils import _pad

    user = query.from_user
    tags = await db_get_document_tags_with_counts(user.id)
    tags = [t for t in tags if t["count"] > 0]
    selected_tag_ids = selected_tag_ids or set()

    keyboard = []
    for tag in tags:
        marker = "☑️" if tag["id"] in selected_tag_ids else "☐"
        prefix = "doctagpick" if doc_id is None else f"doctagedit_{doc_id}"
        keyboard.append([InlineKeyboardButton(f"{marker} {tag['name']} ({tag['count']})", callback_data=f"{prefix}_{tag['id']}")])

    if doc_id is None:
        keyboard.append([InlineKeyboardButton("➕ Новый тег", callback_data="doctag_new")])
        keyboard.append([InlineKeyboardButton("✅ Продолжить", callback_data="doctag_done"), btn_cancel()])
        title = "🏷 *Выбери теги файла*"
    else:
        keyboard.append([InlineKeyboardButton("➕ Новый тег", callback_data=f"doctageditnew_{doc_id}")])
        keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="open_documents")])
        keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="open_documents"), btn_menu()])
        title = "🏷 *Теги файла*"

    text = _pad(title)
    if message:
        text += f"\n\n{message}"
    if not tags:
        text += "\n\nТегов пока нет. Можно создать новый или продолжить с тегом *разное*."
    return await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _send_media_by_type(bot, chat_id, file_id, file_type, caption=None):
    send_kwargs = {"chat_id": chat_id}
    if caption:
        send_kwargs["caption"] = caption

    if file_type == "photo":
        send_kwargs["photo"] = file_id
        return await bot.send_photo(**send_kwargs)
    elif file_type == "video":
        send_kwargs["video"] = file_id
        send_kwargs["supports_streaming"] = True
        return await bot.send_video(**send_kwargs)
    elif file_type == "audio":
        send_kwargs["audio"] = file_id
        return await bot.send_audio(**send_kwargs)
    elif file_type == "animation":
        send_kwargs["animation"] = file_id
        return await bot.send_animation(**send_kwargs)
    elif file_type == "voice":
        send_kwargs["voice"] = file_id
        return await bot.send_voice(**send_kwargs)
    elif file_type == "video_note":
        send_kwargs["video_note"] = file_id
        return await bot.send_video_note(**send_kwargs)
    elif file_type == "sticker":
        send_kwargs["sticker"] = file_id
        return await bot.send_sticker(**send_kwargs)
    else:
        send_kwargs["document"] = file_id
        return await bot.send_document(**send_kwargs)


@domain_handler
async def handle_documents_callbacks(query, context, data, user, chat_id, bot):
    from db import (
        db_get_documents, db_get_document_tags, db_get_document_tags_with_counts,
        db_get_document_tag, db_add_document_tag, db_remove_document_tag,
        db_get_document_photos, db_delete_document,
        db_update_doc_sort_order,
    )
    from handlers.processors.documents import (
        _show_documents, _show_documents_content,
        _get_doc_action_mode, _set_doc_action_mode,
        _set_doc_sort_mode,
    )
    from handlers.session import start_process, processes
    from keyboards import btn_cancel, btn_menu
    from utils import md, _pad

    if data == "open_documents":
        await _show_documents(query)
        return True

    if data.startswith("opendoctag_"):
        tag_id = int(data.split("_")[1])
        text, keyboard = await _build_documents_view(user.id, tag_id=tag_id)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    if data == "add_document":
        start_process(user.id, chat_id, "document", {"step": "waiting_name"}, query.message.message_id)
        await query.edit_message_text(
            _pad("📁 *Добавить файл*\n\nВведи название файла (например: Паспорт, Диплом):"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("doctagpick_"):
        tag_id = int(data.split("_")[1])
        proc = processes.get(user.id)
        if not proc or proc.get("type") != "document":
            await query.answer("Добавление файла не найдено", show_alert=True)
            return True
        selected = set(proc["state"].get("tag_ids", []))
        if tag_id in selected:
            selected.remove(tag_id)
        else:
            selected.add(tag_id)
        proc["state"]["tag_ids"] = list(selected)
        await _show_document_tag_picker(query, selected)
        return True

    if data == "doctag_new":
        proc = processes.get(user.id)
        if not proc or proc.get("type") != "document":
            await query.answer("Добавление файла не найдено", show_alert=True)
            return True
        proc["type"] = "document_new_tag"
        proc["state"]["return_to"] = "create"
        proc["state"]["step"] = "waiting_tag_name"
        await query.edit_message_text(
            _pad("🏷 Введи название нового тега:"),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data == "doctag_done":
        proc = processes.get(user.id)
        if not proc or proc.get("type") != "document":
            await query.answer("Добавление файла не найдено", show_alert=True)
            return True
        proc["state"]["step"] = "waiting_file"
        await query.edit_message_text(
            f"📄 Название: *{md(proc['state'].get('name', 'Файл'))}*\n\nТеперь отправь файл, фото или медиа:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("showdoc_"):
        doc_id = int(data.split("_")[1])
        docs = await db_get_documents(user.id)
        doc = next((d for d in docs if d["id"] == doc_id), None)
        if not doc:
            await query.edit_message_text(_pad("❌ Файл не найден."))
            return True

        try:
            file_id = doc["file_id"]
            file_type = doc.get("file_type", "document")
            source_chat_id = doc.get("source_chat_id")
            source_message_id = doc.get("source_message_id")

            photos = await db_get_document_photos(doc_id)

            sent_msg = None
            if len(photos) > 1:
                from telegram import InputMediaPhoto
                media_group = []
                for p in photos:
                    media_group.append(InputMediaPhoto(media=p["file_id"]))
                sent_msgs = await bot.send_media_group(chat_id=chat_id, media=media_group)
                for m in sent_msgs:
                    from handlers.session import register_message
                    register_message(user.id, chat_id, m.message_id)

                first_msg_id = sent_msgs[0].message_id if sent_msgs else 0
                last_msg_id = sent_msgs[-1].message_id if sent_msgs else 0
                ok_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("OK", callback_data=f"doc_ok_{first_msg_id}_{last_msg_id}_{query.message.message_id}")
                ]])
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"📄 *{md(doc['name'])}* ({len(photos)} фото)\n🏷 {md(', '.join(tag['name'] for tag in await db_get_document_tags(user.id, doc_id)))}",
                    parse_mode="Markdown",
                    reply_markup=ok_markup
                )
            else:
                if source_chat_id and source_message_id:
                    sent_msg = await bot.copy_message(
                        chat_id=chat_id,
                        from_chat_id=source_chat_id,
                        message_id=source_message_id
                    )
                else:
                    sent_msg = await _send_media_by_type(bot, chat_id, file_id, file_type)

                if sent_msg:
                    from handlers.session import register_message
                    register_message(user.id, chat_id, sent_msg.message_id)

                doc_msg_id = sent_msg.message_id if sent_msg else 0
                ok_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton("OK", callback_data=f"doc_ok_{doc_msg_id}_{query.message.message_id}")
                ]])
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"📄 *{md(doc['name'])}*\n🏷 {md(', '.join(tag['name'] for tag in await db_get_document_tags(user.id, doc_id)))}",
                    parse_mode="Markdown",
                    reply_markup=ok_markup
                )
        except Exception as e:
            logger.error(f"Ошибка отправки файла {doc_id}: {e}")
            await query.edit_message_text(
                f"📄 *{md(doc['name'])}*\n\n⚠️ Не удалось загрузить файл. Возможно, он был удалён.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✏️ Название", callback_data=f"editdocname_{doc_id}"),
                     InlineKeyboardButton("🔄 Файл", callback_data=f"refreshdoc_{doc_id}")],
                    [InlineKeyboardButton("🏷 Теги", callback_data=f"edittags_{doc_id}")],
                    [InlineKeyboardButton("🗑 Удалить", callback_data=f"deldoc_{doc_id}")],
                    [InlineKeyboardButton("🔙 К списку", callback_data="open_documents")],
                    [btn_menu()],
                ])
            )
        return True

    if data == "refresh_all_docs":
        await _delete_ok_messages(bot, chat_id, query.message.message_id)
        docs = await db_get_documents(user.id)
        if not docs:
            from keyboards import show_main_menu
            await show_main_menu(bot, user.id, "📁 Нет файлов для обновления.")
            return True

        await query.edit_message_text(
            _pad(f"📁 Начинаю обновление {len(docs)} файлов...\n\nЭто может занять некоторое время."),
            parse_mode="Markdown"
        )

        for doc in docs:
            try:
                file_id = doc["file_id"]
                file_type = doc.get("file_type", "document")
                source_chat_id = doc.get("source_chat_id")
                source_message_id = doc.get("source_message_id")

                if source_chat_id and source_message_id:
                    sent = await bot.copy_message(chat_id=chat_id, from_chat_id=source_chat_id, message_id=source_message_id)
                else:
                    sent = await _send_media_by_type(bot, chat_id, file_id, file_type)

                await asyncio.sleep(0.5)
                await bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
            except Exception as e:
                logger.error(f"Ошибка обновления файла {doc['id']}: {e}")

        from keyboards import show_main_menu
        await show_main_menu(bot, user.id, f"✅ Все {len(docs)} файлов обновлены!")
        return True

    if data == "snooze_docs_refresh":
        from handlers.session import register_message
        await _delete_ok_messages(bot, chat_id, query.message.message_id)
        msg = await bot.send_message(chat_id=chat_id, text=_pad("🔔 Напомню завтра."))
        register_message(user.id, chat_id, msg.message_id)
        return True

    if data.startswith("doc_ok_"):
        parts = data.split("_")
        if len(parts) >= 5:
            first_msg_id = int(parts[2])
            last_msg_id = int(parts[3])
            ok_msg_id = query.message.message_id
            msg_ids_to_delete = list(range(first_msg_id, last_msg_id + 1))
            msg_ids_to_delete.append(ok_msg_id)
            await _delete_ok_messages(bot, chat_id, *msg_ids_to_delete)
        elif len(parts) == 4:
            doc_msg_id = int(parts[2])
            ok_msg_id = query.message.message_id
            await _delete_ok_messages(bot, chat_id, doc_msg_id, ok_msg_id)
        return True

    if data.startswith("edittags_"):
        doc_id = int(data.split("_")[1])
        tags = await db_get_document_tags(user.id, doc_id)
        await _show_document_tag_picker(query, {tag["id"] for tag in tags}, doc_id=doc_id)
        return True

    if data.startswith("doctagedit_"):
        parts = data.split("_")
        doc_id = int(parts[1])
        tag_id = int(parts[2])
        current_tags = await db_get_document_tags(user.id, doc_id)
        selected_ids = {tag["id"] for tag in current_tags}
        if tag_id in selected_ids:
            await db_remove_document_tag(user.id, doc_id, tag_id)
            selected_ids.remove(tag_id)
        else:
            tag = await db_get_document_tag(user.id, tag_id)
            if tag:
                await db_add_document_tag(user.id, doc_id, tag["name"])
                selected_ids.add(tag_id)
        current_tags = await db_get_document_tags(user.id, doc_id)
        await _show_document_tag_picker(query, {tag["id"] for tag in current_tags}, doc_id=doc_id)
        return True

    if data.startswith("doctageditnew_"):
        doc_id = int(data.split("_")[1])
        start_process(user.id, chat_id, "document_new_tag", {"step": "waiting_tag_name", "return_to": "edit", "doc_id": doc_id}, query.message.message_id)
        await query.edit_message_text(
            _pad("🏷 Введи название нового тега:"),
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("editdocname_"):
        doc_id = int(data.split("_")[1])
        docs = await db_get_documents(user.id)
        doc = next((d for d in docs if d["id"] == doc_id), None)
        if not doc:
            await query.edit_message_text(_pad("❌ Файл не найден."))
            return True
        start_process(user.id, chat_id, "document_rename", {"doc_id": doc_id, "step": "waiting_name", "old_name": doc["name"]}, query.message.message_id)
        await query.edit_message_text(
            _pad(f"✏️ *Редактировать название*\n\nТекущее название: `{md(doc['name'])}`\n\nВведи новое название:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("refreshdoc_"):
        doc_id = int(data.split("_")[1])
        docs = await db_get_documents(user.id)
        doc = next((d for d in docs if d["id"] == doc_id), None)
        if not doc:
            await query.answer("❌ Файл не найден", show_alert=True)
            return True
        start_process(user.id, chat_id, "document_refresh", {"doc_id": doc_id, "step": "waiting_file"}, query.message.message_id)
        await query.edit_message_text(
            _pad(f"📄 *{md(doc['name'])}*\n\nОтправь новый скан файла:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("deldoc_"):
        doc_id = int(data.split("_")[1])
        docs = await db_get_documents(user.id)
        doc = next((d for d in docs if d["id"] == doc_id), None)
        if not doc:
            await query.edit_message_text(_pad("❌ Файл не найден."))
            return True

        await query.edit_message_text(
            f"🗑 Удалить файл *{md(doc['name'])}*?",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Да, удалить", callback_data=f"confirmdeldoc_{doc_id}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="open_documents"), btn_menu()],
            ])
        )
        return True

    if data.startswith("confirmdeldoc_"):
        doc_id = int(data.split("_")[1])
        await db_delete_document(user.id, doc_id)
        await _show_documents_content(query, "✅ Файл удалён.")
        return True

    if data == "edit_docs_list":
        docs = await db_get_documents(user.id)
        if not docs:
            await query.edit_message_text(_pad("📄 *Редактирование файлов*\n\nНет сохранённых файлов."), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[btn_menu()]]))
            return True

        keyboard = []
        for doc in docs:
            keyboard.append([
                InlineKeyboardButton(f"✏️ {doc['name']}", callback_data=f"editdoc_{doc['id']}")
            ])
        keyboard.append([btn_menu()])
        await query.edit_message_text(_pad("📄 *Редактирование*\n\nВыбери файл для редактирования:"), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    if data.startswith("doctogglemode_"):
        mode = data[14:]
        current = _get_doc_action_mode(user.id)
        if current == mode:
            _set_doc_action_mode(user.id, "")
        else:
            _set_doc_action_mode(user.id, mode)
        await _show_documents_content(query)
        return True

    if data == "docs_mode_rename_tags":
        tags = await db_get_document_tags_with_counts(user.id)
        tags = [tag for tag in tags if tag["count"] > 0]
        if not tags:
            await query.edit_message_text(_pad("✏️ *Переименование тегов*\n\nТегов пока нет."), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[btn_menu()]]))
        else:
            keyboard = []
            for tag in tags:
                keyboard.append([InlineKeyboardButton(f"{tag['name']} ({tag['count']})", callback_data=f"renametag_{tag['id']}")])
            keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="open_documents"), btn_menu()])
            await query.edit_message_text(_pad("✏️ *Выбери тег для переименования:*"), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    if data.startswith("renametag_"):
        tag_id = int(data.split("_")[1])
        tag = await db_get_document_tag(user.id, tag_id)
        if not tag:
            await query.answer("❌ Тег не найден", show_alert=True)
            return True
        start_process(user.id, chat_id, "document_tag_rename", {"step": "waiting_name", "tag_id": tag_id, "old_name": tag["name"]}, query.message.message_id)
        await query.edit_message_text(
            _pad(f"✏️ *Переименовать тег*\n\nТекущее название: `{md(tag['name'])}`\n\nВведи новое название:"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return True

    if data.startswith("doctoggle_"):
        mode = data.split("_", 1)[1]
        target_mode = {"up": "up", "down": "down", "off": ""}[mode]
        _set_doc_sort_mode(user.id, target_mode)
        if target_mode:
            _set_doc_action_mode(user.id, "")
        text, keyboard = await _build_documents_view(user.id)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    if data.startswith("docsortitem_"):
        parts = data.split("_")
        doc_id = int(parts[1])
        direction = parts[2]
        docs = await db_get_documents(user.id)
        doc_ids = [d['id'] for d in docs]
        if doc_id not in doc_ids:
            await query.answer("❌ Файл не найден", show_alert=True)
            return True
        idx = doc_ids.index(doc_id)
        if direction == "up" and idx > 0:
            doc_ids[idx], doc_ids[idx - 1] = doc_ids[idx - 1], doc_ids[idx]
        elif direction == "down" and idx < len(doc_ids) - 1:
            doc_ids[idx], doc_ids[idx + 1] = doc_ids[idx + 1], doc_ids[idx]
        else:
            await query.answer("⛔ Крайняя позиция", show_alert=False)
            return True
        for i, d_id in enumerate(doc_ids):
            await db_update_doc_sort_order(user.id, d_id, i)
        text, keyboard = await _build_documents_view(user.id)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
        return True

    if data.startswith("editdoc_"):
        doc_id = int(data.split("_")[1])
        docs = await db_get_documents(user.id)
        doc = next((d for d in docs if d["id"] == doc_id), None)
        if not doc:
            await query.edit_message_text(_pad("❌ Файл не найден."))
            return True
        tags = await db_get_document_tags(user.id, doc_id)
        tag_text = ", ".join(tag["name"] for tag in tags) or "разное"

        await query.edit_message_text(
            f"✏️ *{md(doc['name'])}*\n🏷 {md(tag_text)}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Название", callback_data=f"editdocname_{doc_id}")],
                [InlineKeyboardButton("🏷 Теги", callback_data=f"edittags_{doc_id}")],
                [InlineKeyboardButton("🖼 Файл", callback_data=f"refreshdoc_{doc_id}")],
                [InlineKeyboardButton("🗑 Удалить", callback_data=f"deldoc_{doc_id}")],
                [InlineKeyboardButton("◀️ Назад", callback_data="edit_docs_list")],
                [btn_menu()],
            ])
        )
        return True

    return False


async def show_documents_list(bot, user_id, custom_text=None):
    """Send documents list as a new message."""
    from handlers.message_cache import main_menu_messages
    from handlers.session import register_message
    chat_id = main_menu_messages.get(user_id, user_id)
    text, keyboard = await _build_documents_view(user_id, custom_text)
    msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    register_message(user_id, chat_id, msg.message_id)


async def show_document_tag_rename_menu(bot, user_id, custom_text=None):
    """Show tag rename menu."""
    from db import db_get_document_tags_with_counts
    from handlers.message_cache import main_menu_messages
    from handlers.session import register_message
    from keyboards import btn_menu
    from utils import _pad
    chat_id = main_menu_messages.get(user_id, user_id)
    tags = await db_get_document_tags_with_counts(user_id)
    tags = [tag for tag in tags if tag["count"] > 0]
    keyboard = []
    for tag in tags:
        keyboard.append([InlineKeyboardButton(f"{tag['name']} ({tag['count']})", callback_data=f"renametag_{tag['id']}")])
    keyboard.append([InlineKeyboardButton("◀️ Назад", callback_data="open_documents"), btn_menu()])
    text = _pad("✏️ *Выбери тег для переименования:*")
    if custom_text:
        text = custom_text + "\n\n" + text
    msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    register_message(user_id, chat_id, msg.message_id)
