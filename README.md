# Content Desk

A **swipe-style review & publish system** for AI-generated social content — open-sourced
by the crew at [Star Love XP](https://starlovexp.com). 🧙✨

Your content engine writes drafts. The Content Desk turns them into a card deck you
review from any device: read the hook, expand the full post, edit inline, attach
images/video, then **post now** or **schedule**. A Telegram heartbeat rings your
phone when fresh drafts are ready, and you can drive the whole thing by replying
`publish 2` to your own agent bot instead.

**Your schedule, your cadence.** The scheduler presents a dropdown of preset posting
times defined in one array — ours happen to be alignment numbers (9:09, 11:11, 2:22…);
yours can be anything. Slots already claimed by another post show as taken, so every
post in a batch gets its own moment.

```
 content engine (cron)          YOU (any device)
   drafts/*.md  ──sync──►  Cloudflare Worker (Durable Object)  ◄──deck UI── backoffice page
                             │  /desk/list /desk/action /desk/upload …
   poller  ◄──actions───────┘         ▲
   ├─ publish_draft.py → X API         │ chunked media uploads
   ├─ schedule queue (exact minute)    │
   └─ heartbeat → Telegram      host media fetcher ─► shared MEDIA_INBOX
```

## Components

| Path | Runs on | What it does |
|---|---|---|
| `worker/` | Cloudflare | One Durable Object: draft deck state, review actions queue, chunked media relay, ops timeline, agent chat relay |
| `backoffice/` | static page | The deck UI — cards, inline editing, media attach chips, preset-time scheduler, live status chips |
| `vm/content_desk_sync.py` | content box (cron) | Parses the day's drafts (+ media inbox listing) and pushes them to the worker |
| `vm/content_desk_poller.py` | content box (daemon) | Executes your review actions: publish, schedule (drains at the exact minute), edits, media deletes |
| `vm/publish_draft.py` | content box | Posts to X (v2) with media (v1.1 simple + chunked video upload), archives the draft, writes a ledger |
| `vm/content_heartbeat.py` | content box (cron) | Telegram doorbell: “N fresh drafts await review” + link to your desk |
| `vm/SKILL.md` | your agent | Teaches an agent bot to handle `publish N` / `show N` / `art N` replies |
| `mac/media_fetcher.py` | host machine (daemon) | Assembles browser-uploaded media from worker chunks into the shared inbox — with retries, on a reliable network |
| `mac/ops_log.py` | host machine | Tiny helper to log pipeline events to the backoffice timeline |

## Security model

Three layers, three secrets (all `wrangler secret put …`):

- **`AGENT_KEY`** — shared by your pollers/bridges for the machine-to-machine routes.
- **`OPS_KEY`** (optional) — a write-only key for external tools that should log events
  but never read chats or drive agents.
- **`DESK_PASS`** — the operator passphrase. The browser UI sends it as an
  `x-desk-pass` header on every call after login; the worker rejects UI routes without
  it. **Until you set this secret the UI routes fall back to origin-gating only — set
  it before you put real drafts behind this.** The client-side gate in the page is
  cosmetic UX, not security; the worker check is the lock.

## Design notes (learned the hard way)

- **Outbound-only bridges.** The content box never accepts inbound connections — it polls
  the worker. Works behind NAT, nothing to firewall.
- **Cursor-primed pollers.** Every poller primes its cursor to the queue tip on boot, so a
  restart never replays the backlog (a replay storm once pegged our VM for half an hour).
- **Assemble media on the machine with the good network.** Chunk assembly retries per-chunk;
  one connection reset must not kill a 20MB upload.
- **Truncate filename bases, never extensions.** AI image generators emit >100-char filenames.
- **Index-based DOM handlers.** Inline `onclick="...'${id}'..."` breaks the day a folder
  has an apostrophe in its name.
- **The last chunk is the commit.** Upload chunks in parallel, but send the final chunk
  alone — it's what queues the assembly action.

## Setup (short version)

1. **Worker:** `cd worker && wrangler deploy`, then set the three secrets above and edit
   `OK_ORIGIN` to your domain.
2. **Backoffice:** host `backoffice/index.html` on that domain; edit the CONFIG block at
   the top (worker URL, posting times, agent names).
3. **Content box:** drop the `vm/` scripts beside your drafts folder, set the paths at the
   top of each, run the poller under systemd, cron the sync + heartbeat
   (`CONTENT_DESK_CHAT` env = your Telegram chat id). X credentials are OAuth1
   user-context keys — see `publish_draft.py`.
4. **Host machine (optional, for browser uploads):** run `mac/media_fetcher.py` under
   launchd/systemd.

Draft format expected: markdown files with `## POST BODY`, and optionally
`**Nugget:**`, `**Brand:**`, `**Slot:**`, `**Midjourney prompt:**`, and a video
prompt block — our engine also appends an `Audio:` direction to every video prompt.

## License

MIT — take it, fly it, make it yours. ✨

*Built with determination aboard the [S.S. Starlove XP](https://starlovexp.com).*
