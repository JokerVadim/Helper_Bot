"""AI client module for Groq and Tavily."""
import asyncio
import json
import logging
import re
from collections import defaultdict
from datetime import datetime

import cloudscraper
from groq import Groq
from tavily import TavilyClient

from config import MAX_SEARCH_RESULTS
from utils import _pad

logger = logging.getLogger(__name__)

ai_ready = {"groq": False, "tavily": False, "fallback": False}

groq_client: Groq | None = None
tavily: TavilyClient | None = None
fallback_key: str | None = None
fallback_base_url: str = "https://api.cerebras.ai/v1"
fallback_model: str = "llama3.1-8b"

SYSTEM_PROMPT = (
    "Ты умный и дружелюбный ассистент. "
    "Отвечай на русском языке. "
    "Будь кратким и конкретным. "
    "Если не знаешь ответа — честно скажи об этом.\n\n"
    "У тебя есть **долговременная память** — ты помнишь факты, которые пользователь попросил запомнить.\n"
    "Сохраняй информацию ТОЛЬКО если пользователь явно сказал 'запомни' или 'запомни что'.\n"
    "НЕ сохраняй ничего по своей инициативе! Только когда тебя попросили.\n\n"
    "ВАЖНО: [MEMO: ключ = значение] — это **СКРЫТАЯ СИСТЕМНАЯ КОМАНДА**.\n"
    "Она НЕ должна появляться в тексте, который видит пользователь.\n"
    "Пользователь должен видеть только чистый ответ, без [MEMO:] строк.\n\n"
    "Как это работает:\n"
    "1. Пользователь: 'запомни что молоко стоит 80 сум'\n"
    "2. Твой ответ (то, что видит пользователь): '✅ Запомнил: молоко ≈ 80 сум'\n"
    "3. После ответа добавь строку [MEMO: молоко цена = 80 сум] — но ТОЛЬКО эту скрытую строку, она будет обработана системой и удалена.\n\n"
    "Ты можешь искать в сохранённой памяти, когда это нужно для ответа.\n"
    "Для вычислений используй данные из памяти (например: цены, количества, курсы).\n"
    "Не говори 'я не помню' — используй то, что сохранено, или спроси пользователя.\n\n"
    "🚨 **САМОЕ ВАЖНОЕ ПРАВИЛО**: ПЕРЕД КАЖДЫМ ОТВЕТОМ проверяй текущую дату и время!\n"
    "Текущая дата и время указаны ниже в этом сообщении. Сверяйся с ними ОБЯЗАТЕЛЬНО.\n"
    "Особенно важно: 'сегодня', 'завтра', 'вчера', 'позавчера', 'через неделю', 'через месяц', 'на этой неделе', 'в этом месяце'.\n"
    "Пример: если сегодня 21.05.2026, то 'завтра' это 22.05.2026, 'послезавтра' это 23.05.2026.\n"
    "НЕ используй выдуманные даты. НЕ говори 'я не знаю какое сегодня число'. Дата есть ниже!\n\n"
    "ВАЖНО: Когда ты показываешь пользователю его сохранённую память — используй **нумерованный список**:\n"
    "1. ключ: значение\n"
    "2. ключ: значение\n"
    "3. ключ: значение\n"
    "НЕ используй тире, звёздочки или другие маркеры — ТОЛЬКО номера.\n\n"
    "У тебя есть **инструменты** для работы с данными пользователя. Используй их ВСЕГДА, когда пользователь:\n"
    "— спрашивает про деньги/сумму → get_summa\n"
    "— хочет создать/прочитать/изменить/удалить заметку → get_notes, create_note, update_note, delete_note\n"
    "— хочет работать со списками → get_lists, get_list_items, add_items, check_item, delete_item\n"
    "— хочет создать/посмотреть/удалить напоминание → get_reminders, create_reminder, delete_reminder\n"
    "— хочет поставить таймер → create_timer\n"
    "— спрашивает про дни рождения → get_birthdays, add_birthday, delete_birthday\n"
    "— спрашивает про локации → get_locations, delete_location\n"
    "— спрашивает про файлы → get_documents, get_document_tags\n\n"
    "Не выдумывай данные — ВСЕГДА используй инструменты для получения и изменения информации.\n"
    "Показывай ID элементов в ответах, чтобы пользователь мог их использовать для удаления/изменения.\n"
    "При удалении/изменении можно указать НАЗВАНИЕ вместо ID — инструмент найдёт по имени."
)

MAX_HISTORY = 10
chat_history: dict[int, list[dict]] = defaultdict(list)
pending_memo_suggestions: dict[int, list[dict]] = defaultdict(list)

# Models
CHAT_MODEL = "llama-3.3-70b-versatile"
LIGHT_MODEL = "llama-3.1-8b-instant"


def init_ai(groq_key: str, tavily_key: str, fallback_api_key: str = None, fallback_api_url: str = None, fallback_api_model: str = None):
    global groq_client, tavily, ai_ready, fallback_key, fallback_base_url, fallback_model

    # Проверка Groq
    try:
        groq_client = Groq(api_key=groq_key)
        test = groq_client.chat.completions.create(
            model=LIGHT_MODEL,
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
        )
        ai_ready["groq"] = True
        logger.info("Groq API: OK")
    except Exception as e:
        logger.warning(f"Groq API недоступен: {e}")
        groq_client = None

    # Проверка Tavily
    try:
        tavily = TavilyClient(api_key=tavily_key)
        test = tavily.search(query="test", max_results=1)
        ai_ready["tavily"] = True
        logger.info("Tavily API: OK")
    except Exception as e:
        logger.warning(f"Tavily API недоступен: {e}")
        tavily = None

    # Проверка fallback (Cerebras / SambaNova / GitHub Models etc.)
    if fallback_api_key:
        fallback_key = fallback_api_key
        if fallback_api_url:
            fallback_base_url = fallback_api_url
        if fallback_api_model:
            fallback_model = fallback_api_model
        try:
            import requests as req
            resp = req.post(
                fallback_base_url.rstrip("/") + "/chat/completions",
                headers={
                    "Authorization": f"Bearer {fallback_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": fallback_model,
                    "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 5,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                ai_ready["fallback"] = True
                logger.info(f"Fallback API: OK ({fallback_base_url})")
            else:
                logger.warning(f"Fallback API: HTTP {resp.status_code}")
                fallback_key = None
        except Exception as e:
            logger.warning(f"Fallback API недоступен: {e}")
            fallback_key = None


def history_add(user_id: int, role: str, content: str):
    chat_history[user_id].append({"role": role, "content": content})
    if len(chat_history[user_id]) > MAX_HISTORY:
        chat_history[user_id] = chat_history[user_id][-MAX_HISTORY:]


def history_clear(user_id: int):
    chat_history[user_id] = []
    logger.info(f"[CLEAN] chat_history[{user_id}] cleared")


def _get_memories_text(user_id: int, max_memories: int = 15) -> str:
    """Получить сохранённые воспоминания пользователя (последние 15)."""
    from db import db
    memories = db.get_all_memories(user_id)
    if not memories:
        return ""
    recent = memories[:max_memories]
    lines = []
    for i, mem in enumerate(recent, 1):
        lines.append(f"{i}. {mem['key']}: {mem['value']}")
    if len(memories) > max_memories:
        lines.append(f"... и ещё {len(memories) - max_memories} записей")
    return "\n".join(lines)


def _strip_memo_tags(text: str) -> str:
    """Удаляет строки [MEMO: ...] из текста."""
    cleaned = re.sub(r'\s*\[memo:[^\]]*\]\s*', '\n', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'\s*memo:\s*.+', '\n', cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _extract_memo_tags(text: str) -> list[dict]:
    """Парсит [MEMO: ...] из ответа AI."""
    tags = []
    for key, value in re.findall(r'\[memo:\s*(.+?)\s*=\s*(.+?)\]', text, re.IGNORECASE):
        tags.append({"key": key.strip(), "value": value.strip(), "category": "общее"})
    for key, value in re.findall(r'^\s*memo:\s*(.+?)\s*=\s*(.+?)$', text, re.IGNORECASE | re.MULTILINE):
        tags.append({"key": key.strip(), "value": value.strip().rstrip(']'), "category": "общее"})
    return tags


def _queue_memo_tags(text: str, user_id: int):
    """Сохранить AI-предложение памяти до явного подтверждения пользователя."""
    tags = _extract_memo_tags(text)
    if tags:
        pending_memo_suggestions[user_id] = tags
        logger.info(f"MEMORY PENDING: user={user_id}, count={len(tags)}")


def pop_pending_memo_suggestions(user_id: int) -> list[dict]:
    return pending_memo_suggestions.pop(user_id, [])


def peek_pending_memo_suggestions(user_id: int) -> list[dict]:
    return list(pending_memo_suggestions.get(user_id, []))


def _build_system_content(user_id: int) -> str:
    """Build system prompt with date and memories."""
    memories_text = _get_memories_text(user_id)
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    system = f"🚨 **ТЕКУЩАЯ ДАТА И ВРЕМЯ**: {now_str}\n\n" + SYSTEM_PROMPT
    if memories_text:
        system += f"\n\nВот что ты помнишь об этом пользователе:\n{memories_text}"
    return system


def _ask_groq_with_history(user_id: int, user_text: str) -> str:
    if not user_text:
        return "Пожалуйста, напишите текст сообщения."
    if not groq_client:
        if not ai_ready.get("groq"):
            return "⚠️ Groq API недоступен. Проверьте API ключ в настройках."
        return "AI не инициализирован."
    try:
        from tools import TOOLS, handle_tool_call

        system_content = _build_system_content(user_id)
        messages = [{"role": "system", "content": system_content}]
        messages += chat_history[user_id]
        messages.append({"role": "user", "content": user_text})

        response = groq_client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=800,
            temperature=0.7,
        )

        message = response.choices[0].message

        # ── Обработка tool_calls ──
        if message.tool_calls:
            logger.info(f"TOOL CALL: user={user_id}, calls={[tc.function.name for tc in message.tool_calls]}")

            # Добавляем ответ ассистента с tool_calls в историю
            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]
            })

            # Выполняем все инструменты
            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}
                try:
                    result = handle_tool_call(fn_name, fn_args, user_id)
                except Exception as e:
                    logger.error(f"TOOL ERROR: {fn_name}: {e}")
                    result = f"⚠️ Ошибка при выполнении: {e}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result
                })
                logger.info(f"TOOL EXECUTED: {fn_name}({fn_args}) -> {result[:100]}")

            # Второй запрос к Groq — сформировать ответ на основе результатов
            response2 = groq_client.chat.completions.create(
                model=CHAT_MODEL,
                messages=messages,
                max_tokens=800,
                temperature=0.7,
            )
            answer = response2.choices[0].message.content or ""
            answer = answer.strip()
        else:
            # ── Обычный ответ без tool_calls ──
            answer = message.content.strip() if message.content else ""

        # Сохраняем в память только если пользователь явно попросил
        if "запомни" in user_text.lower():
            _queue_memo_tags(answer, user_id)
        answer = _strip_memo_tags(answer)

        # Обновляем историю
        history_add(user_id, "user", user_text)
        history_add(user_id, "assistant", answer[:500])

        return answer

    except Exception as e:
        logger.error(f"Groq history error: {e}")
        # Бесшовный fallback при любой ошибке Groq
        result = _ask_fallback(user_id, user_text)
        if result:
            return result
        # Попробовать распарсить function call из failed_generation
        try:
            failed = getattr(e, 'body', None)
            if isinstance(failed, str):
                try:
                    failed = json.loads(failed)
                except Exception:
                    failed = {}
            elif not isinstance(failed, dict):
                failed = {}
            if isinstance(failed, dict):
                gen = failed.get('error', {}).get('failed_generation', '')
            else:
                gen = str(e)
                m = re.search(r"'failed_generation': '(.*?)'}", gen)
                gen = m.group(1) if m else ''
            fn_match = re.match(r'<function=(\w+)[,>](.+?)</?function>', gen, re.DOTALL)
            if fn_match:
                fn_name = fn_match.group(1)
                try:
                    fn_args = json.loads(fn_match.group(2))
                except Exception:
                    fn_args = {}
                from tools import handle_tool_call
                result = handle_tool_call(fn_name, fn_args, user_id)
                logger.info(f"TOOL FALLBACK: {fn_name}({fn_args}) -> {result[:100]}")
                # Второй запрос без tools — сформировать ответ
                system_content = _build_system_content(user_id)
                messages2 = [{"role": "system", "content": system_content}]
                messages2 += chat_history[user_id]
                messages2.append({"role": "user", "content": user_text})
                messages2.append({"role": "assistant", "content": f"Выполнил: {result}"})
                response2 = groq_client.chat.completions.create(
                    model=CHAT_MODEL,
                    messages=messages2,
                    max_tokens=800,
                    temperature=0.7,
                )
                answer = (response2.choices[0].message.content or "").strip()
                if "запомни" in user_text.lower():
                    _queue_memo_tags(answer, user_id)
                answer = _strip_memo_tags(answer)
                history_add(user_id, "user", user_text)
                history_add(user_id, "assistant", answer[:500])
                return answer
        except Exception as e2:
            logger.error(f"TOOL FALLBACK error: {e2}")
        return "⚠️ Ошибка Groq. Попробуй позже или проверь API ключ."


def _ask_fallback(user_id: int, user_text: str) -> str:
    """Fallback через OpenAI-совместимый API (Cerebras, SambaNova, GitHub Models и т.д.)."""
    if not user_text:
        return "Пожалуйста, напишите текст сообщения."
    if not fallback_key or not ai_ready.get("fallback"):
        return None
    try:
        import requests as req
        system_content = _build_system_content(user_id)
        messages = [{"role": "system", "content": system_content}]
        messages += chat_history[user_id]
        messages.append({"role": "user", "content": user_text})

        resp = req.post(
            fallback_base_url.rstrip("/") + "/chat/completions",
            headers={
                "Authorization": f"Bearer {fallback_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": fallback_model,
                "messages": messages,
                "max_tokens": 800,
                "temperature": 0.7,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"Fallback HTTP {resp.status_code}: {resp.text[:200]}")
            return None

        data = resp.json()
        answer = data["choices"][0]["message"]["content"].strip()
        if "запомни" in user_text.lower():
            _queue_memo_tags(answer, user_id)
        answer = _strip_memo_tags(answer)
        history_add(user_id, "user", user_text)
        history_add(user_id, "assistant", answer[:500])
        logger.info(f"FALLBACK used for user={user_id}")
        return answer
    except Exception as e:
        logger.error(f"Fallback error: {e}")
        return None


def _build_search_query(user_text: str) -> str:
    if not groq_client:
        return re.sub(r'найди\s*', '', user_text, flags=re.IGNORECASE).strip()
    try:
        response = groq_client.chat.completions.create(
            model=LIGHT_MODEL,
            messages=[
                {"role": "system", "content":
                    "Из сообщения пользователя сформулируй короткий поисковый запрос (3-7 слов) для поисковика. "
                    "Верни ТОЛЬКО запрос, без пояснений и кавычек."},
                {"role": "user", "content": user_text}
            ],
            max_tokens=50,
            temperature=0.1,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Query build error: {e}")
        return re.sub(r'найди\s*', '', user_text, flags=re.IGNORECASE).strip()


def _ask_groq_with_search(user_id: int, user_text: str, context_text: str) -> str:
    if not user_text:
        return "Пожалуйста, напишите текст сообщения."
    if not groq_client:
        if not ai_ready.get("groq"):
            return "⚠️ Groq API недоступен. Проверьте API ключ в настройках."
        return "AI не инициализирован."
    try:
        system_content = _build_system_content(user_id)
        messages = [{"role": "system", "content": system_content}]
        messages += chat_history[user_id]
        messages.append({
            "role": "user",
            "content": (
                f"Запрос: {user_text}\n\n"
                f"Результаты поиска:\n{context_text}\n\n"
                "Ответь на запрос на основе найденной информации."
            )
        })
        response = groq_client.chat.completions.create(
            model=CHAT_MODEL,
            messages=messages,
            max_tokens=800,
            temperature=0.2,
        )
        answer = response.choices[0].message.content.strip()
        if "запомни" in user_text.lower():
            _queue_memo_tags(answer, user_id)
        answer = _strip_memo_tags(answer)
        return answer
    except Exception as e:
        logger.error(f"Groq search error: {e}")
        return "⚠️ Ошибка Groq при поиске. Попробуй позже."


def _tavily_search(query: str, max_results: int | None = None) -> list[dict]:
    if not tavily:
        if not ai_ready.get("tavily"):
            logger.warning("Tavily API недоступен")
        return []
    try:
        response = tavily.search(
            query=query,
            max_results=max_results or MAX_SEARCH_RESULTS,
            search_depth="advanced",
            include_raw_content=False
        )
        return [{
            "title": r.get("title", ""),
            "body":  (r.get("content") or "")[:1200],
            "href":  r.get("url", ""),
        } for r in response.get("results", [])]
    except Exception as e:
        logger.error(f"Tavily error: {e}")
        return []


def _suggest_emoji(item: str) -> str:
    """Запросить у Groq эмодзи для элемента."""
    if not groq_client:
        return "📌"
    try:
        response = groq_client.chat.completions.create(
            model=LIGHT_MODEL,
            messages=[
                {"role": "system", "content":
                    "Ты бот, который подбирает эмодзи для элементов списка покупок или дел. "
                    "Верни ТОЛЬКО один эмодзи, без пояснений. "
                    "Примеры: хлеб → 🍞, кроссовки → 👟, телефон → 📱, лекарство → 💊"},
                {"role": "user", "content": f"Подбери эмодзи для: {item}"}
            ],
            max_tokens=10,
            temperature=0.1,
        )
        emoji = response.choices[0].message.content.strip()
        emoji_match = re.search(r'[\U0001F300-\U0001FFFF]', emoji)
        if emoji_match:
            return emoji_match.group()
        return "📌"
    except Exception as e:
        logger.error(f"emoji suggestion error: {e}")
        return "📌"


def _fetch_rub_direct(summa: float | None = None) -> str:
    try:
        scraper = cloudscraper.create_scraper()
        html = scraper.get(
            "https://www.kapitalbank.uz/ru/services/exchange-rates/",
            timeout=15
        ).text

        pre_match = re.search(r'<pre>(.*?)</pre>', html, re.DOTALL)
        if not pre_match:
            return _pad("⚠️ RUB не найден (страница изменилась)")

        pre_content = pre_match.group(1)

        rub_block = re.search(
            r"\[code\]\s*=>\s*RUB\s*\[course_buy\]\s*=>\s*(\d+)\s*\[course_sell\]\s*=>\s*(\d+)",
            pre_content, re.DOTALL
        )

        if not rub_block:
            return _pad("⚠️ RUB не найден (страница изменилась)")

        buy  = rub_block.group(1)
        sell = rub_block.group(2)

        result = (
            f"💱 *Курс рубля (Kapitalbank)*\n\n"
            f"📉 Покупка: *{buy}* сум\n"
            f"📈 Продажа: *{sell}* сум"
        )

        if summa is not None:
            sell_int = int(sell)
            if sell_int > 0:
                converted = (int(summa) // sell_int // 1000) * 1000
                converted_str = f"{converted:,}".replace(",", " ")
                result += f"\n💰 Доступно: *{converted_str}* руб"

        return _pad(result)

    except Exception as e:
        return _pad(f"⚠️ Ошибка: {e}")


def _fetch_usd_requests(summa: float | None = None) -> str | None:
    """Получить курс доллара через API Agrobank (быстро, без Selenium)."""
    import requests
    try:
        url = "https://agrobank.uz/api/v1/?action=pages&code=uz%2Fperson%2Fexchange_rates"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        }
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()

        # Ищем USD в sections[x].blocks[y].content.items где alpha3 == "USD"
        # Берём первый блок с типом currency-rates (обменник в отделении)
        buy = None
        sell = None
        for section in data.get("data", {}).get("sections", []):
            for block in section.get("blocks", []):
                if block.get("type") == "currency-rates":
                    for item in block.get("content", {}).get("items", []):
                        if item.get("alpha3") == "USD":
                            buy = item.get("buy")
                            sell = item.get("sale")
                            break
                    if buy is not None:
                        break

        if buy is None or sell is None:
            logger.warning("USD API: курс не найден в JSON")
            return None

        result = (
            f"💲 *Курс доллара (Agrobank)*\n\n"
            f"📉 Покупка: *{int(buy):,}* сум".replace(",", " ") + "\n"
            f"📈 Продажа: *{int(sell):,}* сум".replace(",", " ")
        )

        if summa is not None and sell > 0:
            converted = int(summa) // int(sell)
            converted_str = f"{converted:,}".replace(",", " ")
            result += f"\n💰 Доступно: *{converted_str}* USD"

        logger.info("USD API: успешно")
        return _pad(result)

    except Exception as e:
        logger.warning(f"USD API не сработал: {e}")
        return None


def _fetch_usd_direct(summa: float | None = None) -> str:
    """Получить курс доллара с Agrobank.uz через JSON API."""
    result = _fetch_usd_requests(summa)
    if result is not None:
        return result
    return _pad("⚠️ Курс доллара временно недоступен.")


async def do_search(update, user_text: str, user_id: int, chat_id: int, bot):
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    message = update.message or update.effective_message

    ok_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("OK", callback_data="search_ok")
    ]])

    try:
        search_query = await asyncio.to_thread(_build_search_query, user_text)
        logger.info(f"Search query: {search_query}")

        msg = await message.reply_text(_pad("🔍 Ищу информацию..."), reply_markup=ok_markup)

        results = await asyncio.wait_for(
            asyncio.to_thread(_tavily_search, search_query, 8),
            timeout=45.0
        )

        if not results:
            answer = await asyncio.to_thread(_ask_groq_with_history, user_id, user_text)
            await msg.edit_text(_pad(f"🤖 {answer}"), parse_mode="Markdown", disable_web_page_preview=True, reply_markup=ok_markup)
            return

        context_text = "\n\n".join(
            f"Источник: {r['href']}\nЗаголовок: {r['title']}\n{r['body']}"
            for r in results[:5]
        )

        answer = await asyncio.wait_for(
            asyncio.to_thread(_ask_groq_with_search, user_id, user_text, context_text),
            timeout=30.0
        )

        history_add(user_id, "user", user_text)
        history_add(user_id, "assistant", answer[:500])

        await msg.edit_text(_pad(f"🤖 {answer}"), parse_mode="Markdown", disable_web_page_preview=True, reply_markup=ok_markup)

    except asyncio.TimeoutError:
        try:
            await msg.edit_text(_pad("⏰ Поиск занял слишком много времени."), reply_markup=ok_markup)
        except Exception:
            await message.reply_text(_pad("⏰ Поиск занял слишком много времени."))
    except Exception as e:
        logger.error(f"Search error: {e}")
        await message.reply_text(_pad("⚠️ Ошибка при поиске."))
