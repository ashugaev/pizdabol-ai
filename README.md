# Pizdabol

A Telegram bot that turns your voice (or text) messages into structured diary entries in Notion — with optional AI cleanup, daily and weekly summaries, and a blunt-but-caring "roast" mode. Built for the [Notion Journal](https://www.notion.com/help/guides/journal).

## Quick start

```bash
git clone https://github.com/ashugaev/pizdabol-ai.git
cd pizdabol-ai
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your tokens
python bot.py
```

You'll need a Telegram bot token, an OpenAI API key, and a Notion integration + database — see **[Configuration](docs/configuration.md)**.

## What you can do

- **Send a voice or text note** — it's transcribed, titled, tagged, previewed, and saved as a Notion row.
- **Edit before saving** — adjust title, text, tags, or date, or reformat the text; nothing is written until you press Save.
- **🔥 Roast** — get an honest take on your entry, with follow-up chat; tell it to behave differently and it remembers.
- **Summaries** — automatic daily recap and an on-demand weekly report.

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome and quick overview |
| `/help` | Commands and preview buttons |
| `/weekly` | Generate the weekly highlight report now |
| `/stat` | Saved audio minutes overall, by day, and by month |
| `/memory` | Rebuild the author profile from every saved note, guided by focus points you supply |
| `/rules` | Show the behavior rules the bot learned from you |

The bot publishes this list to Telegram on startup, so typing `/` in the chat shows it.

## Docs

- **[Usage](docs/usage.md)** — preview & editing, highlights, roast mode, behavior rules, author profile, tags, summaries.
- **[Configuration](docs/configuration.md)** — environment variables, AI provider, Notion setup.
- **[Development & deployment](docs/deployment.md)** — local dev, tests, VPS + systemd, project structure, costs.
