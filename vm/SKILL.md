# Content Desk — publish drafts to X on the operator's command

## When to use
The operator (via the configured Telegram chat) replies to a "🧙 Content Desk" heartbeat
message with commands like: `publish 2`, `edit 2: <changes>`, `show 2`, `art 2`,
or natural language ("post the second one", "publish the tarot one").

## The system
- A cron sends the Content Desk digest from this bot at 06:15 and 19:30. It numbers
  the fresh drafts and writes the mapping to `memory/content-desk-manifest.json`.
- Draft files live in the content office drafts folder. Each has metadata, a
  **Midjourney prompt**, a **Grok Imagine video prompt**, and a `## POST BODY` section.

## Commands to run (from ~/.openclaw/workspace)
- **show N** → `python3 scripts/publish_draft.py --n N` (dry-run prints the full body; relay it)
- **publish N** → `python3 scripts/publish_draft.py --n N --execute`
  → reply with the tweet URL it prints. It auto-archives the draft,
  writes the ledger, and logs `published` to the backoffice.
- **edit N: <changes>** → read the draft file (path from manifest), apply the
  edits to the `## POST BODY` section in place (keep metadata + prompts intact),
  show the new body, and wait for a `publish N` confirmation.
- **art N** → read the draft and send the **Midjourney prompt** and
  **Grok Imagine video prompt** blocks verbatim (they're paste-ready for the art rail).

## Rules
- NEVER post without an explicit publish command for that specific draft.
- If publish fails with a length error, offer a trimmed <280-char version and
  wait for approval before retrying.
- If the manifest is stale (draft file missing), re-run
  `python3 scripts/content_heartbeat.py` and say the numbers refreshed.
