"""Documents domain processor."""
import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    db_get_documents, db_rename_document,
    db_get_document_tags, db_get_document_tags_with_counts,
    db_get_or_create_document_tag, db_add_document_tag, db_rename_document_tag,
)
from keyboards import btn_cancel
from handlers.session import register_message, finish_process, processes, _sh_lock
from handlers.processors import register_message_handler, register_callback_handler
from utils import md, _pad

logger = logging.getLogger(__name__)


async def _send_document_tag_picker(bot, chat_id: int, user_id: int, state: dict, text: str | None = None):
    """Отправить новое сообщение с пикером тегов при добавлении файла."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    tags = await db_get_document_tags_with_counts(user_id)
    selected = set(state.get("tag_ids", []))
    keyboard = []

    for tag in tags:
        marker = "☑️" if tag["id"] in selected else "☐"
        keyboard.append([InlineKeyboardButton(f"{marker} {tag['name']} ({tag['count']})", callback_data=f"doctagpick_{tag['id']}")])

    keyboard.append([InlineKeyboardButton("➕ Новый тег", callback_data="doctag_new")])
    keyboard.append([InlineKeyboardButton("✅ Продолжить", callback_data="doctag_done"), btn_cancel()])

    message_text = _pad("🏷 *Выбери теги файла*")
    if text:
        message_text += f"\n\n{text}"
    if not tags:
        message_text += "\n\nТегов пока нет. Можно создать новый или продолжить с тегом *разное*."

    msg = await bot.send_message(chat_id=chat_id, text=message_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    register_message(user_id, chat_id, msg.message_id)
    return msg


async def _send_document_tag_edit(bot, chat_id: int, user_id: int, doc_id: int, text: str | None = None):
    """Отправить новое сообщение с пикером тегов при редактировании файла."""
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    tags = await db_get_document_tags_with_counts(user_id)
    selected_tags = await db_get_document_tags(user_id, doc_id)
    selected = {tag["id"] for tag in selected_tags}
    keyboard = []

    for tag in tags:
        marker = "☑️" if tag["id"] in selected else "☐"
        keyboard.append([InlineKeyboardButton(f"{marker} {tag['name']} ({tag['count']})", callback_data=f"doctagedit_{doc_id}_{tag['id']}")])

    keyboard.append([InlineKeyboardButton("➕ Новый тег", callback_data=f"doctageditnew_{doc_id}")])
    keyboard.append([InlineKeyboardButton("✅ Готово", callback_data="open_documents")])

    message_text = _pad("🏷 *Теги файла*")
    if text:
        message_text += f"\n\n{text}"
    msg = await bot.send_message(chat_id=chat_id, text=message_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    register_message(user_id, chat_id, msg.message_id)
    return msg

# ─── Sort Mode ───────────────────────────────────────────────────────────────
# Хранит режим сортировки для каждого user_id: "" | "up" | "down"
_doc_sort_modes: dict[int, str] = {}

def _get_doc_sort_mode(user_id: int) -> str:
    return _doc_sort_modes.get(user_id, "")

def _set_doc_sort_mode(user_id: int, mode: str):
    if mode:
        _doc_sort_modes[user_id] = mode
    else:
        _doc_sort_modes.pop(user_id, None)

# ─── Action Mode ─────────────────────────────────────────────────────────────
# Хранит текущий режим действий: "" | "delete" | "rename" | "file" | "tags"
_doc_action_modes: dict[int, str] = {}

def _get_doc_action_mode(user_id: int) -> str:
    return _doc_action_modes.get(user_id, "")

def _set_doc_action_mode(user_id: int, mode: str):
    if mode:
        _doc_action_modes[user_id] = mode
    else:
        _doc_action_modes.pop(user_id, None)


# ─── Document ─────────────────────────────────────────────────────────────────

@register_message_handler("document")
async def handle_document_message(update, context, proc, state):
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")

    # DEBUG: trace emoji/name handling
    logger.info(f"DOC HANDLE: user={user.id}, step={step}, text=({type(text).__name__}){repr(text)[:50]}, text_len={len(text)}, text_empty={not text}")

    if step == "waiting_name":
        logger.info(f"DOC NAME: saving name={repr(text)[:50]} for user={user.id}")
        state["name"] = text
        state["step"] = "selecting_tags"
        state["tag_ids"] = []
        await _send_document_tag_picker(bot, chat_id, user.id, state, f"Название: *{md(text)}*")


# ─── Document New Tag ─────────────────────────────────────────────────────────

@register_message_handler("document_new_tag")
async def handle_document_new_tag(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")
    logger.info(f"DOC NEW TAG: user={user.id}, step={step}, text=({type(text).__name__}){repr(text)[:50]}")
    if step == "waiting_tag_name":
        tag_name = text.strip()
        if not tag_name:
            reply = await message.reply_text(_pad("❌ Название тега не может быть пустым."), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
            register_message(user.id, chat_id, reply.message_id)
            return

        tag_id = await db_get_or_create_document_tag(user.id, tag_name)
        if state.get("return_to") == "edit":
            doc_id = state.get("doc_id")
            await db_add_document_tag(user.id, doc_id, tag_name)
            await finish_process(bot, user.id, show_menu=False)
            await _send_document_tag_edit(bot, chat_id, user.id, doc_id, f"✅ Тег *{md(tag_name)}* добавлен.")
            return

        state["tag_ids"] = list(set(state.get("tag_ids", [])) | {tag_id})
        state["step"] = "selecting_tags"
        async with _sh_lock:
            proc["type"] = "document"
            proc["state"] = state
        await _send_document_tag_picker(bot, chat_id, user.id, state, f"✅ Тег *{md(tag_name)}* добавлен.")


# ─── Document Tag Rename ──────────────────────────────────────────────────────

@register_message_handler("document_tag_rename")
async def handle_document_tag_rename(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")
    logger.info(f"DOC TAG RENAME: user={user.id}, step={step}, text=({type(text).__name__}){repr(text)[:50]}")
    if step == "waiting_name":
        tag_id = state.get("tag_id")
        old_name = state.get("old_name", "")
        new_name = text.strip()
        if not new_name:
            reply = await message.reply_text(_pad("❌ Название тега не может быть пустым."), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
            register_message(user.id, chat_id, reply.message_id)
            return

        renamed = await db_rename_document_tag(user.id, tag_id, new_name)
        await finish_process(bot, user.id, show_menu=False)
        if renamed:
            note = f"✅ Тег *{md(old_name)}* переименован в *{md(renamed['name'])}*."
        else:
            note = "❌ Тег не найден."
        from handlers.callbacks.documents import show_document_tag_rename_menu
        await show_document_tag_rename_menu(bot, user.id, note)


# ─── Document Rename ──────────────────────────────────────────────────────────

@register_message_handler("document_rename")
async def handle_document_rename(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")
    doc_id = state.get("doc_id")
    logger.info(f"DOC RENAME: user={user.id}, step={step}, doc_id={doc_id}, text=({type(text).__name__}){repr(text)[:50]}")
    if step == "waiting_name":
        new_name = text.strip()
        if not new_name:
            reply = await message.reply_text(_pad("❌ Название не может быть пустым."), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
            register_message(user.id, chat_id, reply.message_id)
            return

        docs = await db_get_documents(user.id)
        doc = next((d for d in docs if d["id"] == doc_id), None)
        if doc:
            for d in docs:
                if d["name"] == new_name and d["id"] != doc_id:
                    reply = await message.reply_text(_pad("⚠️ Файл с таким названием уже есть!"), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
                    register_message(user.id, chat_id, reply.message_id)
                    return
            await db_rename_document(user.id, doc_id, new_name)
            await finish_process(bot, user.id, show_menu=False)
            await asyncio.sleep(0.5)
            from handlers.callbacks.documents import show_documents_list
            await show_documents_list(bot, user.id, f"✅ Название изменено: *{md(new_name)}*")


# ─── Callback Handlers ────────────────────────────────────────────────────────


async def _show_documents(query, custom_text: str = None):
    """Показать список файлов (редактирует текущее сообщение)."""
    user = query.from_user
    from handlers.session import is_pin_unlocked
    from db import db_has_pin

    has_pin = await db_has_pin(user.id)

    if has_pin and not is_pin_unlocked(user.id):
        chat_id = query.message.chat_id
        from handlers.session import start_process
        start_process(user.id, chat_id, "enter_pin", {"step": "waiting_pin", "return_to": "open_documents"}, query.message.message_id)
        await query.edit_message_text(
            _pad("🔐 *Введите PIN-код*\n\nДоступ к файлам защищён PIN-кодом."),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="go_menu")]
            ])
        )
        return

    if not has_pin:
        chat_id = query.message.chat_id
        from handlers.session import start_process
        start_process(user.id, chat_id, "setpin_first", {"step": "waiting_choice", "return_to": "open_documents"}, query.message.message_id)
        await query.edit_message_text(
            _pad("🔐 *Защита данных*\n\nЭтот раздел содержит чувствительные данные.\n\nУстановить PIN-код для защиты?"),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Установить PIN", callback_data="pin_setup_now")],
                [InlineKeyboardButton("⏭ Пропустить", callback_data="open_documents_unlocked")],
                [InlineKeyboardButton("❌ Отмена", callback_data="go_menu")],
            ])
        )
        return

    await _show_documents_content(query, custom_text)


async def _show_documents_content(query, custom_text: str = None):
    """Показать список файлов без PIN-проверки (редактирует текущее сообщение)."""
    text, keyboard = await _build_documents_content(query.from_user.id, custom_text)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))


async def _send_documents_content(bot, chat_id: int, user_id: int, custom_text: str = None):
    """Отправить список файлов новым сообщением."""
    text, keyboard = await _build_documents_content(user_id, custom_text)
    msg = await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    register_message(user_id, chat_id, msg.message_id)


async def _build_documents_content(user_id: int, custom_text: str = None) -> tuple[str, list]:
    """Построить текст и клавиатуру списка файлов."""
    from handlers.callbacks.documents import _build_documents_view
    return await _build_documents_view(user_id, custom_text)


@register_callback_handler("open_documents_unlocked")
async def cb_open_documents_unlocked(query, context, data, user, chat_id, bot):
    """Открыть файлы без PIN-проверки (через кнопку Пропустить)."""
    if user.id in processes:
        del processes[user.id]
    await _show_documents_content(query)


# ─── Document Refresh (file replacement) ──────────────────────────────────────

@register_message_handler("document_refresh")
async def handle_document_refresh(update, context, proc, state):
    from telegram import InlineKeyboardMarkup
    user = update.effective_user
    chat_id = update.effective_chat.id
    message = update.message or update.effective_message
    text = message.text.strip() if message.text else ""
    bot = context.bot
    register_message(user.id, chat_id, message.message_id)

    step = state.get("step")
    logger.info(f"DOC REFRESH: user={user.id}, step={step}, text=({type(text).__name__}){repr(text)[:50]}")
    if step == "waiting_file":
        await message.reply_text(
            "Перешли обновлённый файл из избранного:",
            reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
        )
        return
