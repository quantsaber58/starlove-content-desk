#!/usr/bin/env python3
"""
Content Desk media fetcher — host-Mac resident (launchd, KeepAlive).

Assembles browser-uploaded files from the stage worker's chunk store straight
into the iCloud MEDIA_INBOX — which the Mac owns natively, so files appear
instantly (no iCloud sync wait) and the content box sees them through its
shared-folder mount.

Why the Mac and not the content box: a VM's egress can drop connections
("Connection reset by peer"), and assembling a 20MB file takes ~300 chunk
fetches. Here each chunk gets 3 retries with backoff on a reliable network.

Handles ONLY fetch_media actions (own cursor: .media_cursor); the content box's
poller handles everything else with its own cursor.
Expects a .env beside this file with STAGE_AGENT_KEY (and optional STAGE_WORKER_URL).
"""
import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HOME = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOME)
from ops_log import _env

ENV = _env()
WORKER = ENV.get("STAGE_WORKER_URL", "https://starlove-stage.devinohms.workers.dev").rstrip("/")
KEY = ENV["STAGE_AGENT_KEY"]
HDR = {"x-agent-key": KEY, "Content-Type": "application/json",
       "User-Agent": "Mozilla/5.0 (StarloveMediaFetcher)"}
INBOX = os.path.expanduser(
    "~/Library/Mobile Documents/com~apple~CloudDocs/BRAIN/CW/SOLAR-PLEXUS/Content Office/MEDIA_INBOX")
CURSOR = os.path.join(HOME, ".media_cursor")


def _req(url, data=None, extra_headers=None, tries=3):
    last = None
    for attempt in range(tries):
        try:
            h = dict(HDR)
            if extra_headers:
                h.update(extra_headers)
            req = urllib.request.Request(url, data=data, headers=h,
                                         method="POST" if data else "GET")
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"request failed after {tries} tries: {last}")


def fetch_media(name, total):
    os.makedirs(INBOX, exist_ok=True)
    dest = os.path.join(INBOX, name)
    base, ext = os.path.splitext(name)
    n = 2
    while os.path.exists(dest):
        dest = os.path.join(INBOX, f"{base}-{n}{ext}")
        n += 1
    buf = b""
    for i in range(total):
        d = _req(f"{WORKER}/desk/file?name={urllib.parse.quote(name)}&seq={i}").get("data")
        if d is None:
            raise RuntimeError(f"missing chunk {i}/{total}")
        buf += base64.b64decode(d)
    with open(dest, "wb") as f:
        f.write(buf)
    _req(f"{WORKER}/desk/file_done", data=json.dumps({"name": name, "total": total}).encode())
    # ask the content box to resync the deck (origin-gated route — we set our own Origin)
    _req(f"{WORKER}/desk/action", data=json.dumps({"action": "resync"}).encode(),
         extra_headers={"Origin": "https://starlovexp.com"})
    print(f"landed: {os.path.basename(dest)} ({len(buf)} bytes)", flush=True)


def main():
    try:
        since = int(open(CURSOR).read().strip())
    except Exception:
        since = -1
        try:
            items = _req(f"{WORKER}/desk/actions?since=-1").get("items", [])
            if items:
                since = max(a["seq"] for a in items)
        except Exception:
            pass
    print(f"media-fetcher started (cursor {since})", flush=True)
    while True:
        try:
            for a in _req(f"{WORKER}/desk/actions?since={since}").get("items", []):
                since = max(since, a["seq"])
                open(CURSOR, "w").write(str(since))
                if a.get("action") != "fetch_media":
                    continue
                try:
                    fetch_media(a.get("name"), int(a.get("total") or 0))
                except Exception as e:
                    print(f"fetch_media failed for {a.get('name')}: {e}", flush=True)
        except Exception as e:
            print("loop error:", e, flush=True)
        time.sleep(4)


if __name__ == "__main__":
    main()
