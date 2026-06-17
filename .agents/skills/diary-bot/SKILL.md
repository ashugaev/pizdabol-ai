---
name: diary-bot
description: Work on this Telegram-to-Notion diary bot. Use when tasks touch bot behavior, Telegram UX, OpenAI transcription/formatting/summaries, Notion schema or writes, state storage, env config, tests, CI, or deployment. Do not use for unrelated repository metadata-only edits.
---

# Diary Bot

Use this as project memory for implementation and validation.

## Ownership map

| Area | Files |
|---|---|
| Telegram update flow, drafts, callbacks, scheduling | `bot.py` |
| Environment parsing and defaults | `config.py`, `.env.example` |
| OpenAI formatting | `services/formatter.py`, `tests/test_openai_services.py` |
| OpenAI transcription | `services/whisper.py`, `tests/test_openai_services.py` |
| OpenAI daily and weekly summaries | `services/summary.py`, `tests/test_openai_services.py` |
| Notion schema, retries, duplicate checks, writes | `services/notion.py`, `tests/test_notion.py` |
| Local message and draft state | `services/state_store.py`, `tests/test_state_store.py` |
| Dev, test, deploy commands | `Makefile`, `README.md`, `.github/workflows/ci.yml` |

## Behavior invariants

- Preview original transcription or typed text by default.
- Formatter-generated title and tags apply before save; formatted body applies only after the Format button.
- `Daily` tag is always present in rendered and saved entries.
- Date picker allows today plus previous 6 days.
- Duplicate voice notes use Telegram voice facts; duplicate text notes use exact source-text hash.
- Notion save retries transient errors and verifies created page before marking saved.
- Long transcriptions use metadata-only formatting and keep original text.

## External boundaries

- Tests stay offline. Patch OpenAI clients, Notion HTTP clients, Telegram update/context objects, sleeps, and state paths.
- Never require real `.env` values in tests; set test env before importing modules that read settings.
- Never mutate `.data/message_state.json` in tests.
- Do not run `make dev`, `make deploy`, `make stop-dev`, `ssh`, or systemd commands unless user explicitly asks.

## Validation

Use the narrowest targeted test first, then full local validation for code changes:

```bash
python -m py_compile bot.py config.py services/*.py tests/*.py
python -m unittest discover -s tests -v
make test
```

## Change checklist

- Env var changed: update `config.py`, `.env.example`, README config table, tests.
- Notion property changed: update constants, schema ensure logic, tests, README database table.
- Telegram flow changed: update `bot.py` tests for callbacks, preview text, prompt state, and cancel/save retry behavior.
- OpenAI prompt/model changed: update OpenAI service tests and fallback behavior.
- State shape changed: keep backward load defaults or explicit migration; test old/minimal state.
- Deployment changed: route through `operator`; validate without touching production unless requested.
