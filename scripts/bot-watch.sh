#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1

bot_pid=""

load_env() {
  if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
  fi
}

check_env() {
  missing=0
  for key in TELEGRAM_TOKEN OPENAI_API_KEY NOTION_TOKEN NOTION_DATABASE_ID ALLOWED_USER_ID; do
    eval "value=\${$key:-}"
    if [ -z "$value" ]; then
      echo "Missing required $key in .env"
      missing=1
    fi
  done
  return "$missing"
}

requirements_hash() {
  sha256sum requirements.txt 2>/dev/null | awk '{print $1}'
}

ensure_venv() {
  if [ ! -d .venv ]; then
    python3 -m venv .venv || return 1
  fi

  current_hash="$(requirements_hash)"
  installed_hash=""
  if [ -f .venv/.requirements.sha256 ]; then
    installed_hash="$(cat .venv/.requirements.sha256)"
  fi

  if [ "$current_hash" != "$installed_hash" ]; then
    .venv/bin/python -m pip install -r requirements.txt || return 1
    printf '%s\n' "$current_hash" > .venv/.requirements.sha256
  fi
}

fingerprint() {
  {
    find bot.py config.py services -type f -name '*.py' -printf '%T@ %p\n' 2>/dev/null
    find . -maxdepth 1 -type f \( -name '.env' -o -name 'requirements.txt' \) -printf '%T@ %p\n' 2>/dev/null
  } | sort | sha256sum | awk '{print $1}'
}

start_bot() {
  load_env
  check_env || return 1
  ensure_venv || return 1
  PYTHONUNBUFFERED=1 .venv/bin/python bot.py &
  bot_pid="$!"
  echo "bot-watch: started bot.py pid=$bot_pid"
}

stop_bot() {
  if [ -n "${bot_pid:-}" ] && kill -0 "$bot_pid" 2>/dev/null; then
    echo "bot-watch: stopping bot.py pid=$bot_pid"
    kill "$bot_pid" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
      kill -0 "$bot_pid" 2>/dev/null || break
      sleep 1
    done
    kill -9 "$bot_pid" 2>/dev/null || true
    wait "$bot_pid" 2>/dev/null || true
  fi
  bot_pid=""
}

shutdown() {
  stop_bot
  exit 0
}

trap shutdown INT TERM

last_fingerprint="$(fingerprint)"
start_bot || exit 1

while true; do
  sleep 1

  if [ -n "${bot_pid:-}" ] && ! kill -0 "$bot_pid" 2>/dev/null; then
    wait "$bot_pid" 2>/dev/null
    exit_code="$?"
    echo "bot-watch: bot.py exited with code $exit_code; restarting"
    last_fingerprint="$(fingerprint)"
    start_bot || exit 1
    continue
  fi

  next_fingerprint="$(fingerprint)"
  if [ "$next_fingerprint" != "$last_fingerprint" ]; then
    echo "bot-watch: change detected; restarting bot.py"
    stop_bot
    last_fingerprint="$next_fingerprint"
    start_bot || exit 1
  fi
done
