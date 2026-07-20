#!/usr/bin/env python3
"""
Content Desk sync — parse today's drafts fully (body + Midjourney/Grok prompts)
and push them to the stage worker so the backoffice deck can render them.
Run from ~/.openclaw/workspace. Cron: 06:10 & 19:25 (just before the heartbeat).
"""
import json
import os
import re
import urllib.request
from datetime import datetime

OFFICE = "/media/psf/iCloud/BRAIN/CW/SOLAR-PLEXUS/Content Office/02_Drafts_From_Chief_Wizard"
MEDIA = "/media/psf/iCloud/BRAIN/CW/SOLAR-PLEXUS/Content Office/MEDIA_INBOX"
MEDIA_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov"}
WORKER = "https://starlove-stage.devinohms.workers.dev"
KEY = open(os.path.expanduser("~/.starlove_agent_key")).read().strip()
HDR = {"x-agent-key": KEY, "Content-Type": "application/json",
       "User-Agent": "Mozilla/5.0 (ContentDesk)"}


def field(s, name):
    m = re.search(rf"\*\*{name}:\*\*\s*(.+)", s)
    return m.group(1).strip() if m else ""


def block_after(s, header):
    """Text between a **Header:** line and the next **...** line / section."""
    m = re.search(rf"\*\*{header}:?\*\*\s*\n(.*?)(?=\n\*\*|\n## |\Z)", s, re.DOTALL)
    return m.group(1).strip() if m else ""


def parse(path, rel):
    s = open(path, encoding="utf-8", errors="replace").read()
    title = next((l.lstrip("# ").strip() for l in s.splitlines() if l.startswith("#")),
                 os.path.basename(path))
    m = re.search(r"## POST BODY\s*\n(.*)", s, re.DOTALL)
    body = re.sub(r"\n{3,}", "\n\n", (m.group(1) if m else "").strip())
    return {
        "id": rel,
        "t": int(os.path.getmtime(path) * 1000),
        "channel": os.path.basename(os.path.dirname(path)).replace("_", " "),
        "title": title,
        "brand": field(s, "Brand"),
        "slot": field(s, "Slot").split("—")[0].strip().lower(),
        "nugget": field(s, "Nugget")[:300],
        "mj": block_after(s, "Midjourney prompt")[:2000],
        "grok": block_after(s, r"Grok Imagine video prompt[^*\n]*")[:2000],
        "body": body[:20000],
    }


def main():
    d = datetime.now()
    day = os.path.join(OFFICE, d.strftime("%Y"), d.strftime("%m-%d-%y"))
    items = []
    if os.path.isdir(day):
        for root, _dirs, files in os.walk(day):
            for f in sorted(files):
                if f.startswith("post_") and f.endswith(".md"):
                    p = os.path.join(root, f)
                    try:
                        items.append(parse(p, os.path.relpath(p, OFFICE)))
                    except Exception as e:
                        print(f"parse fail {f}: {e}")
    media_files = []
    if os.path.isdir(MEDIA):
        names = [n for n in os.listdir(MEDIA)
                 if os.path.isfile(os.path.join(MEDIA, n))
                 and os.path.splitext(n)[1].lower() in MEDIA_EXT]
        names.sort(key=lambda n: -os.path.getmtime(os.path.join(MEDIA, n)))
        for n in names[:40]:
            p = os.path.join(MEDIA, n)
            media_files.append({"name": n, "size": os.path.getsize(p),
                                "t": int(os.path.getmtime(p) * 1000),
                                "video": os.path.splitext(n)[1].lower() in {".mp4", ".mov"}})
    req = urllib.request.Request(f"{WORKER}/desk/sync",
                                 data=json.dumps({"items": items, "media_files": media_files}).encode(),
                                 headers=HDR)
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"synced {len(items)} drafts + {len(media_files)} media; desk holds {json.load(r).get('count')}")


if __name__ == "__main__":
    main()
