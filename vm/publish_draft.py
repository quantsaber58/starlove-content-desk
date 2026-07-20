#!/usr/bin/env python3
"""
Publish a Content Desk draft to X. Used by the agent's content-desk skill and
the deck poller.

  python3 scripts/publish_draft.py --n 2              # dry-run preview of draft #2
  python3 scripts/publish_draft.py --n 2 --execute    # post it
  python3 scripts/publish_draft.py --file <path> --media img.png --execute

On success: archives the draft to 06_Published_Archive, appends
memory/content-desk-ledger.jsonl, logs `published` to the backoffice ops feed.
X credentials: OAuth1 user-context keys — this script exec's the constants
block of scripts/x_targeted_follow.py (API_KEY, API_SECRET, ACCESS_TOKEN,
ACCESS_TOKEN_SECRET); adapt to your own credential store.
Run from ~/.openclaw/workspace.
"""
import argparse
import json
import os
import re
import shutil
import sys
import urllib.request
from datetime import datetime

WS = os.path.expanduser("~/.openclaw/workspace")
OFFICE = "/media/psf/iCloud/BRAIN/CW/SOLAR-PLEXUS/Content Office"
MANIFEST = os.path.join(WS, "memory", "content-desk-manifest.json")
LEDGER = os.path.join(WS, "memory", "content-desk-ledger.jsonl")
OPS_URL = "https://starlove-stage.devinohms.workers.dev/ops/log"
OPS_KEY_FILE = os.path.expanduser("~/.starlove_agent_key")

sys.path.insert(0, WS)
exec(open(os.path.join(WS, "scripts/x_targeted_follow.py")).read().split("def ")[0])  # API creds
from requests_oauthlib import OAuth1Session

MEDIA_INBOX = os.path.join(OFFICE, "MEDIA_INBOX")
UPLOAD = "https://upload.twitter.com/1.1/media/upload.json"
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def upload_media(oauth, path):
    """Upload one media file; returns media_id string. Chunked for video."""
    ext = os.path.splitext(path)[1].lower()
    if ext in IMG_EXT:
        with open(path, "rb") as f:
            r = oauth.post(UPLOAD, files={"media": f})
        if r.status_code not in (200, 201):
            raise RuntimeError(f"image upload failed {r.status_code}: {r.text[:200]}")
        return r.json()["media_id_string"]
    # video: chunked INIT / APPEND / FINALIZE (+ processing wait)
    import time as _t
    total = os.path.getsize(path)
    mime = "video/mp4" if ext == ".mp4" else "video/quicktime"
    r = oauth.post(UPLOAD, data={"command": "INIT", "total_bytes": total,
                                 "media_type": mime, "media_category": "tweet_video"})
    if r.status_code not in (200, 201, 202):
        raise RuntimeError(f"video INIT failed {r.status_code}: {r.text[:200]}")
    mid = r.json()["media_id_string"]
    with open(path, "rb") as f:
        seg = 0
        while True:
            chunk = f.read(4 * 1024 * 1024)
            if not chunk:
                break
            r = oauth.post(UPLOAD, data={"command": "APPEND", "media_id": mid, "segment_index": seg},
                           files={"media": chunk})
            if r.status_code not in (200, 201, 204):
                raise RuntimeError(f"video APPEND seg{seg} failed {r.status_code}")
            seg += 1
    r = oauth.post(UPLOAD, data={"command": "FINALIZE", "media_id": mid})
    if r.status_code not in (200, 201):
        raise RuntimeError(f"video FINALIZE failed {r.status_code}: {r.text[:200]}")
    info = r.json().get("processing_info")
    while info and info.get("state") in ("pending", "in_progress"):
        _t.sleep(info.get("check_after_secs", 3))
        r = oauth.get(UPLOAD, params={"command": "STATUS", "media_id": mid})
        info = r.json().get("processing_info")
    if info and info.get("state") == "failed":
        raise RuntimeError(f"video processing failed: {json.dumps(info)[:200]}")
    return mid


def resolve_media(names):
    out = []
    for n in [x.strip() for x in names.split(",") if x.strip()]:
        p = n if os.path.isabs(n) else os.path.join(MEDIA_INBOX, n)
        if not os.path.isfile(p):
            sys.exit(f"media not found: {p}")
        out.append(p)
    return out[:4]


def post_body(path):
    s = open(path, encoding="utf-8", errors="replace").read()
    m = re.search(r"## POST BODY\s*\n(.*)", s, re.DOTALL)
    body = (m.group(1) if m else s).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body


def ops_event(action, detail):
    try:
        key = open(OPS_KEY_FILE).read().strip()
        now = datetime.now()
        job = f"gnoss-dispatch-{now:%Y%m%d}-{'am' if now.hour < 12 else 'pm'}"
        data = json.dumps({"job": job, "actor": "Chief Wizard", "action": action,
                           "detail": detail[:800]}).encode()
        req = urllib.request.Request(OPS_URL, data=data, headers={
            "Content-Type": "application/json", "x-agent-key": key,
            "User-Agent": "Mozilla/5.0 (ContentDesk)"})
        urllib.request.urlopen(req, timeout=20)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", help="draft number from the latest Content Desk heartbeat")
    ap.add_argument("--file", help="explicit draft path")
    ap.add_argument("--media", help="comma-separated media (MEDIA_INBOX names or abs paths, max 4)")
    ap.add_argument("--execute", action="store_true", help="actually post (default: dry-run)")
    a = ap.parse_args()

    path = a.file
    if a.n:
        man = json.load(open(MANIFEST))
        path = man["posts"].get(str(a.n))
        if not path:
            sys.exit(f"no draft #{a.n} in manifest (run content_heartbeat.py first)")
    if not path or not os.path.isfile(path):
        sys.exit(f"draft not found: {path}")

    body = post_body(path)
    media_paths = resolve_media(a.media) if a.media else []
    print(f"— DRAFT: {path}\n— LENGTH: {len(body)} chars"
          + (f"\n— MEDIA: {', '.join(os.path.basename(p) for p in media_paths)}" if media_paths else "")
          + f"\n{'-'*50}\n{body[:600]}\n{'-'*50}")
    if not a.execute:
        print("(dry-run — add --execute to post)")
        return

    oauth = OAuth1Session(API_KEY, client_secret=API_SECRET,
                          resource_owner_key=ACCESS_TOKEN, resource_owner_secret=ACCESS_TOKEN_SECRET)
    payload = {"text": body}
    if media_paths:
        ids = []
        for p in media_paths:
            print(f"uploading {os.path.basename(p)}…")
            ids.append(upload_media(oauth, p))
        payload["media"] = {"media_ids": ids}
    r = oauth.post("https://api.twitter.com/2/tweets", json=payload)
    if r.status_code not in (200, 201):
        detail = r.text[:300]
        if len(body) > 280 and ("280" in detail or "length" in detail.lower() or r.status_code == 403):
            sys.exit(f"POST FAILED {r.status_code}: {detail}\nLikely over 280 chars without X Premium long-posts — trim or thread it.")
        sys.exit(f"POST FAILED {r.status_code}: {detail}")
    tweet_id = r.json().get("data", {}).get("id", "?")
    url = f"https://x.com/i/web/status/{tweet_id}"
    print(f"POSTED: {url}")

    # archive + ledger + backoffice
    rel = os.path.relpath(path, os.path.join(OFFICE, "02_Drafts_From_Chief_Wizard"))
    dest = os.path.join(OFFICE, "06_Published_Archive", rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.move(path, dest)
    for p in media_paths:  # keep the inbox clean; posted media is archived
        if p.startswith(MEDIA_INBOX):
            dest_m = os.path.join(MEDIA_INBOX, "posted", os.path.basename(p))
            os.makedirs(os.path.dirname(dest_m), exist_ok=True)
            shutil.move(p, dest_m)
    with open(LEDGER, "a") as f:
        f.write(json.dumps({"t": datetime.now().isoformat(), "file": rel,
                            "media": [os.path.basename(p) for p in media_paths],
                            "tweet_id": tweet_id, "url": url}) + "\n")
    ops_event("published", f"{os.path.basename(rel)}"
              + (f" +{len(media_paths)} media" if media_paths else "") + f" → {url}")
    print(f"archived → 06_Published_Archive/{rel}")


if __name__ == "__main__":
    main()
