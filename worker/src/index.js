/* Content Desk stage worker.
   One Durable Object holds the draft deck, review-action queue, chunked media relay,
   ops timeline, and an agent chat relay — strongly consistent, no KV write-rate limits.
   Secrets: AGENT_KEY (pollers/bridges), OPS_KEY (optional write-only ops logging),
   DESK_PASS (operator passphrase for the browser UI — set it or the UI routes fall
   back to origin-gating only). Edit OK_ORIGIN to your domain. */

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};
const json = (o, s) => new Response(JSON.stringify(o), { status: s || 200, headers: { ...CORS, "Content-Type": "application/json" } });

export default {
  async fetch(req, env) {
    if (req.method === "OPTIONS") return new Response(null, { headers: CORS });
    return env.STAGE.get(env.STAGE.idFromName("live")).fetch(req);
  },
};

const OK_ORIGIN = (req) => {
  const o = req.headers.get("origin") || req.headers.get("referer") || "";
  return /(^|\/\/)(yourdomain\.com|[a-z0-9-]+\.pages\.dev|localhost(:\d+)?)/i.test(o);
};

export class Stage {
  constructor(state, env) {
    this.state = state; this.env = env; this.seq = 0; this.recent = []; this.featured = "";
    this.agSeq = 0; this.agIn = []; this.agOut = [];   // agent chat relay: inbound (→content box) / outbound (→UI)
    this.opsSeq = 0; this.opsLog = [];                 // ops log (backoffice timeline)
    this.deskItems = {}; this.deskActSeq = 0; this.deskActions = []; this.deskMedia = [];  // content desk (drafts + review actions + media inbox)
    state.blockConcurrencyWhile(async () => {
      this.seq = (await state.storage.get("seq")) || 0;
      this.recent = (await state.storage.get("recent")) || [];
      this.featured = (await state.storage.get("featured")) || "";
      this.agSeq = (await state.storage.get("agSeq")) || 0;
      this.agIn = (await state.storage.get("agIn")) || [];
      this.agOut = (await state.storage.get("agOut")) || [];
      this.opsSeq = (await state.storage.get("opsSeq")) || 0;
      this.opsLog = (await state.storage.get("opsLog")) || [];
      this.deskItems = (await state.storage.get("deskItems")) || {};
      this.deskActSeq = (await state.storage.get("deskActSeq")) || 0;
      this.deskActions = (await state.storage.get("deskActions")) || [];
      this.deskMedia = (await state.storage.get("deskMedia")) || [];
    });
  }
  okKey(req) { return this.env.AGENT_KEY && req.headers.get("x-agent-key") === this.env.AGENT_KEY; }
  // ops-only key: lets external tools log work without agent-relay access
  okOpsKey(req) { return this.okKey(req) || (this.env.OPS_KEY && req.headers.get("x-agent-key") === this.env.OPS_KEY); }
  // operator passphrase for the browser UIs. Until the DESK_PASS secret is set,
  // this is permissive (origin-gate only) for back-compat.
  okPass(req) { return !this.env.DESK_PASS || req.headers.get("x-desk-pass") === this.env.DESK_PASS || this.okKey(req); }
  async fetch(req) {
    const url = new URL(req.url);

    /* ---- ops log (dispatchers/watchers → backoffice timeline) ---- */
    // pipeline tools → append an event (needs key)
    if (url.pathname.endsWith("/ops/log") && req.method === "POST") {
      if (!this.okOpsKey(req)) return json({ error: "forbidden" }, 403);
      const b = await req.json().catch(() => ({}));
      this.opsSeq++;
      this.opsLog.push({
        seq: this.opsSeq, t: Date.now(),
        job: (b.job || "").toString().slice(0, 80),
        actor: (b.actor || "").toString().slice(0, 40),
        action: (b.action || "").toString().slice(0, 40),
        detail: (b.detail || "").toString().slice(0, 2000),
      });
      if (this.opsLog.length > 300) this.opsLog = this.opsLog.slice(-300);
      await this.state.storage.put("opsSeq", this.opsSeq);
      await this.state.storage.put("opsLog", this.opsLog);
      return json({ seq: this.opsSeq });
    }
    // backoffice → read the timeline
    if (url.pathname.endsWith("/ops/feed")) {
      if (!OK_ORIGIN(req) || !this.okPass(req)) return json({ error: "forbidden" }, 403);
      const since = parseInt(url.searchParams.get("since") || "-1", 10);
      const items = this.opsLog.filter((e) => e.seq > since);
      return json({ seq: this.opsSeq, items });
    }

    /* ---- content desk (draft review deck) ---- */
    // content box pushes the day's parsed drafts (+ the MEDIA_INBOX file list)
    if (url.pathname.endsWith("/desk/sync") && req.method === "POST") {
      if (!this.okKey(req)) return json({ error: "forbidden" }, 403);
      const b = await req.json().catch(() => ({}));
      if (Array.isArray(b.media_files)) {
        this.deskMedia = b.media_files.slice(0, 60);
        await this.state.storage.put("deskMedia", this.deskMedia);
      }
      const items = Array.isArray(b.items) ? b.items.slice(0, 40) : [];
      for (const it of items) {
        if (!it.id) continue;
        const prev = this.deskItems[it.id];
        this.deskItems[it.id] = { ...it, status: prev ? prev.status : "new", result: prev ? prev.result : null };
      }
      const ids = Object.keys(this.deskItems);
      if (ids.length > 60) {
        ids.sort((a, b) => (this.deskItems[a].t || 0) - (this.deskItems[b].t || 0));
        for (const id of ids.slice(0, ids.length - 60)) delete this.deskItems[id];
      }
      await this.state.storage.put("deskItems", this.deskItems);
      return json({ ok: true, count: Object.keys(this.deskItems).length });
    }
    // UI → the deck (+ media inbox listing)
    if (url.pathname.endsWith("/desk/list")) {
      if (!OK_ORIGIN(req) || !this.okPass(req)) return json({ error: "forbidden" }, 403);
      const items = Object.values(this.deskItems).sort((a, b) => (b.t || 0) - (a.t || 0));
      return json({ items, media: this.deskMedia });
    }
    // UI → queue a review action
    if (url.pathname.endsWith("/desk/action") && req.method === "POST") {
      if (!OK_ORIGIN(req) || !this.okPass(req)) return json({ error: "forbidden" }, 403);
      const b = await req.json().catch(() => ({}));
      const queueAction = async (extra) => {
        this.deskActSeq++;
        this.deskActions.push(Object.assign({ seq: this.deskActSeq, t: Date.now() }, extra));
        if (this.deskActions.length > 100) this.deskActions = this.deskActions.slice(-100);
        await this.state.storage.put("deskActSeq", this.deskActSeq);
        await this.state.storage.put("deskActions", this.deskActions);
      };
      if (b.action === "resync") {   // no item needed — ask the content box to re-scan drafts + media inbox
        await queueAction({ id: null, action: "resync" });
        return json({ ok: true });
      }
      if (b.action === "delete_media") {   // move an inbox file to trash on the content box
        if (!b.name) return json({ error: "no name" }, 400);
        await queueAction({ id: null, action: "delete_media", name: String(b.name).slice(0, 120) });
        this.deskMedia = this.deskMedia.filter((m) => m.name !== b.name);
        await this.state.storage.put("deskMedia", this.deskMedia);
        return json({ ok: true });
      }
      const ok = ["publish", "schedule", "skip", "unskip", "save_edit", "set_media", "unschedule"];
      if (!b.id || !ok.includes(b.action) || !this.deskItems[b.id]) return json({ error: "bad action" }, 400);
      const it = this.deskItems[b.id];
      if (Array.isArray(b.media)) it.media = b.media.slice(0, 4).map(String);
      if (typeof b.body === "string" && b.body.trim()) it.body = b.body.slice(0, 25000);
      if (b.action === "publish") it.status = "queued";
      else if (b.action === "schedule") { it.status = "scheduled"; it.when = b.when || null; }
      else if (b.action === "skip") it.status = "skipped";
      else if (b.action === "unskip") it.status = "new";
      else if (b.action === "save_edit" || b.action === "set_media") { if (it.status !== "scheduled") it.status = "edited"; }
      else if (b.action === "unschedule") { it.status = "edited"; it.when = null; }
      if (!["unskip", "skip", "set_media"].includes(b.action)) {
        await queueAction({ id: b.id, action: b.action,
          body: b.body ? b.body.slice(0, 25000) : null, when: b.when || null,
          media: it.media || null });
      }
      await this.state.storage.put("deskItems", this.deskItems);
      return json({ ok: true, status: it.status });
    }
    // browser → upload a media file in base64 chunks (relayed to the MEDIA_INBOX)
    if (url.pathname.endsWith("/desk/upload") && req.method === "POST") {
      if (!OK_ORIGIN(req) || !this.okPass(req)) return json({ error: "forbidden" }, 403);
      const b = await req.json().catch(() => ({}));
      const raw = String(b.name || "").replace(/[^\w.\- ]/g, "_");
      const dot = raw.lastIndexOf(".");
      const ext = dot > 0 ? raw.slice(dot).slice(0, 8) : "";
      const base = (dot > 0 ? raw.slice(0, dot) : raw).slice(0, Math.max(1, 96 - ext.length)).replace(/\.+$/, "");
      const name = base + ext;  // truncate the base, never the extension — and never double it
      const seq = parseInt(b.seq, 10), total = parseInt(b.total, 10);
      if (!name || !(seq >= 0) || !(total > 0) || total > 450 || typeof b.data !== "string" || b.data.length > 110000)
        return json({ error: "bad chunk" }, 400);
      await this.state.storage.put(`up:${name}:${seq}`, b.data);
      if (seq === total - 1) {
        this.deskActSeq++;
        this.deskActions.push({ seq: this.deskActSeq, id: null, action: "fetch_media",
          name, total, t: Date.now() });
        if (this.deskActions.length > 100) this.deskActions = this.deskActions.slice(-100);
        await this.state.storage.put("deskActSeq", this.deskActSeq);
        await this.state.storage.put("deskActions", this.deskActions);
      }
      return json({ ok: true, seq });
    }
    // media fetcher → read one uploaded chunk
    if (url.pathname.endsWith("/desk/file")) {
      if (!this.okKey(req)) return json({ error: "forbidden" }, 403);
      const name = url.searchParams.get("name"), seq = url.searchParams.get("seq");
      const data = await this.state.storage.get(`up:${name}:${seq}`);
      return json({ data: data || null });
    }
    // media fetcher → uploaded file landed; clear the chunks
    if (url.pathname.endsWith("/desk/file_done") && req.method === "POST") {
      if (!this.okKey(req)) return json({ error: "forbidden" }, 403);
      const b = await req.json().catch(() => ({}));
      const total = parseInt(b.total, 10) || 0;
      for (let i = 0; i < total; i++) await this.state.storage.delete(`up:${b.name}:${i}`);
      return json({ ok: true });
    }
    // pollers → pull queued actions
    if (url.pathname.endsWith("/desk/actions")) {
      if (!this.okKey(req)) return json({ error: "forbidden" }, 403);
      const since = parseInt(url.searchParams.get("since") || "-1", 10);
      return json({ items: this.deskActions.filter((a) => a.seq > since) });
    }
    // pollers → report execution result
    if (url.pathname.endsWith("/desk/result") && req.method === "POST") {
      if (!this.okKey(req)) return json({ error: "forbidden" }, 403);
      const b = await req.json().catch(() => ({}));
      const it = b.id && this.deskItems[b.id];
      if (it) {
        it.status = b.status || it.status;
        it.result = { url: b.url || null, error: b.error || null, t: Date.now() };
        await this.state.storage.put("deskItems", this.deskItems);
      }
      return json({ ok: true });
    }

    // bridges → merged recent conversation (operator + all agents), for group-chat context
    if (url.pathname.endsWith("/agent/transcript")) {
      if (!this.okKey(req)) return json({ error: "forbidden" }, 403);
      const convo = url.searchParams.get("convo") || "backoffice";
      const limit = Math.min(parseInt(url.searchParams.get("limit") || "20", 10), 60);
      const merged = [
        ...this.agIn.filter((m) => m.convo === convo).map((m) => ({ seq: m.seq, t: m.t, from: "operator", to: m.agent, text: m.text })),
        ...this.agOut.filter((m) => m.convo === convo).map((m) => ({ seq: m.seq, t: m.t, from: m.agent, text: m.text })),
      ].sort((a, b) => a.seq - b.seq);
      // fan-out sends duplicate the operator's text once per recipient — collapse them
      const out = [];
      for (const m of merged) {
        const prev = out[out.length - 1];
        if (prev && prev.from === "operator" && m.from === "operator" && prev.text === m.text) continue;
        out.push(m);
      }
      return json({ items: out.slice(-limit) });
    }

    /* ---- agent chat relay (UI ⇄ content box agent bridge) ---- */
    // UI → queue a message for an agent
    if (url.pathname.endsWith("/agent/send") && req.method === "POST") {
      if (!OK_ORIGIN(req) || !this.okPass(req)) return json({ error: "forbidden" }, 403);
      const b = await req.json().catch(() => ({}));
      const text = (b.text || "").toString().slice(0, 4000);
      const agent = (b.agent || "wizard").toString();
      const convo = (b.convo || "backstage").toString();
      if (!text) return json({ error: "no text" }, 400);
      this.agSeq++;
      this.agIn.push({ seq: this.agSeq, agent, convo, text, t: Date.now() });
      if (this.agIn.length > 100) this.agIn = this.agIn.slice(-100);
      await this.state.storage.put("agSeq", this.agSeq);
      await this.state.storage.put("agIn", this.agIn);
      return json({ seq: this.agSeq });
    }
    // bridge → pull queued messages (needs key)
    if (url.pathname.endsWith("/agent/pull")) {
      if (!this.okKey(req)) return json({ error: "forbidden" }, 403);
      const since = parseInt(url.searchParams.get("since") || "-1", 10);
      const agent = url.searchParams.get("agent");
      const items = this.agIn.filter((m) => m.seq > since && (!agent || m.agent === agent));
      return json({ items });
    }
    // bridge → post a reply (needs key)
    if (url.pathname.endsWith("/agent/reply") && req.method === "POST") {
      if (!this.okKey(req)) return json({ error: "forbidden" }, 403);
      const b = await req.json().catch(() => ({}));
      this.agSeq++;
      this.agOut.push({ seq: this.agSeq, agent: (b.agent || "wizard").toString(), convo: (b.convo || "backstage").toString(),
        text: (b.text || "").toString(), replyTo: b.replyTo || null, t: Date.now() });
      if (this.agOut.length > 100) this.agOut = this.agOut.slice(-100);
      await this.state.storage.put("agSeq", this.agSeq);
      await this.state.storage.put("agOut", this.agOut);
      return json({ seq: this.agSeq });
    }
    // UI → poll for replies
    if (url.pathname.endsWith("/agent/replies")) {
      if (!OK_ORIGIN(req) || !this.okPass(req)) return json({ error: "forbidden" }, 403);
      const since = parseInt(url.searchParams.get("since") || "-1", 10);
      const convo = url.searchParams.get("convo");
      const items = this.agOut.filter((m) => m.seq > since && (!convo || m.convo === convo));
      return json({ seq: this.agSeq, items });
    }

    if (url.pathname.endsWith("/poll")) {
      const since = parseInt(url.searchParams.get("since") || "-1", 10);
      const items = this.recent.filter((r) => r.seq > since);
      return json({ seq: this.seq, items });
    }

    if (url.pathname.endsWith("/command") && req.method === "POST") {
      const origin = req.headers.get("origin") || req.headers.get("referer") || "";
      if (!/(^|\/\/)(yourdomain\.com|[a-z0-9-]+\.pages\.dev|localhost(:\d+)?)/i.test(origin))
        return json({ error: "forbidden" }, 403);
      const body = await req.json().catch(() => ({}));
      if (!body.cmd) return json({ error: "no cmd" }, 400);
      this.seq++;
      this.recent.push({ seq: this.seq, cmd: body });
      if (this.recent.length > 80) this.recent = this.recent.slice(-80);
      await this.state.storage.put("seq", this.seq);
      await this.state.storage.put("recent", this.recent);
      return json({ seq: this.seq });
    }

    if (url.pathname.endsWith("/featured")) {
      if (req.method === "POST") {
        const origin = req.headers.get("origin") || req.headers.get("referer") || "";
        if (!/(^|\/\/)(yourdomain\.com|[a-z0-9-]+\.pages\.dev|localhost(:\d+)?)/i.test(origin))
          return json({ error: "forbidden" }, 403);
        const b = await req.json().catch(() => ({}));
        this.featured = (b.file || "").toString();
        await this.state.storage.put("featured", this.featured);
        return json({ featured: this.featured });
      }
      return json({ featured: this.featured || "" });
    }

    return json({ ok: true, seq: this.seq });
  }
}
