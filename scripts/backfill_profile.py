"""Seed the durable author profile from all historical Notion diary entries.

Pure orchestration over service functions — no direct HTTP. Run with:

    python -m scripts.backfill_profile [--dry-run] [--reset] [--batch-size N] [--max-chars N]

Reads every diary page (oldest first), batches their text, and feeds each batch
through the same profile extraction the bot uses per message, accumulating durable
facts. Persists incrementally after each batch for crash safety unless --dry-run.
"""

import argparse
import asyncio
import logging
from collections.abc import Iterator

from services import notion, roast
from services.state_store import state_store

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 5
DEFAULT_MAX_CHARS = 6000
ENTRY_SEPARATOR = "\n\n---\n\n"


def _batch(
    entries: list[str],
    batch_size: int,
    max_chars: int,
) -> Iterator[str]:
    """Yields entries joined into batches, capped by count and combined chars."""
    current: list[str] = []
    current_chars = 0
    for entry in entries:
        entry_len = len(entry)
        would_exceed_chars = current and current_chars + entry_len > max_chars
        would_exceed_count = len(current) >= batch_size
        if current and (would_exceed_chars or would_exceed_count):
            yield ENTRY_SEPARATOR.join(current)
            current = []
            current_chars = 0
        current.append(entry)
        current_chars += entry_len
    if current:
        yield ENTRY_SEPARATOR.join(current)


async def _collect_entries() -> list[str]:
    pages = await notion.get_diary_pages()
    entries: list[str] = []
    for page in pages:
        title = notion.extract_page_title(page)
        body = await notion.get_page_text(page["id"])
        text = "\n".join(part for part in (title, body) if part).strip()
        if text:
            entries.append(text)
    return entries


async def backfill(
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_chars: int = DEFAULT_MAX_CHARS,
    reset: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """Rebuilds the author profile from all historical diary entries."""
    entries = await _collect_entries()
    logger.info("Collected %d non-empty diary entries", len(entries))

    points: list[str] = [] if reset else state_store.get_profile_points()
    batches = list(_batch(entries, batch_size, max_chars))
    logger.info("Processing %d batches (batch_size=%d, max_chars=%d)", len(batches), batch_size, max_chars)

    for index, batch_text in enumerate(batches, start=1):
        points = await roast.extract_profile_points(batch_text, points)
        logger.info("Batch %d/%d -> %d points", index, len(batches), len(points))
        if not dry_run:
            state_store.set_profile_points(points)

    return points


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill the author profile from Notion history.")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--reset", action="store_true", help="Start from an empty profile.")
    parser.add_argument("--dry-run", action="store_true", help="Do not persist points.")
    return parser.parse_args(argv)


async def _main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args(argv)
    points = await backfill(
        batch_size=args.batch_size,
        max_chars=args.max_chars,
        reset=args.reset,
        dry_run=args.dry_run,
    )
    print("Final profile points:")
    for point in points:
        print(f"- {point}")


if __name__ == "__main__":
    asyncio.run(_main())
