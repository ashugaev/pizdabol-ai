---
name: skill-writer
description: "Write and review agent content: skills, agent definitions, prompts, workflow docs, AGENTS.md, CLAUDE.md, and .codex agent config. Use for token economy, precision, and mirrored instruction changes."
---

# Skill Writer

Treat agent prose as code.

## Principles

- Delete filler. Keep only constraints that change agent behavior.
- Put trigger details in frontmatter `description`.
- Use one term per concept.
- Prefer commands, file paths, and templates over abstract prose.
- Keep repo-specific details in `diary-bot` skill unless they are global routing rules.
- No bold markdown in agent/rule files.

## Skill shape

```text
skill-name/
  SKILL.md
```

Frontmatter:

```yaml
---
name: kebab-case-name
description: <capability>. Use when <trigger>. Do not use for <negative trigger>.
---
```

## Agent shape

```yaml
---
name: agent-name
description: <what it does>. Use when <trigger>.
model: inherit | opus | sonnet
tools: Read, Grep, Glob, Bash
---
```

Body order: role sentence, Process, Rules, Output.

## Caveman gate

When manager routes prose changes here:

1. Read changed prose surfaces only.
2. Check mirrored files.
3. Remove duplication, hedging, and generic AI instructions.
4. Return `APPROVED` or `CHANGES_REQUESTED`.

## Rejection rules

- Reject unsynced `AGENTS.md` and `CLAUDE.md`.
- Reject unsynced `.agents/` and `.claude/`.
- Reject instructions that require live production commands by default.
- Reject prompt prose that duplicates `diary-bot` project memory.
