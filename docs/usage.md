# Usage

Commands live in Telegram's `/` menu (published on startup); `/help` prints the same list plus the preview buttons.

## How it works

1. You send a voice (or text) message to the bot.
2. Voice is transcribed with OpenAI Whisper.
3. The formatter generates a title, tags, and a lightly cleaned text candidate.
4. The bot shows a preview — generated title/tags, but the original transcription as the text.
5. Optionally **Format** to swap in the cleaned text (split into paragraphs); **↺ Original** restores it.
6. Optionally mark the entry as a highlight ⭐.
7. Press **Save** — the entry becomes its own row in your Notion database.

## Editing before saving

The processing reply turns into a single preview message you edit in place:

```
Generated title

Original transcribed text

Date: Today (YYYY-MM-DD)

Daily sport health

[ ✎ Title ]  [ ✎ Text ]  [ ✎ Tags ]
[              ✦ Format              ]
[        Date: Today (YYYY-MM-DD)        ]
[      Mark as Highlight ⭐       ]
[            🔥 Roast             ]
[            ✓ Save              ]
[            Cancel              ]
```

- **✎ Title / Text / Tags** — prompt you for a new value; the preview updates in place.
- **✦ Format** — replaces only the draft text with the formatter's cleaned version (semantic paragraphs, saved as separate Notion blocks). It fixes recognition/grammar slips without changing your wording or meaning. Becomes **↺ Original** so you can revert.
- **Date** — opens a 7-day picker. **Back to preview** keeps the date; **Cancel draft** discards.
- **Cancel** — discards the draft without saving.

Nothing is written to Notion until you press **Save**. If saving fails, the preview stays with the Save button so you can retry. If the bot recognizes an already-saved voice message, it warns you first and offers **Add anyway**.

## Highlights

**Mark as Highlight ⭐** flags the entry as a key moment of the week (toggle to unmark). Saved highlights get a `⭐` prefix on the Notion heading and are surfaced first in the weekly report.

## 🔥 Roast mode (разъёб)

**🔥 Roast** sends the current draft to a high-reasoning model that plays a blunt-but-caring street-bro: honest, on your side, teasing where it helps, never sugar-coating. The take is posted as a new reply — your draft is never modified.

Reply to any roast message to keep the thread going; the bot sends the whole prior chain plus your reply back to the model. Voice replies work too — they're transcribed first and never become a new diary entry. These conversations live in RAM only and are discarded on restart.

The button is available whenever the active AI provider's API key is set (see [Configuration](configuration.md)). The persona is built in but can be replaced with `ROAST_SYSTEM_PROMPT`; set `ROAST_LANGUAGE` to force a reply language regardless of the entry's language.

### Author profile

The bot distills a compact **author profile** — one-sentence facts about who you are — refreshed from **every diary message** (best-effort, in the background). It captures durable, decision-shaping context: long-term traits and biases, values, recurring patterns, key relationships and goals, and your current life phase (medium-term, not day-to-day). New knowledge is merged and semantically deduped; transient one-offs are dropped, and a message that adds nothing leaves the list unchanged. Under the hood the model returns only what changed (added, removed, reworded facts) and the merge happens locally, so the request cost stays flat as the profile grows; an unusable response leaves the accumulated profile intact. The points persist in local state and are fed back as background context on the next roast. Pick the model with `OPENAI_PROFILE_MODEL` (defaults to `OPENAI_SUMMARY_MODEL`).

### Rebuilding the profile retrospectively — `/memory`

`/memory` walks your whole diary history and rebuilds the profile from it, in two steps:

1. **Focus** — the bot asks what should drive this pass (what matters most, what to keep, what to drop). Reply with text or a voice message; send `-` to rebuild without extra focus. The reply is only ever read as focus, never saved as a diary note.
2. **Confirm** — the bot echoes the focus and the current fact count, then waits for **✓ Confirm** or **✗ Cancel**. Nothing runs until you confirm.

On confirm the bot walks every Notion note **oldest-first, one at a time** — one AI request per note, each fed the profile accumulated so far, exactly like the per-message refresh. Existing facts seed the pass and get corrected as it goes; an empty profile is built from scratch. Focus steers what gets pulled out and how known facts are reframed, and is never stored as a fact itself.

The status message shows a live progress bar (throttled to stay inside Telegram's edit rate limits) and the running fact count, and the final message reports the fact delta plus any skipped or failed notes.

The pass is built to be dull and safe:

- **Sequential** — never concurrent, with a short pause between notes so Notion and the AI provider aren't hammered.
- **Single-flight** — a second `/memory` run is refused while one is in flight.
- **Fault-isolated** — a note that can't be read or extracted is counted and skipped; accumulated facts are untouched.
- **Circuit-broken** — the pass aborts once notes fail back-to-back instead of burning one doomed request per remaining note.
- **Incrementally saved** — facts are persisted after every note, so an abort or a restart never loses the pass.

## Tags

The `Daily` tag is always added. Additional tags can be:

- **Extracted by the formatter** — mention them naturally: _"went for a run today. Tags: sport, health"_.
- **Edited manually** — click **✎ Tags** and send them comma-separated: `sport, health, work`.

## Summaries

Every day at 21:00 (your timezone) the bot posts a summary of that day's entries, or a friendly reminder if there were none. Daily and weekly summaries include a small stats block (entry count, saved audio minutes, and the busiest day for weekly reports). Use `/weekly` to generate the weekly highlight report on demand.

`/stat` shows total saved audio time, minutes for each of the last 7 days, and monthly totals for the last 6 months — computed from saved Notion rows with `Audio Duration` filled in.

Date-picker defaults and summaries respect `DIARY_DAY_START_HOUR`: with `DIARY_DAY_START_HOUR=4`, entries before 04:00 belong to the previous diary date.
