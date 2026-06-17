---
name: code-simplifier
description: Reduce code, config, docs, and prompt overhead in this repo. Use before review for code changes or when asked to simplify, remove duplication, or pressure-test diff size.
---

# Code Simplifier

Order: delete -> merge -> shorten -> rewrite.

## Process

1. State the behavior in one sentence.
2. Find overhead: duplicate paths, speculative fallbacks, repeated defaults, broad helpers, stale docs, prompt duplication.
3. For each piece ask:
   - Can it be deleted?
   - Can two paths become one?
   - Can this move to a boundary?
   - Can this use existing tests or helpers?
4. Keep one source of truth.
5. Preserve behavior and tests.
6. Report what changed and what complexity remains.

## Diary-bot heuristics

- Do not split `bot.py` unless the extracted unit has a stable boundary and tests get simpler.
- Keep external API retries and schema handling inside service modules.
- Keep env defaults in `config.py`, not scattered across services.
- Prefer targeted unit tests over new harnesses.
- Delete docs that restate code unless user-facing setup changes.
