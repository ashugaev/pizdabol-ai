import json
import openai
from config import settings

client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = """Верни JSON для дневниковой заметки:
- "title": короткий заголовок 3-5 слов, без кавычек
- "text": исходный текст с минимальной правкой
- "tags": только явно названные пользователем теги, иначе []

Правила для "text":
- не переписывай стиль, формулировки и порядок мыслей
- не заменяй слова синонимами и не улучшай смысл
- исправляй только очевидный мусор распознавания, повторы, пунктуацию и грубые ошибки
- не добавляй факты, выводы, имена и детали
- если фраза короткая или обрывочная, оставь ее короткой

Только валидный JSON, без markdown и пояснений."""


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
