# Development & deployment

## Local development

```bash
make dev        # stop the VPS bot and run locally
make stop-dev   # restore the VPS bot when done
make test       # offline validation — no Telegram/OpenAI/Notion calls
```

## Deploy to VPS

```bash
make deploy
```

Pushes to GitHub, pulls on the VPS, and restarts the bot.

## First-time VPS setup

```bash
git clone https://github.com/shataev/audio-noter-bot.git /opt/noter
cd /opt/noter
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && nano .env   # fill in all values
```

Create `/etc/systemd/system/noter.service`:

```ini
[Unit]
Description=Noter Telegram Bot
After=network.target

[Service]
User=root
WorkingDirectory=/opt/noter
ExecStart=/opt/noter/.venv/bin/python bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable noter
systemctl start noter
```

Useful commands:

```bash
systemctl status noter     # status
journalctl -u noter -f     # live logs
systemctl restart noter    # restart
```

## Project structure

```
bot.py                  # Telegram bot entry point
config.py               # Settings loaded from .env
services/
├── whisper.py          # Audio transcription (OpenAI Whisper)
├── formatter.py        # Entry title/tags/text formatting
├── ai.py               # Chat client factory (OpenAI / Anthropic)
├── notion.py           # Notion API: create/read diary pages
├── summary.py          # Daily summary & weekly report
├── roast.py            # Roast mode + author profile
├── stats.py            # Audio-minute stats
├── state_store.py      # Local JSON state (messages, drafts, profile)
└── diary_dates.py      # Diary-day date logic
Makefile                # Dev & deploy commands
requirements.txt
.env.example
```

## Estimated costs

Cheap for personal use — dominated by Whisper:

| Service | Price | Per entry (~1 min voice) |
|---------|-------|--------------------------|
| Whisper | $0.006 / minute | ~$0.006 |
| Chat models | depends on model | usually well below $0.001 |

100 entries/month ≈ **$0.60**.
