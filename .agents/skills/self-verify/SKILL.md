---
name: self-verify
description: Validate manager close-out for diary-bot work. Use when implementation or docs are done and final evidence must be checked. Do not use for planning or implementation.
---

# Self Verify

## Process

1. Confirm scope: branch, touched files, user request, acceptance criteria.
2. Re-walk manager routing from `AGENTS.md` and `.agents/skills/manager/SKILL.md`.
3. Verify required gates ran or were intentionally collapsed.
4. Verify tests and compile checks are fresh for changed code.
5. Verify no production commands ran unless requested.
6. Verify mirrors stayed synced:
   - `AGENTS.md` and `CLAUDE.md`
   - `.agents/` and `.claude/`
   - `.codex/agents/*.toml` and matching agent behavior
7. Report PASS, MISSING, or RERUN.

## Rules

- Do not claim PASS with missing relevant tests.
- Do not claim PASS when changed instructions are not mirrored.
- Do not claim PASS after stale validation.
- Keep output short.

## Output

```text
Self-verify: PASS | MISSING | RERUN
Evidence:
- <check>
Missing:
- <gap or none>
```
