"""AI client module for Groq and Tavily."""
import logging
import re
from collections import defaultdict

import cloudscraper
from groq import Groq
from tavily import TavilyClient

from config import MAX_SEARCH_RESULTS

logger = logging.getLogger(__name__)

groq_client: Groq | None = None
tavily: TavilyClient | None = None

GROQ_SYSTEM = (
    "Ты умный и дружелюбный ассистент. "
    "Отвечай на русском языке. "
    "Будь кратким и конкретным. "
    "Если не знаешь ответа — честно скажи об этом."
)

MAX_HISTORY = 10
chat_history: dict[int, list[dict]] = defaultdict(list)


def init_ai(groq_key: str, tavily_key: str):
    global groq_client, tavily
    groq_client = Groq(api_key=groq_key)
    tavily = TavilyClient(api_key=tavily_key)


def history_add(user_id: int, role: str, content: str):
    chat_history[user_id].append({"role": role, "content": content})
    if len(chat_history[user_id]) > MAX_HISTORY:
        chat_history[user_id] = chat_history[user_id][-MAX_HISTORY:]


def history_clear(user_id: int):
    chat_history[user_id] = []


def _ask_groq_with_history(user_id: int, user_text: str) -> str:
    if not groq_client:
        return "AI не инициализирован."
    try:
        messages = [{"role": "system", "content": GROQ_SYSTEM}]
        messages += chat_history[user_id]
        messages.append({"role": "user", "content": user_text})
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=800,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Groq history error: {e}")
        return "Не удалось получить ответ."


def _build_search_query(user_text: str) -> str:
    if not groq_client:
        return re.sub(r'найди\s*', '', user_text, flags=re.IGNORECASE).strip()
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
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
    if not groq_client:
        return "AI не инициализирован."
    try:
        messages = [{"role": "system", "content": GROQ_SYSTEM}]
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
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=800,
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Groq search error: {e}")
        return "Не удалось получить ответ."




def _tavily_search(query: str, max_results: int | None = None) -> list[dict]:
    if not tavily:
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
            "body":  r.get("content", "")[:1200],
            "href":  r.get("url", ""),
        } for r in response.get("results", [])]
    except Exception as e:
        logger.error(f"Tavily error: {e}")
        return []


def _fetch_rub_direct(summa: float | None = None) -> str:
    try:
        scraper = cloudscraper.create_scraper()
        html = scraper.get(
            "https://www.kapitalbank.uz/ru/services/exchange-rates/",
            timeout=15
        ).text

        rub_block = re.search(
            r"\[code\]\s*=>\s*RUB.*?\[course_buy\]\s*=>\s*(\d+).*?\[course_sell\]\s*=>\s*(\d+).*?\[scale\]\s*=>\s*(\d+)",
            html, re.DOTALL
        )

        if not rub_block:
            return "⚠️ RUB не найден (страница изменилась)"

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

        return result

    except Exception as e:
        return f"⚠️ Ошибка: {e}"


async def do_search(update, user_text: str, user_id: int, chat_id: int, bot):
    from telegram import Update as TgUpdate
    message = update.message or update.effective_message
    msg = await message.reply_text("🔍 Формирую запрос...")

    try:
        search_query = await asyncio.to_thread(_build_search_query, user_text)
        logger.info(f"Search query: {search_query}")

        await msg.edit_text("🔍 Ищу информацию...")

        results = await asyncio.wait_for(
            asyncio.to_thread(_tavily_search, search_query, 8),
            timeout=45.0
        )

        if not results:
            await msg.edit_text("🤖 Анализирую...")
            answer = await asyncio.to_thread(_ask_groq_with_history, user_id, user_text)
            history_add(user_id, "user", user_text)
            history_add(user_id, "assistant", answer)
            try:
                await msg.edit_text(f"🤖 {answer}", parse_mode="Markdown", disable_web_page_preview=True)
            except Exception:
                await msg.edit_text(f"🤖 {answer}", disable_web_page_preview=True)
            return

        await msg.edit_text("🤖 Анализирую...")

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

        try:
            await msg.edit_text(f"🤖 {answer}", parse_mode="Markdown", disable_web_page_preview=True)
        except Exception:
            await msg.edit_text(f"🤖 {answer}", disable_web_page_preview=True)

    except asyncio.TimeoutError:
        await msg.edit_text("⏰ Поиск занял слишком много времени.")
    except Exception as e:
        logger.error(f"Search error: {e}")
        await msg.edit_text("⚠️ Ошибка при поиске.")
