import json
import openai
from config import settings

client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """Ты помогаешь вести личный дневник.
Тебе дают сырую транскрипцию голосового сообщения.
Твоя задача — вернуть JSON с тремя полями:
- "title": короткий заголовок записи (3-5 слов, на русском, без кавычек)
- "text": аккуратно отформатированный текст записи (исправь ошибки транскрипции, убери слова-паразиты, сохрани смысл и тон)
- "tags": массив тегов, которые пользователь явно упомянул в сообщении (пустой массив если не упомянул)

Не добавляй факты, имена, должности, события или выводы, которых нет в транскрипции.
Если транскрипция короткая, обрывочная или выглядит неуверенно, сохрани ее как короткую заметку,
не превращай ее в подробную дневниковую запись.

Отвечай ТОЛЬКО валидным JSON, без markdown-блоков и пояснений."""


async def format_entry(transcription: str) -> tuple[str, str, list[str]]:
    response = await client.chat.completions.create(
        model=settings.openai_formatter_model,
        max_completion_tokens=1024,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcription},
        ],
    )
    data = json.loads(response.choices[0].message.content)
    return data["title"], data["text"], data.get("tags", [])
