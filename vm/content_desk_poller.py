#!/usr/bin/env python3
"""
Content Desk poller — executes the review actions taken on the backoffice deck.
Runs as a systemd user service (content-desk-poller.service).

Loop every 5s:
  • pull /desk/actions since cursor
      save_edit          → rewrite the draft's ## POST BODY in place
      publish [+body]    → (save edit if body) then publish_draft.py --file --execute
      schedule [+when]   → append to memory/content-desk-schedule.jsonl
      delete_media       → soft-delete an inbox file (MEDIA_INBOX/trash/)
      resync             → re-run content_desk_sync.py
  • drain due scheduled posts (when <= now) through the same publish path
  • report each outcome to /desk/result (backoffice chip updates live)
Cursor persisted in memory/.content-desk-cursor so restarts never replay.
(fetch_media actions are handled by the host Mac's media_fetcher.py — the
machine with the reliable network and native access to the media folder.)
"""
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

WS = os.path.expanduser("~/.openclaw/workspace")
OFFICE = "/media/psf/iCloud/BRAIN/CW/SOLAR-PLEXUS/Content Office/02_Drafts_From_Chief_Wizard"
WORKER = "https://starlove-stage.devinohms.workers.dev"
KEY = open(os.path.expanduser("~/.starlove_agent_key")).read().strip()
HDR = {"x-agent-key": KEY, "Content-Type": "application/json",
       "User-Agent": "Mozilla/5.0 (ContentDeskPoller)"}
CURSOR = os.path.join(WS, "memory", ".content-desk-cursor")
SCHEDULE = os.path.join(WS, "memory", "content-desk-schedule.jsonl")


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=30) as r:
        return json.load(r)


def _post(url, data):
    req = urllib.request.Request(url, data=json.dumps(data).encode(), headers=HDR, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def result(item_id, status, url=None, error=None):
    try:
        _post(f"{WORKER}/desk/result", {"id": item_id, "status": status, "url": url, "error": error})
    except Exception as e:
        print("result post failed:", e, flush=True)


def save_body(item_id, body):
    path = os.path.join(OFFICE, item_id)
    s = open(path, encoding="utf-8", errors="replace").read()
    if "## POST BODY" in s:
        s = re.sub(r"(## POST BODY\s*\n).*", r"\1" + body.replace("\\", "\\\\") + "\n", s, flags=re.DOTALL)
    else:
        s += "\n\n## POST BODY\n" + body + "\n"
    open(path, "w", encoding="utf-8").write(s)


def publish(item_id, body=None, media=None):
    path = os.path.join(OFFICE, item_id)
    if not os.path.isfile(path):
        return result(item_id, "error", error="draft file missing (already published?)")
    try:
        if body:
            save_body(item_id, body)
        cmd = ["python3", "scripts/publish_draft.py", "--file", path, "--execute"]
        if media:
            cmd += ["--media", ",".join(media)]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600, cwd=WS)
        m = re.search(r"POSTED: (\S+)", out.stdout)
        if m:
            result(item_id, "published", url=m.group(1))
            print(f"published {item_id} -> {m.group(1)}", flush=True)
        else:
            err = (out.stdout + out.stderr).strip()[-400:]
            result(item_id, "error", error=err)
            print(f"publish FAILED {item_id}: {err}", flush=True)
    except Exception as e:
        result(item_id, "error", error=str(e)[:400])


MEDIA_INBOX = os.path.join(os.path.dirname(OFFICE.rstrip("/")), "MEDIA_INBOX")


def trash_media(name):
    """Soft-delete an inbox file (move to MEDIA_INBOX/trash/)."""
    if not name:
        return
    src = os.path.join(MEDIA_INBOX, os.path.basename(name))
    if os.path.isfile(src):
        import shutil
        trash = os.path.join(MEDIA_INBOX, "trash")
        os.makedirs(trash, exist_ok=True)
        shutil.move(src, os.path.join(trash, os.path.basename(name)))
        print(f"trashed media: {name}", flush=True)
    subprocess.run(["python3", "scripts/content_desk_sync.py"], capture_output=True, timeout=60, cwd=WS)


def drain_schedule():
    if not os.path.isfile(SCHEDULE):
        return
    try:
        rows = [json.loads(l) for l in open(SCHEDULE) if l.strip()]
    except Exception:
        return
    now = time.time() * 1000
    due = [r for r in rows if not r.get("done") and r.get("when") and r["when"] <= now]
    if not due:
        return
    for r in due:
        print(f"schedule due: {r['id']}", flush=True)
        publish(r["id"], r.get("body"), r.get("media"))
        r["done"] = True
    with open(SCHEDULE, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def cancel_scheduled(item_id):
    """Mark all pending schedule rows for this draft as superseded."""
    if not os.path.isfile(SCHEDULE):
        return 0
    try:
        rows = [json.loads(l) for l in open(SCHEDULE) if l.strip()]
    except Exception:
        return 0
    n = 0
    for r in rows:
        if r.get("id") == item_id and not r.get("done"):
            r["done"] = "superseded"
            n += 1
    with open(SCHEDULE, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return n


def main():
    try:
        since = int(open(CURSOR).read().strip())
    except Exception:
        since = -1
        # prime to tip so a fresh install never replays old actions
        try:
            items = _get(f"{WORKER}/desk/actions?since=-1").get("items", [])
            if items:
                since = max(a["seq"] for a in items)
        except Exception:
            pass
    print(f"content-desk-poller started (cursor {since})", flush=True)
    while True:
        try:
            for a in _get(f"{WORKER}/desk/actions?since={since}").get("items", []):
                since = max(since, a["seq"])
                open(CURSOR, "w").write(str(since))
                act, item_id = a.get("action"), a.get("id")
                if act == "resync":
                    subprocess.run(["python3", "scripts/content_desk_sync.py"],
                                   capture_output=True, timeout=60, cwd=WS)
                    print("resynced drafts + media inbox", flush=True)
                elif act == "fetch_media":
                    pass  # assembled by the host Mac's media_fetcher (better network, native media folder)
                elif act == "delete_media":
                    trash_media(a.get("name"))
                elif act == "save_edit" and a.get("body"):
                    try:
                        save_body(item_id, a["body"])
                        result(item_id, "edited")
                        print(f"edited {item_id}", flush=True)
                    except Exception as e:
                        result(item_id, "error", error=str(e)[:300])
                elif act == "publish":
                    cancel_scheduled(item_id)  # post-now overrides any pending schedule
                    publish(item_id, a.get("body"), a.get("media"))
                elif act == "unschedule":
                    n = cancel_scheduled(item_id)
                    print(f"unscheduled {item_id} ({n} rows)", flush=True)
                elif act == "schedule":
                    cancel_scheduled(item_id)  # a new time replaces the old one
                    with open(SCHEDULE, "a") as f:
                        f.write(json.dumps({"id": item_id, "when": a.get("when"),
                                            "body": a.get("body"), "media": a.get("media"),
                                            "done": False}) + "\n")
                    print(f"scheduled {item_id} for {a.get('when')}", flush=True)
            drain_schedule()
        except Exception as e:
            print("loop error:", e, flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
