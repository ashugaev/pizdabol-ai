import json
import httpx
import openai
from config import settings
from services.notion import API, HEADERS, NOTION_TIMEOUT, extract_page_title, get_today_page, get_week_pages

openai_client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

SUMMARY_PROMPT = """You are helping the user reflect on their day.
Below are the diary entries they recorded throughout the day.
Write a concise, warm daily summary in Russian (2-4 sentences):
highlight the key events, mood, and any notable thoughts.
Do not use bullet points — write as a short paragraph."""


async def _fetch_page_text(page_id: str) -> str:
    """Fetches all text blocks from a Notion page and returns them as plain text."""
    async with httpx.AsyncClient(timeout=NOTION_TIMEOUT) as http:
        resp = await http.get(
            f"{API}/blocks/{page_id}/children",
            headers=HEADERS,
        )
        resp.raise_for_status()
        blocks = resp.json().get("results", [])

    lines = []
    for block in blocks:
        block_type = block.get("type")
        rich_text = block.get(block_type, {}).get("rich_text", [])
        text = "".join(t["plain_text"] for t in rich_text)
        if text:
            lines.append(text)

    return "\n\n".join(lines)


WEEKLY_PROMPT = """You are helping the user reflect on their week.
Below are all diary entries from the past 7 days.
Entries marked with ⭐ were highlighted by the user as personally significant.

Write a weekly highlight report in Russian:
1. A warm narrative paragraph (3-5 sentences) capturing the spirit of the week.
2. A list of 5-7 highlights — include all ⭐-marked entries first, then add any others you find significant. Format each as a short bullet point.

Do not use headers. Write naturally and warmly, as if summarizing a meaningful week to a friend."""


async def generate_weekly_report() -> str | None:
    """Generates a GPT weekly highlight report. Returns None if no pages found."""
    pages = await get_week_pages()
    if not pages:
        return None

    sections = []
    for page in pages:
        page_title = extract_page_title(page)
        page_text = await _fetch_page_text(page["id"])
        if page_text.strip():
            sections.append(f"### {page_title}\n{page_text}")

    if not sections:
        return None

    full_text = "\n\n".join(sections)
    response = await openai_client.chat.completions.create(
        model=settings.openai_summary_model,
        max_completion_tokens=1024,
        messages=[
            {"role": "system", "content": WEEKLY_PROMPT},
            {"role": "user", "content": full_text},
        ],
    )
    return response.choices[0].message.content


async def generate_daily_summary() -> str | None:
    """Generates a GPT summary of today's diary page. Returns None if no page exists."""
    page = await get_today_page()
    if not page:
        return None

    page_text = await _fetch_page_text(page["id"])
    if not page_text.strip():
        return None

    response = await openai_client.chat.completions.create(
        model=settings.openai_summary_model,
        max_completion_tokens=512,
        messages=[
            {"role": "system", "content": SUMMARY_PROMPT},
            {"role": "user", "content": page_text},
        ],
    )
    return response.choices[0].message.content
