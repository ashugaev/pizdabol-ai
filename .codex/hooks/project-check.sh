#!/usr/bin/env bash
set -euo pipefail

repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$repo_root"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found; skipping Codex project checks"
  exit 0
fi

python3 <<'PY'
from pathlib import Path
import tomllib

for path in sorted(Path(".codex").rglob("*.toml")):
    with path.open("rb") as handle:
        tomllib.load(handle)

for root in (Path(".claude/skills"), Path(".agents/skills")):
    if not root.exists():
        continue
    for skill_path in sorted(root.glob("*/SKILL.md")):
        text = skill_path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise SystemExit(f"{skill_path}: missing YAML frontmatter")
        end = text.find("\n---\n", 4)
        if end == -1:
            raise SystemExit(f"{skill_path}: unclosed YAML frontmatter")
        fields = {}
        for line in text[4:end].splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                raise SystemExit(f"{skill_path}: invalid frontmatter line: {line}")
            key, value = stripped.split(":", 1)
            fields[key.strip()] = value.strip().strip("\"'")
        if fields.get("name") != skill_path.parent.name:
            raise SystemExit(
                f"{skill_path}: name must match folder {skill_path.parent.name}"
            )
        if not fields.get("description"):
            raise SystemExit(f"{skill_path}: description is required")

print("Codex config and skills OK")
PY

if [[ -f bot.py ]]; then
  python3 -m py_compile bot.py config.py services/*.py tests/*.py
fi
