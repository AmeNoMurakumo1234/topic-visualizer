#!/usr/bin/env python3
"""Topic Visualizer MCP face - the AI-side half of the seam, as first-class tools.

One stdio MCP server (newline-delimited JSON-RPC 2.0), TWO storage backends behind
the same six tools - the adapter law, server-side:

  TOPICS_BACKEND=server  (default)  -> HTTP passthrough to the plugin's own
                                       server.py (TOPICS_SERVER_URL, :8991)
  TOPICS_BACKEND=board               -> topics live as message-board posts with the
                                       "OPEN THREAD" title convention
                                       (TOPICS_BOARD_URL, :9772 + TOPICS_BOARD_PROJECT)

The board backend imports the store-agnostic ranking brains (near_duplicates_in,
search_in, rank_candidates) from server.py, so BOTH stores get identical dedup,
semantic search, and serve ranking. Board topic_convert(kind=work_item) creates a
REAL board issue and resolves the thread with a pointer - the EXPLORING -> ACTING
crossing made atomic (the hard ontological line, CHARTER discipline 6).

Zero heavy deps: stdlib only. Register via the plugin's .mcp.json.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# ranking brains only; server.py opens no DB and starts nothing at import time
from server import near_duplicates_in, search_in, rank_candidates  # noqa: E402

ACTOR = os.environ.get("TOPICS_ACTOR", "ai")


class Unreachable(Exception):
    """The target server is not running (connection-level failure, not an app error)."""


def _http(method: str, url: str, body: dict | None = None,
          headers: dict | None = None) -> dict:
    hdrs = {"Content-Type": "application/json"}
    hdrs.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return {"error": f"HTTP {e.code}", "detail": json.loads(e.read() or b"{}")}
        except Exception:
            return {"error": f"HTTP {e.code}"}
    except Exception as e:
        raise Unreachable(str(e)) from e


# ------------------------------------------------------- server backend ----
class ServerBackend:
    """HTTP passthrough to the plugin server when it is running; DIRECT in-process
    sqlite otherwise (same functions the server itself calls). Zero-setup: capture
    works before anyone has started a server - the web views are the only surface
    that needs the HTTP process."""

    def __init__(self):
        self.base = os.environ.get("TOPICS_SERVER_URL", "http://127.0.0.1:8991").rstrip("/")
        self._direct = None

    def _fallback(self):
        if self._direct is None:
            import server as srv
            db = os.environ.get("TOPICS_DB") or str(HERE / "topics.db")
            Path(db).parent.mkdir(parents=True, exist_ok=True)
            srv._conn = srv.open_db(db)
            srv.DB_PATH = db
            srv.expire_seedlings()
            self._direct = srv
        return self._direct

    def add(self, items):
        try:
            return _http("POST", f"{self.base}/api/topics",
                         {"topics": items, "actor": ACTOR})
        except Unreachable:
            return {"results": self._fallback().add_topics(items, ACTOR)}

    def serve(self, context):
        from urllib.parse import quote
        try:
            return _http("GET", f"{self.base}/api/topics/serve?context={quote(context)}")
        except Unreachable:
            return self._fallback().serve_card(context)

    def search(self, query):
        from urllib.parse import quote
        try:
            return _http("GET", f"{self.base}/api/topics/search?q={quote(query)}")
        except Unreachable:
            return {"results": self._fallback().search(query)}

    def state(self, slug, state, note):
        try:
            return _http("POST", f"{self.base}/api/topics/{slug}/state",
                         {"state": state, "actor": ACTOR, "note": note})
        except Unreachable:
            return self._fallback().set_state(slug, state, ACTOR, note)

    def convert(self, slug, kind, ref, note):
        try:
            return _http("POST", f"{self.base}/api/topics/{slug}/links",
                         {"links": [{"kind": kind, "ref": ref, "note": note}],
                          "actor": ACTOR, "note": note})
        except Unreachable:
            return self._fallback().convert(
                slug, [{"kind": kind, "ref": ref, "note": note}], ACTOR, note)

    def attach(self, slug, parent_slug, note, remove=False):
        try:
            return _http("POST", f"{self.base}/api/topics/{slug}/attach",
                         {"parent_slug": parent_slug, "actor": ACTOR,
                          "note": note, "remove": remove})
        except Unreachable:
            return self._fallback().attach_parent(slug, parent_slug, ACTOR, note, remove)

    def groom(self):
        try:
            return _http("GET", f"{self.base}/api/topics/groom")
        except Unreachable:
            return self._fallback().groom_report()


# -------------------------------------------------------- board backend ----
class BoardBackend:
    """Topics as message-board posts (title prefix "OPEN THREAD", body lines
    "parent: <slug>" / "stage: seedling" / "priority: critical"). States map onto
    post resolutions: discussed = resolve kind completed, pruned = discarded.
    Mirrors static/topics/adapter-board.js - change conventions in BOTH."""

    PREFIX = "OPEN THREAD"

    def __init__(self):
        self.base = os.environ.get("TOPICS_BOARD_URL",
                                   os.environ.get("MESSAGEBOARD_URL",
                                                  "http://127.0.0.1:9772")).rstrip("/")
        self.project = os.environ.get("TOPICS_BOARD_PROJECT", "quantum-concepts")
        self.author = os.environ.get("TOPICS_BOARD_AUTHOR", "Joule")
        # the board's anti-CSRF check requires this exact value (its own app name)
        self.hdrs = {"X-Requested-By": "messageboard"}

    def _load(self):
        import re as _re
        resp = _http("GET", f"{self.base}/api/posts?project={self.project}")
        topics = []
        for p in resp.get("items", []):
            title = p.get("title") or ""
            if not title.upper().startswith(self.PREFIX):
                continue
            if (p.get("resolve_kind") or "") == "discarded":
                continue
            body = p.get("body") or ""
            # MULTI-PARENT: every "parent:" body line counts - first is the primary
            # (layout spine), the rest are extra avenues into the same topic
            parents = _re.findall(r"^parent:\s*([a-z0-9-]+)", body, _re.M | _re.I)
            extra = [{"slug": s, "note": ""} for s in parents[1:]]
            # rediscoveries attach as thread replies ("also-parent: <slug> | <note>")
            # because post bodies are immutable through the board API; only posts
            # with replies pay the extra fetch
            if p.get("message_count"):
                full = _http("GET", f"{self.base}/api/post?slug={p['slug']}")
                for th in full.get("threads", []):
                    for msg in th.get("messages", []):
                        for mm in _re.finditer(
                                r"^also-parent:\s*([a-z0-9-]+)\s*(?:\|\s*(.*))?$",
                                msg.get("body") or "", _re.M | _re.I):
                            extra.append({"slug": mm.group(1),
                                          "note": (mm.group(2) or "").strip()})
            state = ("discussed" if str(p.get("status") or "open") != "open"
                     else ("seedling" if _re.search(r"^stage:\s*seedling", body, _re.M | _re.I)
                           else "open"))
            topics.append({
                "slug": p["slug"],
                "title": _re.sub(r"^OPEN THREAD:?\s*", "", title, flags=_re.I),
                "body": body, "state": state,
                "parent_slug": parents[0] if parents else None,
                "extra_parents": extra,
                "priority": ("critical"
                             if _re.search(r"^priority:\s*critical", body, _re.M | _re.I)
                             else "normal"),
                # board timestamps are ISO-with-T; rank_candidates parses "Y-m-d H:M:S"
                "touched_at": (p.get("created") or "").replace("T", " ")[:19],
                "created_at": (p.get("created") or "").replace("T", " ")[:19],
            })
        return topics

    def attach(self, slug, parent_slug, note, remove=False):
        """Rediscovery on the board: an "also-parent" reply in the topic's thread (post
        bodies are immutable through the API; the thread IS the discovery log)."""
        if remove:
            return {"error": "the board backend cannot detach an avenue "
                             "(replies are append-only; reply a correction instead)"}
        topics = {t["slug"]: t for t in self._load()}
        t, p = topics.get(slug), topics.get(parent_slug)
        if not t or not p:
            return {"error": "topic or parent not found"}
        if t["parent_slug"] == parent_slug or any(
                x["slug"] == parent_slug for x in t["extra_parents"]):
            return {"error": "already attached to that parent"}
        # cycle guard over the loaded DAG: no ancestor path from the new parent
        # may reach this topic
        frontier, seen = [parent_slug], set()
        while frontier:
            cur = frontier.pop()
            if cur == slug:
                return {"error": "cycle: that parent is inside this topic's subtree"}
            if cur in seen or cur not in topics:
                continue
            seen.add(cur)
            c = topics[cur]
            if c["parent_slug"]:
                frontier.append(c["parent_slug"])
            frontier += [x["slug"] for x in c["extra_parents"]]
        r = _http("POST", f"{self.base}/api/reply",
                  {"slug": slug, "author": self.author,
                   "body": f"also-parent: {parent_slug}"
                           + (f" | {note}" if note else "")}, self.hdrs)
        if r.get("error"):
            return {"error": "reply failed", "detail": r}
        return {"ok": True, "attached": parent_slug}

    def add(self, items):
        existing = self._load()
        results = []
        for it in items:
            title = str(it.get("title") or "").strip()
            if not title:
                results.append({"error": "title required"})
                continue
            dups = near_duplicates_in(title, str(it.get("body") or ""), existing)
            lines = []
            if it.get("parent_slug"):
                lines.append(f"parent: {it['parent_slug']}")
            # parity with the sqlite store: captures default to SEEDLING unless
            # explicitly planted open (the capture skill promises this)
            if it.get("state", "seedling") == "seedling":
                lines.append("stage: seedling")
            if it.get("priority") == "critical":
                lines.append("priority: critical")
            body = ("\n".join(lines) + "\n\n" if lines else "") + \
                   str(it.get("body") or "captured via the topics MCP tools")
            r = _http("POST", f"{self.base}/api/post",
                      {"project": self.project, "author": self.author,
                       "type": "proposal", "to": self.author,
                       "title": f"{self.PREFIX}: {title}"[:200], "body": body},
                      self.hdrs)
            item = {"slug": r.get("slug"), "near_duplicates": dups}
            if r.get("error"):
                item["error"] = r["error"]
            results.append(item)
        return {"results": results}

    def serve(self, context):
        cands = rank_candidates(self._load(), context)
        if not cands:
            return {"card": None, "note": "no open topics"}
        top = [{"slug": t["slug"], "title": t["title"], "state": t["state"],
                "priority": t["priority"], "score": round(s, 2)}
               for s, t in cands[:3]]
        return {"card": top[0], "alternates": top[1:]}

    def search(self, query):
        return {"results": search_in(query, self._load())}

    def state(self, slug, state, note):
        if state == "open":
            return _http("POST", f"{self.base}/api/reopen",
                         {"slug": slug, "author": self.author}, self.hdrs)
        kind = "discarded" if state == "pruned" else "completed"
        return _http("POST", f"{self.base}/api/post/resolve",
                     {"slug": slug, "author": self.author, "kind": kind,
                      "note": note or state}, self.hdrs)

    def convert(self, slug, kind, ref, note):
        """The full lifecycle on the board: a work_item conversion with no ref MINTS
        a real board issue from the topic, then resolves the thread pointing at it."""
        created = None
        if kind == "work_item" and not ref:
            topic = next((t for t in self._load() if t["slug"] == slug), None)
            if not topic:
                return {"error": "topic not found"}
            r = _http("POST", f"{self.base}/api/issue/create",
                      {"project": self.project, "title": topic["title"][:200],
                       "description": (note or topic["body"][:1000])
                       + f"\n\n(converted from topic thread {slug})",
                       "priority": "P2", "author": self.author}, self.hdrs)
            ref = r.get("slug") or ""
            created = r if not ref else {"issue": ref}
            if not ref:
                return {"error": "issue create failed", "detail": r}
        # the resolve can fail AFTER the issue was minted - report honestly so a
        # blind retry never mints a duplicate issue (audit MED-5)
        try:
            res = self.state(slug, "discussed", f"converted -> {kind}: {ref}"
                             + (f" | {note}" if note else ""))
        except Unreachable as e:
            return {"error": f"issue minted but the thread resolve failed: {e}. "
                             "Do NOT retry the convert - resolve the thread manually.",
                    "created": created, "ref": ref}
        if isinstance(res, dict) and res.get("error"):
            return {"error": "issue minted but the thread resolve failed",
                    "created": created, "ref": ref, "resolve": res}
        return {"ok": True, "kind": kind, "ref": ref, "created": created,
                "resolve": res}

    def groom(self):
        topics = self._load()
        by_state: dict = {}
        for t in topics:
            by_state[t["state"]] = by_state.get(t["state"], 0) + 1
        beacons = sum(1 for t in topics if t["priority"] == "critical")
        live = by_state.get("open", 0) + by_state.get("seedling", 0)
        return {"backend": "board", "project": self.project, "by_state": by_state,
                "beacons": beacons,
                "beacon_ratio_warn": bool(live and beacons / live > 0.10)}


_BACKEND = None


def _backend():
    """Singleton: a fresh backend per call would rebuild the direct-sqlite
    fallback's connection every time (leaking the previous one) and re-run the
    expiry job per tool call (audit MED-7)."""
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = (BoardBackend() if os.environ.get("TOPICS_BACKEND") == "board"
                    else ServerBackend())
    return _BACKEND


# ------------------------------------------------------------ MCP plumbing ----
TOOLS = [
    {"name": "topic_add",
     "description": (
         "Silently capture topic(s) into the shared thread tree - forks worth keeping "
         "that the conversation didn't take. Capture at the moment of the fork; do not "
         "ask permission, do not announce (report softly at session end). Near the "
         "context-compaction boundary, LOWER the threshold and sweep aggressively as "
         "seedlings (state='seedling') - an over-captured seedling costs ~nothing (it "
         "auto-expires); a lost idea is gone. Check near_duplicates in the result: if "
         "the topic already exists, do NOT plant a twin - use topic_attach to add this "
         "conversation's avenue as an extra parent (topics form a DAG, not a tree)."),
     "inputSchema": {"type": "object", "properties": {
         "items": {"type": "array", "items": {"type": "object", "properties": {
             "title": {"type": "string", "description": "short, glanceable (a node label)"},
             "body": {"type": "string", "description": "enough context to resume cold"},
             "parent_slug": {"type": "string", "description": "attach under this topic"},
             "priority": {"type": "string", "enum": ["normal", "critical"],
                          "description": "critical = beacon; RARE (<10% of live topics)"},
             "state": {"type": "string", "enum": ["open", "seedling"],
                       "description": "seedling = tentative capture, auto-expires untouched"},
         }, "required": ["title"]}}}, "required": ["items"]}},
    {"name": "topic_serve",
     "description": (
         "Get ONE topic card worth raising now (plus 2 alternates) - beacons first, "
         "then semantic fit to the given context, then oldest-important resurfacing. "
         "Default cadence: first session of the day. Serve the card conversationally; "
         "never dump a list."),
     "inputSchema": {"type": "object", "properties": {
         "context": {"type": "string",
                     "description": "what we're working on right now (for territory fit)"}}}},
    {"name": "topic_search",
     "description": "Ranked search over all topics (semantic when the local embedder is "
                    "up, keyword otherwise). Use before adding: the dup you merge into "
                    "is better than the twin you plant.",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}}, "required": ["query"]}},
    {"name": "topic_state",
     "description": "Move a topic: open (reopen), discussed (we actually talked it "
                    "through), pruned (dead branch; on the sqlite backend this cascades "
                    "to the live subtree). Touching any topic graduates a seedling.",
     "inputSchema": {"type": "object", "properties": {
         "slug": {"type": "string"},
         "state": {"type": "string", "enum": ["open", "discussed", "pruned"]},
         "note": {"type": "string"}}, "required": ["slug", "state"]}},
    {"name": "topic_convert",
     "description": (
         "The atomic crossing out of EXPLORING: record what a discussed topic became - "
         "decision | work_item | document - and mark it discussed in one act. On the "
         "board backend, kind=work_item with no ref CREATES a real board issue from the "
         "topic and links it. Never convert silently mid-conversation; do it at the "
         "moment the human ratifies."),
     "inputSchema": {"type": "object", "properties": {
         "slug": {"type": "string"},
         "kind": {"type": "string", "enum": ["decision", "work_item", "document"]},
         "ref": {"type": "string", "description": "existing artifact ref; empty on the "
                 "board work_item path mints a new issue"},
         "note": {"type": "string"}}, "required": ["slug", "kind"]}},
    {"name": "topic_attach",
     "description": (
         "The same semantic topic reached from ANOTHER conversational avenue: attach "
         "an existing topic under an additional parent (multi-parent DAG - one topic, "
         "many roads in, never a duplicated subtree). Records what the later "
         "discovery added (note) on the topic itself. Use this instead of topic_add "
         "when near_duplicates flags an existing match. Cycle-guarded. remove=true "
         "detaches an extra avenue (sqlite backend only)."),
     "inputSchema": {"type": "object", "properties": {
         "slug": {"type": "string", "description": "the existing topic"},
         "parent_slug": {"type": "string", "description": "the additional parent"},
         "note": {"type": "string",
                  "description": "what this avenue added - the rediscovery enrichment"},
         "remove": {"type": "boolean"}}, "required": ["slug", "parent_slug"]}},
    {"name": "topic_groom_report",
     "description": "Seam vital signs + capture calibration (expiry rates per actor "
                    "where available). Read during a grooming round; adjust your "
                    "capture threshold from the evidence.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _call(name: str, args: dict) -> dict:
    b = _backend()
    if name == "topic_add":
        return b.add(args.get("items") or [])
    if name == "topic_serve":
        return b.serve(str(args.get("context") or ""))
    if name == "topic_search":
        return b.search(str(args.get("query") or ""))
    if name == "topic_state":
        return b.state(args["slug"], args["state"], str(args.get("note") or ""))
    if name == "topic_convert":
        return b.convert(args["slug"], args["kind"], str(args.get("ref") or ""),
                         str(args.get("note") or ""))
    if name == "topic_attach":
        return b.attach(args["slug"], args["parent_slug"],
                        str(args.get("note") or ""), bool(args.get("remove")))
    if name == "topic_groom_report":
        return b.groom()
    return {"error": f"unknown tool {name!r}"}


def main() -> None:
    stdin = sys.stdin.buffer
    out = sys.stdout.buffer
    while True:
        line = stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except Exception:
            continue
        if not isinstance(msg, dict):
            continue          # a JSON array/scalar line must not kill the process
        mid = msg.get("id")
        method = msg.get("method") or ""
        resp: dict | None = None
        if method == "initialize":
            resp = {"protocolVersion": (msg.get("params") or {}).get(
                        "protocolVersion", "2024-11-05"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "topic-visualizer", "version": "0.4.1"}}
        elif method == "tools/list":
            resp = {"tools": TOOLS}
        elif method == "tools/call":
            p = msg.get("params") or {}
            try:
                result = _call(p.get("name") or "", p.get("arguments") or {})
                resp = {"content": [{"type": "text",
                                     "text": json.dumps(result, indent=1)}],
                        "isError": bool(isinstance(result, dict) and result.get("error"))}
            except Exception as e:
                resp = {"content": [{"type": "text", "text": f"error: {e}"}],
                        "isError": True}
        elif method == "ping":
            resp = {}
        elif mid is None:
            continue                      # notification - no response
        else:
            out.write((json.dumps({"jsonrpc": "2.0", "id": mid,
                                   "error": {"code": -32601,
                                             "message": f"unknown method {method}"}})
                       + "\n").encode())
            out.flush()
            continue
        if mid is not None:
            out.write((json.dumps({"jsonrpc": "2.0", "id": mid, "result": resp})
                       + "\n").encode())
            out.flush()


if __name__ == "__main__":
    main()
