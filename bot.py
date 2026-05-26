"""
Telegram Assistant Bot
Process Manager + SQLite + Groq AI
"""
import asyncio
import io
import logging
import os
import sys
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application

from dotenv import load_dotenv
load_dotenv()

from db import (
    init_db,
    db_delete_document_photos,
    db_delete_reminder,
    db_get_document_tag,
    db_get_documents,
    db_get_pending_reminders,
    db_update_reminder,
)
import ai
from ai import init_ai
from app_handlers import register_handlers, set_commands
from handlers.session import reminder_counter, _store_memory_reminder, register_message
from handlers.reminders import _schedule_reminder, _row_to_reminder
from scheduler import register_jobs
from utils import md, _pad, fire_and_forget

# ── Настройка UTF-8 для консоли Windows ──
# Без этого эмодзи в логах и print превращаются в кракозябры на cp1251
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Логирование в файл и консоль
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"bot_{datetime.now().strftime('%Y%m%d')}.log")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


# Функции перенесены в handlers/processors/documents.py для устранения циклического импорта.
# Реэкспортируем для обратной совместимости с любыми внешними импортами.


async def restore_reminders(app: Application):
    from datetime import datetime
    from utils.time_utils import next_repeat_time

    rows = await db_get_pending_reminders()
    restored = 0
    missed = 0
    for row in rows:
        chat_id  = row["chat_id"]
        rid      = row["rid"]
        text     = row["text"]
        fire_at  = datetime.strptime(row["fire_at"], "%Y-%m-%d %H:%M:%S")
        is_timer = bool(row["is_timer"])
        repeat_type = row.get("repeat_type") or "none"
        minutes = row.get("minutes") or 0
        repeat_days = row.get("repeat_days") or ""
        delivered = bool(row.get("delivered", 0))
        delay    = (fire_at - datetime.now()).total_seconds()

        if delivered:
            # Одноразовые delivered не добавляем в память - они уже сработали
            if repeat_type == "none":
                continue
            _store_memory_reminder(chat_id, _row_to_reminder(row))
            reminder_counter[chat_id] = max(reminder_counter.get(chat_id, 0), rid)
            continue

        if delay <= 0:
            missed += 1
            try:
                title = "⏱ Пропущенный таймер" if is_timer else "⏰ Пропущенное напоминание"
                # Для циклических напоминаний OK = просто скрыть сообщение, не удалять напоминание
                ok_callback = f"reminder_ok_{rid}" if repeat_type != "none" else f"delrem_{rid}"
                msg = await app.bot.send_message(
                    chat_id=chat_id,
                    text=_pad(f"{title}\n\n{md(text)}\n\n_Было запланировано: {fire_at.strftime('%d.%m %H:%M')}_"),
                    parse_mode="Markdown",
                    reply_markup=None if is_timer else InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("+10м", callback_data=f"snooze_{rid}_10m"),
                            InlineKeyboardButton("+1ч", callback_data=f"snooze_{rid}_1h"),
                            InlineKeyboardButton("Завтра", callback_data=f"snooze_{rid}_1d"),
                        ],
                        [InlineKeyboardButton("OK", callback_data=ok_callback)],
                    ])
                )
                register_message(chat_id, chat_id, msg.message_id)
            except Exception as e:
                logger.error(f"Missed reminder send error: {e}")

            if is_timer:
                await db_delete_reminder(chat_id, rid)
                continue

            if repeat_type != "none":
                next_time = next_repeat_time(fire_at, repeat_type, minutes=minutes, repeat_days=repeat_days)
                if next_time:
                    await db_update_reminder(chat_id, rid, fire_at=next_time, delivered=False)
                    _schedule_reminder(app.job_queue, chat_id, rid, text, next_time, False, repeat_type, minutes=minutes, repeat_days=repeat_days)
                    restored += 1
                continue

            await db_update_reminder(chat_id, rid, delivered=True)
            row["delivered"] = 1
            _store_memory_reminder(chat_id, _row_to_reminder(row))
            reminder_counter[chat_id] = max(reminder_counter.get(chat_id, 0), rid)
            continue

        _schedule_reminder(app.job_queue, chat_id, rid, text, fire_at, is_timer, repeat_type, minutes=minutes, repeat_days=repeat_days)
        _store_memory_reminder(chat_id, _row_to_reminder(row))
        reminder_counter[chat_id] = max(reminder_counter.get(chat_id, 0), rid)
        restored += 1
    logger.info(f"🔁 Восстановлено напоминаний: {restored}, пропущенных: {missed}")


async def handle_message(update: Update, context):
    from telegram import InlineKeyboardMarkup
    from handlers.session import processes, register_message
    from keyboards import btn_cancel, show_main_menu
    import re as _re
    from ai import (
        do_search,
        _ask_groq_with_history,
        peek_pending_memo_suggestions,
        pop_pending_memo_suggestions,
    )
    from db import (
        db_clear_memories,
        db_count_memories,
        db_delete_memory_by_id,
        db_get_all_memories,
        db_save_memory,
        db_search_memories,
        db_set_memory_category,
        db_update_memory_by_id,
    )
    from memory_manager import (
        format_memory_rows,
        format_pending_memories,
        parse_memory_category,
        parse_memory_update,
    )

    message = update.message or update.effective_message
    if not message:
        return

    chat_id = update.effective_chat.id

    # ── Проверка доступа ──
    user = update.effective_user
    from utils import is_authorized
    if not is_authorized(user.id):
        if message.text and message.text.startswith("/start"):
            reply = await message.reply_text(_pad("❌ Доступ запрещён. Обратитесь к администратору."))
            register_message(user.id, chat_id, reply.message_id)
            return
        if not message.text or not message.text.startswith("/"):
            reply = await message.reply_text(_pad("❌ Доступ запрещён. Обратитесь к администратору."))
            register_message(user.id, chat_id, reply.message_id)
            return
        # Команды проверяют авторизацию самостоятельно через _check_auth

    # Логирование входящих сообщений (текст скрывается для PIN-процессов)
    has_loc = bool(message.location)
    in_proc = user.id in processes
    _pin_processes = {"setpin", "setpin_first", "enter_pin"}
    _active_proc_type = processes.get(user.id, {}).get("type", "")
    _is_pin_proc = _active_proc_type in _pin_processes
    _log_text = "[PIN hidden]" if _is_pin_proc else (message.text[:30] if message.text else "None")
    location_attr = getattr(message, 'location', None)
    logger.info(f"MSG: user={user.id}, has_location={has_loc}, in_process={in_proc}, text={_log_text}, location_type={type(location_attr).__name__ if location_attr else 'None'}")


    # Проверяем что получил бот
    has_content = message.photo or message.document or message.video or message.audio or message.voice or message.video_note or message.animation or message.sticker
    has_forward = message.forward_origin is not None
    if has_content or has_forward:
        logger.info(f"MSG from {user.id}: photo={bool(message.photo)}, doc={bool(message.document)}, video={bool(message.video)}, audio={bool(message.audio)}, voice={bool(message.voice)}, animation={bool(message.animation)}, sticker={bool(message.sticker)}, forward={has_forward}, proc={user.id in processes}")

    # ── Обработка фото/файлов/локаций ──
    if user.id in processes:
        proc = processes[user.id]
        proc_type = proc["type"]
        state = proc["state"]

        # Сохранение локации при добавлении
        if proc_type == "location" and state.get("step") == "waiting_location":
            logger.info(f"LOC SAVE: user={user.id}, proc_type={proc_type}, step={state.get('step')}, has_location={bool(message.location)}")
            if not message.location:
                reply = await message.reply_text(_pad("❌ Локация не получена. Нажми скрепку → геолокация."), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
                register_message(user.id, chat_id, reply.message_id)
                return
            name = state.get("name")
            lat = message.location.latitude
            lon = message.location.longitude
            logger.info(f"LOC: name={name}, lat={lat}, lon={lon}")

            from db import db_save_location as _save_loc
            try:
                _save_loc(user.id, name, lat, lon)
                logger.info("LOC: saved to DB")
            except Exception as e:
                logger.error(f"LOC: save error: {e}")
                reply = await message.reply_text(_pad("❌ Ошибка сохранения локации."), reply_markup=InlineKeyboardMarkup([[btn_cancel()]]))
                register_message(user.id, chat_id, reply.message_id)
                return
            register_message(user.id, chat_id, message.message_id)
            from handlers.session import finish_process
            await finish_process(context.bot, user.id, show_menu=False)
            await show_main_menu(context.bot, user.id, f"✅ Локация *{md(name)}* сохранена!")
            logger.info("LOC: done")
            return

        # Обновление координат локации
        if proc_type == "location_refresh" and message.location:
            loc_id = state.get("loc_id")
            from db import db_get_locations
            locs = await db_get_locations(user.id)
            loc = next((l for l in locs if l["id"] == loc_id), None)
            if loc:
                from db import db_delete_location as _del_loc, db_save_location as _save_loc
                _del_loc(user.id, loc_id)
                _save_loc(user.id, loc["name"], message.location.latitude, message.location.longitude)
            register_message(user.id, chat_id, message.message_id)
            from handlers.session import finish_process
            from handlers.callbacks.locations import show_locations_menu
            await finish_process(context.bot, user.id, show_menu=False)
            await show_locations_menu(context.bot, user.id, "✅ Координаты обновлены!")
            return

        # Сохранение файла при добавлении
        if proc_type == "document" and state.get("step") == "waiting_file":
            logger.info(f"DOC DEBUG: photo={bool(message.photo)}, doc={bool(message.document)}, forward_origin={message.forward_origin}, media_group={message.media_group_id}")

            # ── Определяем file_id ──
            def _extract_file_id(msg):
                if msg.photo:
                    return msg.photo[-1].file_id, "photo"
                elif msg.document:
                    mime = msg.document.mime_type or ""
                    return msg.document.file_id, "document" if mime.startswith("image/") else "document"
                elif msg.video:
                    return msg.video.file_id, "video"
                elif msg.audio:
                    return msg.audio.file_id, "audio"
                elif msg.voice:
                    return msg.voice.file_id, "voice"
                elif msg.video_note:
                    return msg.video_note.file_id, "video_note"
                elif msg.animation:
                    return msg.animation.file_id, "animation"
                elif msg.sticker:
                    return msg.sticker.file_id, "sticker"
                return None, None

            def _extract_forward(msg):
                if not msg.forward_origin:
                    return None, None, None
                try:
                    origin = msg.forward_origin
                    if hasattr(origin, 'chat') and hasattr(origin, 'message_id'):
                        return origin.chat.id, origin.message_id, None
                except Exception:
                    pass
                return None, None, None

            file_id = None
            file_name = "document"
            file_type = "document"
            source_chat_id = None
            source_message_id = None

            # Прямое фото/файл/видео/аудио/т.д.
            if message.photo or message.document or message.video or message.audio or message.voice or message.video_note or message.animation or message.sticker:
                file_id, ft = _extract_file_id(message)
                file_type = ft or "document"
                if message.photo:
                    file_name = "photo"
                elif message.document:
                    file_name = message.document.file_name or "document"
                elif message.video:
                    file_name = message.video.file_name or "video"
                elif message.audio:
                    file_name = message.audio.file_name or message.audio.title or "audio"
                elif message.voice:
                    file_name = "voice"
                elif message.video_note:
                    file_name = "video_note"
                elif message.animation:
                    file_name = message.animation.file_name or "animation"
                elif message.sticker:
                    file_name = "sticker"
                else:
                    file_name = "file"
                # Для пересланного сохраняем source
                if message.forward_origin:
                    source_chat_id, source_message_id, _ = _extract_forward(message)

            # Пересланное сообщение без прямого медиа
            if not file_id and message.forward_origin:
                try:
                    origin = message.forward_origin
                    if hasattr(origin, 'chat') and hasattr(origin, 'message_id'):
                        orig_msg = await context.bot.get_message(
                            chat_id=origin.chat.id,
                            message_id=origin.message_id
                        )
                        file_id, ft = _extract_file_id(orig_msg)
                        file_type = ft or "document"
                        file_name = "photo" if orig_msg.photo else (orig_msg.document.file_name or "document")
                        source_chat_id = origin.chat.id
                        source_message_id = origin.message_id
                except Exception as e:
                    logger.error(f"Ошибка получения пересланного: {e}")

            if not file_id:
                # Если пришёл текст вместо файла — напоминаем, что нужно отправить файл
                if message.text:
                    name = state.get("name", "Файл")
                    reply = await message.reply_text(
                        _pad(f"📄 Название: *{md(name)}*\n\nОтправь файл, фото или медиа:\n\n_Ты отправил текст, а нужен файл. Нажми 📎 → Файл/Фото/Видео_"),
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
                    )
                else:
                    reply = await message.reply_text(
                        _pad("❌ Не удалось сохранить файл. Отправь фото, видео, аудио, файл или перешли из избранного."),
                        reply_markup=InlineKeyboardMarkup([[btn_cancel()]])
                    )
                register_message(user.id, chat_id, reply.message_id)
                return

            # ── Подготовка ──
            name = state.get("name", "Файл")
            selected_tag_ids = state.get("tag_ids", [])
            tag_names = []
            for tag_id in selected_tag_ids:
                tag = await db_get_document_tag(user.id, tag_id)
                if tag:
                    tag_names.append(tag["name"])

            # ── Медиа-группа (альбом) ──
            if message.media_group_id:
                # Собираем медиа из медиа-группы
                if "pending_photos" not in state:
                    state["pending_photos"] = []
                    state["media_group_id"] = message.media_group_id

                state["pending_photos"].append({
                    "file_id": file_id,
                    "file_type": file_type or "photo",
                })
                logger.info(f"DOC: album media #{len(state['pending_photos'])} added, type={file_type}, media_group={message.media_group_id}")

                register_message(user.id, chat_id, message.message_id)

                # Если это первый элемент — запускаем таймер на сохранение
                if len(state["pending_photos"]) == 1 and "save_task" not in state:
                    from db import db_save_document, db_save_document_photos

                    # Фиксируем все переменные из внешнего scope прямо сейчас,
                    # чтобы избежать race condition если пользователь начнёт
                    # новый процесс до истечения 2 секунд.
                    _saved_user_id = user.id
                    _saved_name = name
                    _saved_source_chat_id = source_chat_id
                    _saved_source_message_id = source_message_id
                    _saved_tag_names = list(tag_names)

                    async def _delayed_save(
                        _uid=_saved_user_id,
                        _name=_saved_name,
                        _src_chat=_saved_source_chat_id,
                        _src_msg=_saved_source_message_id,
                        _tags=_saved_tag_names,
                    ):
                        await asyncio.sleep(2.0)
                        # Берём актуальное состояние процесса
                        current_proc = processes.get(_uid)
                        if not current_proc or current_proc.get("type") != "document":
                            return
                        current_state = current_proc["state"]
                        photos = current_state.get("pending_photos", [])
                        if not photos:
                            return

                        first = photos[0]
                        logger.info(f"DOC: saving album with {len(photos)} items")

                        first_type = first.get("file_type", "photo")
                        album_label = "видео" if first_type == "video" else "медиа"

                        doc_id = await db_save_document(
                            _uid, _name,
                            first["file_id"], "album_",
                            first["file_type"], _src_chat, _src_msg, _tags
                        )
                        await db_save_document_photos(_uid, doc_id, photos)

                        # Завершаем процесс
                        if _uid in processes:
                            del processes[_uid]
                        await show_main_menu(context.bot, _uid, f"✅ Альбом *{md(_name)}* ({len(photos)} {album_label}) сохранён!")

                    task = fire_and_forget(_delayed_save())
                    state["save_task"] = task
                return

            # ── Одиночный файл ──
            from db import db_save_document
            await db_save_document(
                user.id, name, file_id, file_name,
                file_type, source_chat_id, source_message_id, tag_names
            )
            # Если это фото/видео — сохраняем как preview в document_photos
            if file_type in ("photo", "video"):
                docs = await db_get_documents(user.id)
                doc = next((d for d in docs if d["name"] == name and d["user_id"] == user.id), None)
                if doc:
                    from db import db_save_document_photos
                    await db_save_document_photos(user.id, doc["id"], [{"file_id": file_id, "file_type": file_type}])

            register_message(user.id, chat_id, message.message_id)
            from handlers.session import finish_process
            await finish_process(context.bot, user.id, show_menu=False)
            await show_main_menu(context.bot, user.id, f"✅ Файл *{md(name)}* сохранён!")
            return

        # Обновление файла
        if proc_type == "document_refresh" and state.get("step") == "waiting_file":
            file_id = None
            file_name = "file"
            file_type = "document"
            source_chat_id = None
            source_message_id = None
            doc_id = state.get("doc_id")

            if message.photo:
                file_id = message.photo[-1].file_id
                file_name = "photo"
                file_type = "photo"
            elif message.document:
                file_id = message.document.file_id
                file_name = message.document.file_name or "document"
                file_type = "document"
            elif message.video:
                file_id = message.video.file_id
                file_name = message.video.file_name or "video"
                file_type = "video"
            elif message.audio:
                file_id = message.audio.file_id
                file_name = message.audio.file_name or message.audio.title or "audio"
                file_type = "audio"
            elif message.voice:
                file_id = message.voice.file_id
                file_name = "voice"
                file_type = "voice"
            elif message.video_note:
                file_id = message.video_note.file_id
                file_name = "video_note"
                file_type = "video_note"
            elif message.animation:
                file_id = message.animation.file_id
                file_name = message.animation.file_name or "animation"
                file_type = "animation"
            elif message.sticker:
                file_id = message.sticker.file_id
                file_name = "sticker"
                file_type = "sticker"
            elif message.forward_origin:
                origin = message.forward_origin
                if hasattr(origin, 'chat') and hasattr(origin, 'message_id'):
                    source_chat_id = origin.chat.id
                    source_message_id = origin.message_id
                try:
                    orig_msg = await context.bot.get_message(
                        chat_id=source_chat_id,
                        message_id=source_message_id
                    )
                    if orig_msg.photo:
                        file_id = orig_msg.photo[-1].file_id
                        file_name = "photo"
                        file_type = "photo"
                    elif orig_msg.document:
                        file_id = orig_msg.document.file_id
                        file_name = orig_msg.document.file_name or "document"
                        file_type = "document"
                    elif orig_msg.video:
                        file_id = orig_msg.video.file_id
                        file_name = orig_msg.video.file_name or "video"
                        file_type = "video"
                    elif orig_msg.audio:
                        file_id = orig_msg.audio.file_id
                        file_name = orig_msg.audio.file_name or orig_msg.audio.title or "audio"
                        file_type = "audio"
                    elif orig_msg.voice:
                        file_id = orig_msg.voice.file_id
                        file_name = "voice"
                        file_type = "voice"
                    elif orig_msg.video_note:
                        file_id = orig_msg.video_note.file_id
                        file_name = "video_note"
                        file_type = "video_note"
                    elif orig_msg.animation:
                        file_id = orig_msg.animation.file_id
                        file_name = orig_msg.animation.file_name or "animation"
                        file_type = "animation"
                    elif orig_msg.sticker:
                        file_id = orig_msg.sticker.file_id
                        file_name = "sticker"
                        file_type = "sticker"
                except Exception:
                    pass

            if file_id:
                docs = await db_get_documents(user.id)
                doc = next((d for d in docs if d["id"] == doc_id), None)
                if doc:
                    # Очищаем старые фото
                    await db_delete_document_photos(doc_id)
                    await db_save_document(
                        user.id, doc["name"], file_id, file_name,
                        file_type, source_chat_id, source_message_id
                    )
                    # Если это фото/видео — добавляем в document_photos
                    if file_type in ("photo", "video"):
                        await db_save_document_photos(user.id, doc_id, [{"file_id": file_id, "file_type": file_type}])
                    register_message(user.id, chat_id, message.message_id)
                    from handlers.session import finish_process
                    await finish_process(context.bot, user.id, show_menu=False)
                    await asyncio.sleep(0.5)
                    from handlers.callbacks.documents import show_documents_list
                    await show_documents_list(context.bot, user.id, "✅ Файл обновлён!")
                return

    text = message.text.strip() if message.text else ""

    # ── Обработка голосовых сообщений (Whisper через Groq) ──
    if message.voice:
        if not ai.groq_client:
            reply = await message.reply_text(_pad("⚠️ Голосовые сообщения не поддерживаются. Отправь текстом."))
            register_message(user.id, chat_id, reply.message_id)
            return
        for attempt in range(3):
            try:
                from io import BytesIO
                voice_file = await context.bot.get_file(message.voice.file_id)
                audio_bytes = await voice_file.download_as_bytearray()
                audio_file = BytesIO(audio_bytes)
                audio_file.name = "voice.ogg"
                transcript = await asyncio.to_thread(
                    lambda: ai.groq_client.audio.transcriptions.create(
                        model="whisper-large-v3-turbo",
                        file=audio_file,
                        language="ru",
                    )
                )
                text = transcript.text.strip()
                logger.info(f"VOICE: user={user.id}, transcribed={text[:50]}")
                break
            except Exception as e:
                logger.error(f"VOICE transcription error (attempt {attempt+1}): {e}")
                if attempt < 2:
                    await asyncio.sleep(2)
                else:
                    reply = await message.reply_text(_pad("⚠️ Не удалось распознать голосовое сообщение. Попробуй позже."))
                    register_message(user.id, chat_id, reply.message_id)
                    return

    # ── Если есть активный процесс — диспатчим в обработчик ──
    # ДО проверки text, т.к. локации, фото, документы не содержат текста
    if user.id in processes:
        proc = processes[user.id]
        proc_type = proc["type"]
        state = proc["state"]
        _dispatch_text = "[PIN hidden]" if proc_type in _pin_processes else f"({type(text).__name__}){repr(text)[:50]}"
        logger.info(f"DISPATCH: user={user.id}, proc_type={proc_type}, step={state.get('step')}, text={_dispatch_text}")
        from handlers.processors import get_message_handler
        handler = get_message_handler(proc_type)
        if handler:
            logger.info(f"DISPATCH: found handler={handler.__name__} for proc_type={proc_type}")
            await handler(update, context, proc, state)
            return
        else:
            logger.warning(f"DISPATCH: NO handler found for proc_type={proc_type}")

    if not text or text.startswith("/"):
        return

    register_message(user.id, chat_id, message.message_id)

    # ── Нет процесса — диалог с Groq ──
    if user.id not in processes:
        fire_and_forget(_auto_cleanup(context.bot, user.id, chat_id, message.message_id, delay=1))

        # ── Команды памяти ──
        lower = text.lower()

        # Показать всю память (нумерованный список)
        # Ловим любые вариации: что помнишь, что ты помнишь обо мне, что ты знаешь, покажи память и т.д.
        memory_show_phrases = ["что помнишь", "что знаешь", "покажи память", "мои воспоминания", "моя память",
                               "вся память", "все воспоминания", "всю память", "что ты обо мне помнишь",
                               "что ты обо мне знаешь", "расскажи что помнишь"]
        if any(p in lower for p in memory_show_phrases) or lower in ("memory", "memories"):
            memories = await db_get_all_memories(user.id)
            if not memories:
                reply = await message.reply_text(_pad("🧠 *Моя память*\n\nПока ничего не запомнил. Скажи *запомни*, и я сохраню информацию."), parse_mode="Markdown")
                register_message(user.id, chat_id, reply.message_id)
            else:
                text_parts = format_memory_rows(memories)
                if len(text_parts) > 4000:
                    for chunk in [text_parts[i:i+4000] for i in range(0, len(text_parts), 4000)]:
                        reply = await message.reply_text(_pad(chunk), parse_mode="Markdown")
                        register_message(user.id, chat_id, reply.message_id)
                else:
                    reply = await message.reply_text(_pad(text_parts), parse_mode="Markdown")
                    register_message(user.id, chat_id, reply.message_id)
            return

        if lower in {"память подтвердить", "memory confirm"}:
            pending = pop_pending_memo_suggestions(user.id)
            if not pending:
                reply = await message.reply_text(_pad("🧠 Нет ожидающих подтверждения записей памяти."))
                register_message(user.id, chat_id, reply.message_id)
                return
            for mem in pending:
                await db_save_memory(
                    user.id,
                    mem["key"],
                    mem["value"],
                    mem.get("category") or "общее",
                )
            count = await db_count_memories(user.id)
            reply = await message.reply_text(
                _pad(f"✅ Сохранил {len(pending)} записей.\n\n🧠 Всего записей: {count}"),
                parse_mode="Markdown"
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        if lower in {"память отмена", "память отклонить", "memory cancel"}:
            pending = pop_pending_memo_suggestions(user.id)
            text_out = f"🧹 Отклонил {len(pending)} предложений памяти." if pending else "🧠 Нет ожидающих подтверждения записей памяти."
            reply = await message.reply_text(_pad(text_out))
            register_message(user.id, chat_id, reply.message_id)
            return

        if lower.startswith(("память поиск ", "memory search ")):
            query = text.split(maxsplit=2)[2].strip() if len(text.split(maxsplit=2)) >= 3 else ""
            results = await db_search_memories(user.id, query) if query else []
            reply = await message.reply_text(
                _pad(format_memory_rows(results, f"🔎 *Поиск в памяти*: {md(query)}")),
                parse_mode="Markdown"
            )
            register_message(user.id, chat_id, reply.message_id)
            return

        if lower.startswith(("память редактировать ", "memory edit ")):
            parsed = parse_memory_update(text)
            if not parsed:
                reply = await message.reply_text(
                    _pad("❌ Формат: `память редактировать ID ключ = значение`"),
                    parse_mode="Markdown"
                )
                register_message(user.id, chat_id, reply.message_id)
                return
            memory_id, key, value = parsed
            updated = await db_update_memory_by_id(user.id, memory_id, key, value)
            text_out = f"✅ Память `#{memory_id}` обновлена: *{md(key)}* = {md(value)}" if updated else f"❌ Запись `#{memory_id}` не найдена."
            reply = await message.reply_text(_pad(text_out), parse_mode="Markdown")
            register_message(user.id, chat_id, reply.message_id)
            return

        if lower.startswith(("память категория ", "memory category ")):
            parsed = parse_memory_category(text)
            if not parsed:
                reply = await message.reply_text(
                    _pad("❌ Формат: `память категория ID категория`"),
                    parse_mode="Markdown"
                )
                register_message(user.id, chat_id, reply.message_id)
                return
            memory_id, category = parsed
            updated = await db_set_memory_category(user.id, memory_id, category)
            text_out = f"✅ Для памяти `#{memory_id}` установлена категория: *{md(category)}*" if updated else f"❌ Запись `#{memory_id}` не найдена."
            reply = await message.reply_text(_pad(text_out), parse_mode="Markdown")
            register_message(user.id, chat_id, reply.message_id)
            return

        # Удалить по номерам: забудь 1,3,5  или  забудь 1 3 5
        forget_nums = _re.match(r'забудь[\s,;]+([\d,\s;]+)', text, _re.IGNORECASE)
        if forget_nums and text.lower() != "забудь всё":
            memories = await db_get_all_memories(user.id)
            if not memories:
                reply = await message.reply_text(_pad("🧠 Память пуста, нечего забывать."))
                register_message(user.id, chat_id, reply.message_id)
                return
            # Парсим числа из списка
            numbers = set()
            parts = forget_nums.group(1).replace(",", " ").replace(";", " ").split()
            for part in parts:
                part = part.strip()
                if part.isdigit():
                    n = int(part)
                    if 1 <= n <= len(memories):
                        numbers.add(n)
            if not numbers:
                reply = await message.reply_text(_pad("❌ Некорректные номера. Используй: забудь 1,3,5"))
                register_message(user.id, chat_id, reply.message_id)
                return
            deleted = []
            for n in sorted(numbers, reverse=True):
                mem = memories[n - 1]
                await db_delete_memory_by_id(user.id, mem["id"])
                deleted.append(f"{n}. {mem['key']}: {mem['value']}")
            lines = [f"🧹 Забыл {len(deleted)} записей:\n"]
            for d in deleted:
                lines.append(f"— {md(d)}")
            # Показываем что осталось
            remaining = await db_get_all_memories(user.id)
            if remaining:
                lines.append(f"\nОсталось: {len(remaining)} записей")
            else:
                lines.append("\nПамять пуста")
            reply = await message.reply_text(_pad("\n".join(lines)), parse_mode="Markdown")
            register_message(user.id, chat_id, reply.message_id)
            return

        # Очистить память
        forget_exact = {"забудь всё", "забудь все", "очисти память", "очисти всю память", "удали все воспоминания", "удали воспоминания"}
        if lower in forget_exact:
            await db_clear_memories(user.id)
            reply = await message.reply_text(_pad("🧹 Память очищена!"))
            register_message(user.id, chat_id, reply.message_id)
            return

        # Явное запоминание: запомни ключ = значение
        memory_match = _re.match(r'запомни\s+([^=]+?)\s*=\s*(.+)', text, _re.IGNORECASE)
        if memory_match:
            key = memory_match.group(1).strip()
            value = memory_match.group(2).strip()
            category = "общее"
            if "/" in key:
                raw_category, raw_key = key.split("/", 1)
                if raw_category.strip() and raw_key.strip():
                    category = raw_category.strip()
                    key = raw_key.strip()
            await db_save_memory(user.id, key, value, category)
            count = await db_count_memories(user.id)
            reply = await message.reply_text(_pad(f"✅ Запомнил: [{md(category)}] *{md(key)}* = {md(value)}\n\n🧠 Всего записей: {count}"), parse_mode="Markdown")
            register_message(user.id, chat_id, reply.message_id)
            return

        if "найди" in lower:
            await do_search(update, text, user.id, chat_id, context.bot)
            await show_main_menu(context.bot, user.id, "🔍 Что дальше?")
        else:
            answer = await asyncio.to_thread(_ask_groq_with_history, user.id, text)
            try:
                reply = await message.reply_text(_pad(answer), parse_mode="Markdown")
                register_message(user.id, chat_id, reply.message_id)
            except Exception:
                reply = await message.reply_text(_pad(answer))
                register_message(user.id, chat_id, reply.message_id)
            pending = peek_pending_memo_suggestions(user.id)
            if pending:
                reply = await message.reply_text(
                    _pad(format_pending_memories(pending)),
                    parse_mode="Markdown"
                )
                register_message(user.id, chat_id, reply.message_id)
        return


# ─── Auto cleanup helper ───────────────────────────────────────────────────────

async def _auto_cleanup(bot, user_id: int, chat_id: int, message_id: int, delay: int = 5):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


# ─── Entry point ─────────────────────────────────────────────────────────────

BOT_TOKEN  = os.getenv("BOT_TOKEN")
TAVILY_KEY = os.getenv("TAVILY_KEY")
GROQ_KEY = os.getenv("GROQ_KEY")
FALLBACK_KEY = os.getenv("FALLBACK_KEY")
FALLBACK_URL = os.getenv("FALLBACK_URL")
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL")

missing_env = [name for name, value in {
    "BOT_TOKEN": BOT_TOKEN,
    "TAVILY_KEY": TAVILY_KEY,
    "GROQ_KEY": GROQ_KEY,
}.items() if not value]
if missing_env:
    raise RuntimeError(f"Missing required environment variables: {', '.join(missing_env)}")

init_ai(GROQ_KEY, TAVILY_KEY, FALLBACK_KEY, FALLBACK_URL, FALLBACK_MODEL)



if __name__ == "__main__":
    init_db()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(set_commands)
        .connect_timeout(60)
        .read_timeout(60)
        .write_timeout(60)
        .pool_timeout(60)
        .build()
    )

    register_jobs(app, restore_reminders)

    register_handlers(app, handle_message)

    print("🚀 Бот запущен с Process Manager + SQLite + Groq History")
    app.run_polling()
