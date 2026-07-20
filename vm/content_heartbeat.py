#!/usr/bin/env python3
"""
Content Desk heartbeat — sent BY your agent's bot (e.g. @ChiefWizard11, the main
OpenClaw account's token) so the operator can reply to the same bot in natural
language ("publish 2") and the agent executes via the content-desk skill.

Scans today's dated folder of drafts, numbers the posts, writes
memory/content-desk-manifest.json, sends a doorbell digest.
Run from ~/.openclaw/workspace. Cron: 06:15 & 19:30 daily.
Set CONTENT_DESK_CHAT to your Telegram chat id.
"""
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta

WS = os.path.expanduser("~/.openclaw/workspace")
OFFICE = "/media/psf/iCloud/BRAIN/CW/SOLAR-PLEXUS/Content Office/02_Drafts_From_Chief_Wizard"
MANIFEST = os.path.join(WS, "memory", "content-desk-manifest.json")
CHAT = os.environ.get("CONTENT_DESK_CHAT", "")  # your Telegram chat id


def cw_token():
    d = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json")))
    acc = d["channels"]["telegram"]["accounts"]["main"]
    return acc.get("botToken") or acc.get("token")


def send(msg):
    url = f"https://api.telegram.org/bot{cw_token()}/sendMessage"
    data = json.dumps({"chat_id": CHAT, "text": msg, "parse_mode": "HTML",
                       "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30)


def parse_draft(path):
    try:
        s = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return None
    title = next((l.lstrip("# ").strip() for l in s.splitlines() if l.startswith("#")), os.path.basename(path))
    def field(name):
        m = re.search(rf"\*\*{name}:\*\*\s*(.+)", s)
        return m.group(1).strip() if m else ""
    nugget = field("Nugget")
    return {"file": path, "title": title, "brand": field("Brand"),
            "slot": field("Slot").split("—")[0].strip(), "nugget": nugget[:160],
            "has_mj": "**Midjourney prompt:**" in s, "has_video": "Grok Imagine video prompt" in s}


def main():
    days = []
    for back in (0,):
        d = datetime.now() - timedelta(days=back)
        days.append(os.path.join(OFFICE, d.strftime("%Y"), d.strftime("%m-%d-%y")))
    posts = []
    for day in days:
        if not os.path.isdir(day):
            continue
        for root, _dirs, files in os.walk(day):
            for f in sorted(files):
                if f.startswith("post_") and f.endswith(".md"):
                    p = parse_draft(os.path.join(root, f))
                    if p:
                        p["channel"] = os.path.basename(root).replace("_", " ")
                        posts.append(p)
    posts = posts[:12]
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    json.dump({"generated": datetime.now().isoformat(),
               "posts": {str(i + 1): p["file"] for i, p in enumerate(posts)}},
              open(MANIFEST, "w"), indent=1)

    if not posts:
        send("\U0001f9d9 <b>Content Desk</b> — no fresh drafts today. The forge is cold; I shall investigate.")
        return
    channels = sorted({p["channel"] for p in posts})
    media = sum(1 for p in posts if p["has_mj"] or p["has_video"])
    msg = (
        f"\U0001f9d9 <b>Content Desk</b> — {len(posts)} fresh drafts await your review, Captain\n"
        f"\U0001f4da {', '.join(channels)}"
        + (f"  ·  \U0001f3a8 {media} with art prompts" if media else "") + "\n\n"
        "→ <a href=\"https://starlovexp.com/backoffice/\">Open the Content Desk</a> — "
        "read, edit, post now, or schedule.\n\n"
        "<i>(Away from the desk? Reply here: publish N · show N · art N)</i>"
    )
    send(msg)
    print(f"heartbeat sent: {len(posts)} drafts")


if __name__ == "__main__":
    main()
