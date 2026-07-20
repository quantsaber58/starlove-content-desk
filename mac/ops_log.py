#!/usr/bin/env python3
"""
Shared helper: post pipeline events to the stage worker's /ops/log
(displayed on the backoffice timeline). Stdlib only. Never raises —
an ops-log outage must not break a dispatch.
Expects a .env beside this file: STAGE_AGENT_KEY=... STAGE_WORKER_URL=...
"""
import json
import os
import urllib.request

HOME = os.path.dirname(os.path.abspath(__file__))


def _env():
    env = {}
    with open(os.path.join(HOME, ".env")) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def ops_event(job, actor, action, detail=""):
    """Fire-and-forget event. Returns True on success, False otherwise."""
    try:
        env = _env()
        url = env.get("STAGE_WORKER_URL", "").rstrip("/")
        key = env.get("STAGE_AGENT_KEY", "")
        if not url or not key:
            return False
        data = json.dumps(
            {"job": job, "actor": actor, "action": action, "detail": detail[:2000]}
        ).encode()
        req = urllib.request.Request(
            f"{url}/ops/log", data=data,
            headers={
                "Content-Type": "application/json",
                "x-agent-key": key,
                "User-Agent": "Mozilla/5.0 (starlove-ops)",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            return bool(json.load(r).get("seq"))
    except Exception:
        return False
