import asyncio
from datetime import datetime, timedelta
import zoneinfo
import httpx
from config import settings

API = "https://api.notion.com/v1"
NOTION_TIMEOUT = 30
NOTION_RETRY_ATTEMPTS = 3
NOTION_RETRY_DELAY = 1
TITLE_PROPERTY_CANDIDATES = ("Name", "Title", "title")
CREATED_PROPERTY = "Created"
TAGS_PROPERTY = "Tags"
DAY_PROPERTY = "Day"
HEADERS = {
    "Authorization": f"Bearer {settings.notion_token}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 429} or status_code >= 500


async def _request_with_retry(
    http: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    delay = NOTION_RETRY_DELAY
    request = getattr(http, method)
    for attempt in range(1, NOTION_RETRY_ATTEMPTS + 1):
        try:
            resp = await request(url, headers=HEADERS, **kwargs)
        except httpx.RequestError as e:
            if attempt == NOTION_RETRY_ATTEMPTS:
                raise RuntimeError(
                    f"Notion {method.upper()} failed after {attempt} attempts: {e}"
                ) from e
        else:
            if resp.is_success:
                return resp
            if not _is_retryable_status(resp.status_code) or attempt == NOTION_RETRY_ATTEMPTS:
                raise RuntimeError(f"Notion {method.upper()} error {resp.status_code}: {resp.text}")

        await asyncio.sleep(delay)
        delay *= 2

    raise RuntimeError(f"Notion {method.upper()} failed after {NOTION_RETRY_ATTEMPTS} attempts")


MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def _today_date() -> str:
    tz = zoneinfo.ZoneInfo(settings.timezone)
    return datetime.now(tz).date().isoformat()  # e.g. "2026-04-09"


def _today_label() -> str:
    tz = zoneinfo.ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    return f"{now.day} {MONTHS_RU[now.month]}"


def extract_page_title(page: dict) -> str:
    title_prop = _find_page_property(page["properties"], "title", TITLE_PROPERTY_CANDIDATES)
    parts = title_prop.get("title", [])
    return "".join(p["plain_text"] for p in parts)


def _find_page_property(properties: dict, prop_type: str, candidates: tuple[str, ...]) -> dict:
    for name in candidates:
        prop = properties.get(name)
        if prop and prop.get("type") == prop_type:
            return prop
    for prop in properties.values():
        if prop.get("type") == prop_type:
            return prop
    raise RuntimeError(f"Notion page is missing a {prop_type} property")


def _find_database_property(properties: dict, prop_type: str, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        prop = properties.get(name)
        if prop and prop.get("type") == prop_type:
            return name
    for name, prop in properties.items():
        if prop.get("type") == prop_type:
            return name
    available = ", ".join(sorted(properties))
    raise RuntimeError(f"Notion database is missing a {prop_type} property. Available: {available}")


async def _database_properties(http: httpx.AsyncClient) -> dict:
    resp = await _request_with_retry(
        http,
        "get",
        f"{API}/databases/{settings.notion_database_id}",
    )
    return resp.json().get("properties", {})


async def ensure_database_schema(http: httpx.AsyncClient) -> tuple[str, str, str, str]:
    """Ensures the Notion database has the properties this bot writes."""
    properties = await _database_properties(http)
    title_property = _find_database_property(properties, "title", TITLE_PROPERTY_CANDIDATES)

    updates = {}
    created = properties.get(CREATED_PROPERTY)
    if not created:
        updates[CREATED_PROPERTY] = {"date": {}}
    elif created.get("type") != "date":
        raise RuntimeError(f'Notion property "{CREATED_PROPERTY}" must be a date property')

    tags = properties.get(TAGS_PROPERTY)
    if not tags:
        updates[TAGS_PROPERTY] = {"multi_select": {}}
    elif tags.get("type") != "multi_select":
        raise RuntimeError(f'Notion property "{TAGS_PROPERTY}" must be a multi_select property')

    day = properties.get(DAY_PROPERTY)
    if not day:
        updates[DAY_PROPERTY] = {"select": {}}
    elif day.get("type") != "select":
        raise RuntimeError(f'Notion property "{DAY_PROPERTY}" must be a select property')

    if updates:
        await _request_with_retry(
            http,
            "patch",
            f"{API}/databases/{settings.notion_database_id}",
            json={"properties": updates},
        )

    return title_property, CREATED_PROPERTY, TAGS_PROPERTY, DAY_PROPERTY


def _combine_tags(
    existing_page: dict | None,
    new_tags: list[str],
    tags_property: str,
) -> list[dict]:
    """Merges page tags with new ones, always prepends Daily, no duplicates."""
    existing = []
    if existing_page:
        existing = [
            t["name"]
            for t in existing_page["properties"].get(tags_property, {}).get("multi_select", [])
        ]
    all_tags = ["Daily"] + [t for t in (existing + new_tags) if t != "Daily"]
    # deduplicate while preserving order
    seen = set()
    unique = []
    for t in all_tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return [{"name": t} for t in unique]


async def get_today_page() -> dict | None:
    pages = await get_today_pages()
    return pages[0] if pages else None


async def get_today_pages() -> list[dict]:
    async with httpx.AsyncClient(timeout=NOTION_TIMEOUT) as http:
        _, date_property, _, _ = await ensure_database_schema(http)
        resp = await _request_with_retry(
            http,
            "post",
            f"{API}/databases/{settings.notion_database_id}/query",
            json={
                "filter": {
                    "property": date_property,
                    "date": {"equals": _today_date()},
                },
                "sorts": [{"property": date_property, "direction": "ascending"}],
            },
        )
        return resp.json().get("results", [])


async def _verify_page_created(http: httpx.AsyncClient, page_id: str) -> None:
    resp = await _request_with_retry(
        http,
        "get",
        f"{API}/pages/{page_id}",
    )
    page = resp.json()
    if page.get("id") != page_id or page.get("archived"):
        raise RuntimeError(f"Notion saved page verification failed for {page_id}")


async def create_page(entry_title: str, entry_text: str, entry_tags: list[str]) -> str:
    async with httpx.AsyncClient(timeout=NOTION_TIMEOUT) as http:
        title_property, date_property, tags_property, day_property = await ensure_database_schema(http)
        properties = {
            title_property: {"title": [{"text": {"content": entry_title}}]},
            date_property: {"date": {"start": _today_date()}},
            day_property: {"select": {"name": _today_date()}},
            tags_property: {
                "multi_select": _combine_tags(None, entry_tags, tags_property),
            },
        }
        resp = await _request_with_retry(
            http,
            "post",
            f"{API}/pages",
            json={
                "parent": {"database_id": settings.notion_database_id},
                "properties": properties,
                "children": [
                    {
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {"rich_text": [{"text": {"content": entry_title}}]},
                    },
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"text": {"content": entry_text}}]},
                    },
                ],
            },
        )
        page = resp.json()
        page_id = page.get("id")
        if not page_id:
            raise RuntimeError("Notion create page response did not include page id")
        await _verify_page_created(http, page_id)
        return page_id


async def update_page(page: dict, entry_title: str, entry_text: str, entry_tags: list[str]) -> None:
    page_id = page["id"]
    new_title = f"{extract_page_title(page)}, {entry_title}"
    async with httpx.AsyncClient(timeout=NOTION_TIMEOUT) as http:
        title_property, _, tags_property, _ = await ensure_database_schema(http)
        properties = {
            title_property: {"title": [{"text": {"content": new_title}}]},
            tags_property: {
                "multi_select": _combine_tags(page, entry_tags, tags_property),
            },
        }
        await _request_with_retry(
            http,
            "patch",
            f"{API}/pages/{page_id}",
            json={"properties": properties},
        )

        await _request_with_retry(
            http,
            "patch",
            f"{API}/blocks/{page_id}/children",
            json={
                "children": [
                    {"object": "block", "type": "divider", "divider": {}},
                    {
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {"rich_text": [{"text": {"content": entry_title}}]},
                    },
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"text": {"content": entry_text}}]},
                    },
                ]
            },
        )


async def get_week_pages() -> list[dict]:
    """Returns all diary pages created in the last 7 days, oldest first."""
    tz = zoneinfo.ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    week_ago = today - timedelta(days=6)
    async with httpx.AsyncClient(timeout=NOTION_TIMEOUT) as http:
        _, date_property, _, _ = await ensure_database_schema(http)
        resp = await _request_with_retry(
            http,
            "post",
            f"{API}/databases/{settings.notion_database_id}/query",
            json={
                "filter": {
                    "and": [
                        {"property": date_property, "date": {"on_or_after": week_ago.isoformat()}},
                        {"property": date_property, "date": {"on_or_before": today.isoformat()}},
                    ]
                },
                "sorts": [{"property": date_property, "direction": "ascending"}],
            },
        )
        return resp.json().get("results", [])


async def save_entry(entry_title: str, entry_text: str, entry_tags: list[str]) -> str:
    """Creates and verifies a separate Notion database row for every diary entry."""
    return await create_page(entry_title, entry_text, entry_tags)
