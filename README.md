# 🧙 Star Love Content Desk

A **swipe-style review & publish system** for AI-generated social content — built by the
Star Love XP exec fleet and battle-tested on [starlovexp.com/backoffice](https://starlovexp.com/backoffice/).

Your content engine writes drafts. The Content Desk turns them into a card deck you
review from any device: read the hook, expand the full post, edit inline, attach
images/video, then **post now** or **schedule** — on alignment-number times
(9:09, 10:10, 11:11…) if that's your cadence. A Telegram heartbeat rings your
phone when fresh drafts are ready, and you can drive the whole thing by replying
`publish 2` to your agent bot instead.

```
 content engine (cron)          YOU (any device)
   drafts/*.md  ──sync──►  Cloudflare Worker (Durable Object)  ◄──deck UI── backoffice page
                             │  /desk/list /desk/action /desk/upload …
   VM poller  ◄──actions─────┘         ▲
   ├─ publish_draft.py → X API         │ chunked media uploads
   ├─ schedule queue (exact minute)    │
   └─ heartbeat → Telegram      Mac media fetcher ─► iCloud MEDIA_INBOX
```

## Components

| Path | Runs on | What it does |
|---|---|---|
| `worker/` | Cloudflare | One Durable Object: draft deck state, review actions queue, chunked media relay, ops timeline, agent chat relay |
| `backoffice/` | static page | The deck UI — cards, inline editing, media attach chips, alignment-time scheduler, live status chips |
| `vm/content_desk_sync.py` | content box (cron) | Parses the day's drafts (+ media inbox listing) and pushes them to the worker |
| `vm/content_desk_poller.py` | content box (daemon) | Executes your review actions: publish, schedule (drains at the exact minute), edits, media deletes |
| `vm/publish_draft.py` | content box | Posts to X (v2) with media (v1.1 simple + chunked video upload), archives the draft, writes a ledger |
| `vm/content_heartbeat.py` | content box (cron) | Telegram doorbell: “N fresh drafts await review” + deep link |
| `vm/SKILL.md` | your agent | Teaches an OpenClaw/agent bot to handle `publish N` / `show N` / `art N` replies |
| `mac/media_fetcher.py` | host Mac (daemon) | Assembles browser-uploaded media from worker chunks straight into the iCloud inbox — with retries, on a reliable network |
| `mac/ops_log.py` | host Mac | Tiny helper to log pipeline events to the backoffice timeline |

## Design notes (learned the hard way)

- **Outbound-only bridges.** The content box never accepts inbound connections — it polls
  the worker. Works behind NAT, nothing to firewall.
- **Cursor-primed pollers.** Every poller primes its cursor to the queue tip on boot, so a
  restart never replays the backlog (a replay storm once pegged our VM for half an hour).
- **Assemble media on the machine with the good network.** Chunk assembly retries per-chunk;
  one connection reset must not kill a 20MB upload.
- **Truncate filename bases, never extensions.** Midjourney filenames are >100 chars.
- **Index-based DOM handlers.** Inline `onclick="...'${id}'..."` breaks the day a channel
  is named *Tookie's Tarot*.
- **The last chunk is the commit.** Upload chunks in parallel, but send the final chunk
  alone — it's what queues the assembly action.

## Setup (short version)

1. **Worker:** `cd worker && wrangler deploy`, then `wrangler secret put AGENT_KEY`
   (shared with your pollers) and optionally `OPS_KEY` (write-only ops logging for
   other tools). Edit `OK_ORIGIN` to your domain.
2. **Backoffice:** host `backoffice/index.html` anywhere on that domain; set `LIVE` to
   your worker URL. Put a real passphrase behind your own auth (the included gate is a
   convenience, not a fortress).
3. **Content box:** drop the `vm/` scripts beside your drafts folder, set the paths at the
   top of each, run the poller under systemd, cron the sync+heartbeat
   (`CONTENT_DESK_CHAT` env = your Telegram chat id). X credentials are read from your
   existing OAuth1 setup — see `publish_draft.py`.
4. **Host Mac (optional, for browser uploads):** run `mac/media_fetcher.py` under launchd.

Draft format expected: markdown files with `## POST BODY`, and optionally
`**Nugget:**`, `**Brand:**`, `**Slot:**`, `**Midjourney prompt:**`,
`**Grok Imagine video prompt…**` blocks — see the blog post for how our engine
generates them (including a mandatory 10-second video + `Audio:` direction).

## License

MIT — take it, fly it, make it yours. ✨

*Built with the crew: Boss Gnoss (CEO), Chief Wizard (CTO), Dr Raja (COO),
Admiral Harmony (CMO), Quant Saber (CFO) — the S.S. Starlove XP.*
