#!/usr/bin/env python3
"""Topic Visualizer server - one small process, two faces over one SQLite store.

HTTP face: the web views (and anything else local). MCP face: exposed separately by
mcp_tools.py, which imports the same operations. Localhost only; zero heavy deps.

    python server.py [--db topics.db] [--port 8991] [--web ../web]

Design: docs/2026-07-11-seam-design.md. Schema: schema.sql (v2).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
SEEDLING_EXPIRY_DAYS = 21
BEACON_WARN_RATIO = 0.10

_lock = threading.Lock()      # single-writer discipline over the connection
_conn: sqlite3.Connection | None = None
DB_PATH = "topics.db"


# ---------------------------------------------------------------- store ----
def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    conn.commit()
    return conn


def _slugify(title: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "topic"
    slug, n = base, 1
    with _lock:
        while _conn.execute("SELECT 1 FROM topic WHERE slug=?", (slug,)).fetchone():
            n += 1
            slug = f"{base}-{n}"
    return slug


def _row_to_topic(r: sqlite3.Row, links: dict | None = None) -> dict:
    return {
        "id": r["id"], "slug": r["slug"], "title": r["title"], "body": r["body"],
        "parent_slug": r["parent_slug"] if "parent_slug" in r.keys() else None,
        "state": r["state"], "priority": r["priority"], "tags": r["tags"],
        "created_by": r["created_by"], "created_at": r["created_at"],
        "touched_at": r["touched_at"], "provenance": r["provenance"],
        "state_note": r["state_note"],
        "links": (links or {}).get(r["id"], []),
    }


def _load_topics(include_archive: bool = False) -> list[dict]:
    q = """SELECT t.*, p.slug AS parent_slug FROM topic t
           LEFT JOIN topic p ON p.id = t.parent_id"""
    if not include_archive:
        q += " WHERE t.state IN ('seedling','open','discussed')"
    with _lock:
        rows = _conn.execute(q).fetchall()
        link_rows = _conn.execute(
            "SELECT topic_id, kind, ref, note FROM topic_link").fetchall()
    links: dict = {}
    for lr in link_rows:
        links.setdefault(lr["topic_id"], []).append(
            {"kind": lr["kind"], "ref": lr["ref"], "note": lr["note"]})
    return [_row_to_topic(r, links) for r in rows]


def _event(topic_id: int, event: str, actor: str, note: str = "") -> None:
    _conn.execute(
        "INSERT INTO topic_event (topic_id, event, actor, note) VALUES (?,?,?,?)",
        (topic_id, event, actor, note))


def _touch(topic_id: int, actor: str, note: str = "") -> None:
    _conn.execute("UPDATE topic SET touched_at = datetime('now') WHERE id=?", (topic_id,))
    _event(topic_id, "touched", actor, note)
    # first touch graduates a seedling to a full topic (death-by-choice from here on)
    _conn.execute(
        "UPDATE topic SET state='open' WHERE id=? AND state='seedling'", (topic_id,))


# ------------------------------------------------------ embeddings ----
# Optional SEMANTIC ranking via any OpenAI-style /v1/embeddings endpoint (env
# TOPICS_EMBED_URL; default the local CPU embedding server). Graceful: when the
# endpoint is down or absent, every ranking falls back to keyword scoring.
import urllib.request

EMBED_URL = (os.environ.get("TOPICS_EMBED_URL", "http://127.0.0.1:8082")).rstrip("/")
_embed_up = None
_embed_cache = {}


def _embed(texts):
    global _embed_up
    if not EMBED_URL or _embed_up is False:
        return None
    todo = [x for x in texts if x not in _embed_cache]
    if todo:
        try:
            req = urllib.request.Request(
                EMBED_URL + "/v1/embeddings",
                data=json.dumps({"input": todo}).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())["data"]
            for txt, item in zip(todo, data):
                _embed_cache[txt] = item["embedding"]
            _embed_up = True
        except Exception:
            _embed_up = False
            return None
    return [_embed_cache[x] for x in texts]


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def semantic_rank(query, topics):
    """Cosine-rank topics against a query; None when the embedder is unavailable."""
    if not query or not topics:
        return None
    texts = [query] + [t["title"] + " " + t["body"][:400] for t in topics]
    vecs = _embed(texts)
    if vecs is None:
        return None
    qv = vecs[0]
    return sorted(((max(0.0, _cosine(qv, v)), t) for v, t in zip(vecs[1:], topics)),
                  key=lambda x: -x[0])


# ------------------------------------------------------ text ranking ----
_WORD = re.compile(r"[a-z0-9]{3,}")
_STOP = frozenset("the and for with that this from are was were should would could "
                  "does need what when how who our your their have has not but".split())


def _tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP]


def _score(query_toks: list[str], text: str) -> float:
    """Keyword fallback ranking (BM25-flavored: term overlap with length damping).
    The semantic embedder, when installed, replaces this - same signature."""
    toks = _tokens(text)
    if not toks or not query_toks:
        return 0.0
    tf = {}
    for t in toks:
        tf[t] = tf.get(t, 0) + 1
    hit = sum(math.sqrt(tf.get(q, 0)) for q in query_toks)
    return hit / math.sqrt(len(toks) + 8)


def near_duplicates_in(title, body, topics, limit=3):
    """Write-time dedup guard over a given topic list (store-agnostic; the MCP board
    backend reuses this). Semantic when the embedder is up, keyword otherwise."""
    ranked = semantic_rank(title + " " + body[:200], topics)
    out = []
    if ranked is not None:
        out = [{"slug": x["slug"], "title": x["title"], "score": round(s, 3)}
               for s, x in ranked if s > 0.62]
    else:
        q = _tokens(title + " " + body[:200])
        for x in topics:
            s = _score(q, x["title"] + " " + x["body"][:200])
            if s > 0.55:
                out.append({"slug": x["slug"], "title": x["title"], "score": round(s, 3)})
        out.sort(key=lambda y: -y["score"])
    return out[:limit]


def _near_duplicates(title: str, body: str, limit: int = 3) -> list[dict]:
    return near_duplicates_in(title, body, _load_topics(), limit)


# ------------------------------------------------------------ actions ----
def add_topics(items: list[dict], actor: str) -> list[dict]:
    """Batch capture. Each item: {title, body?, parent_slug?, priority?, tags?,
    provenance?, state?}. Returns per-item {slug, near_duplicates}."""
    results = []
    for it in items:
        title = str(it.get("title") or "").strip()
        if not title:
            results.append({"error": "title required"})
            continue
        dups = _near_duplicates(title, str(it.get("body") or ""))
        slug = _slugify(title)
        with _lock:
            parent_id = None
            if it.get("parent_slug"):
                row = _conn.execute("SELECT id FROM topic WHERE slug=?",
                                    (it["parent_slug"],)).fetchone()
                parent_id = row["id"] if row else None
            state = it.get("state") or "seedling"
            if state not in ("seedling", "open"):
                state = "seedling"
            cur = _conn.execute(
                """INSERT INTO topic (slug, title, body, parent_id, state, priority,
                                      tags, created_by, provenance)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (slug, title, str(it.get("body") or ""), parent_id, state,
                 "critical" if it.get("priority") == "critical" else "normal",
                 str(it.get("tags") or ""), actor, str(it.get("provenance") or "")))
            _event(cur.lastrowid, "created", actor, f"as {state}")
            _conn.commit()
        results.append({"slug": slug, "near_duplicates": dups})
    return results


def set_state(slug: str, state: str, actor: str, note: str = "",
              cascade: list[str] | None = None) -> dict:
    """State transitions. prune supports a client-confirmed cascade: the subtree the
    human SAW in the consequence dialog; the server verifies it still matches (no
    TOCTOU pruning of children added mid-dialog)."""
    if state not in ("open", "discussed", "pruned"):
        return {"error": f"bad state {state!r}"}
    with _lock:
        row = _conn.execute("SELECT id, state FROM topic WHERE slug=?", (slug,)).fetchone()
        if not row:
            return {"error": "not found"}
        ids = [row["id"]]
        if state == "pruned":
            # collect the live subtree
            subtree, frontier = [row["id"]], [row["id"]]
            while frontier:
                marks = ",".join("?" for _ in frontier)
                kids = _conn.execute(
                    f"SELECT id FROM topic WHERE parent_id IN ({marks}) "
                    "AND state IN ('seedling','open','discussed')", frontier).fetchall()
                frontier = [k["id"] for k in kids]
                subtree.extend(frontier)
            if cascade is not None:
                slugs = set(cascade)
                actual = {r2["slug"] for r2 in _conn.execute(
                    f"SELECT slug FROM topic WHERE id IN ({','.join('?' for _ in subtree)})",
                    subtree)}
                if actual != slugs:
                    return {"error": "subtree changed since the confirm dialog; reload",
                            "expected": sorted(slugs), "actual": sorted(actual)}
            ids = subtree
        ev = {"open": "reopened", "discussed": "discussed", "pruned": "pruned"}[state]
        for tid in ids:
            _conn.execute(
                """UPDATE topic SET state=?, state_changed_at=datetime('now'),
                   state_changed_by=?, state_note=?, touched_at=datetime('now')
                   WHERE id=?""", (state, actor, note, tid))
            _event(tid, ev, actor, note)
        _conn.commit()
    return {"ok": True, "changed": len(ids)}


def convert(slug: str, links: list[dict], actor: str, note: str = "") -> dict:
    """The atomic conversion moment: record decision/work_item/document refs AND mark
    discussed, one act. links: [{kind, ref, note?}]."""
    with _lock:
        row = _conn.execute("SELECT id FROM topic WHERE slug=?", (slug,)).fetchone()
        if not row:
            return {"error": "not found"}
        for l in links:
            if l.get("kind") not in ("decision", "work_item", "document"):
                return {"error": f"bad link kind {l.get('kind')!r}"}
            _conn.execute(
                "INSERT INTO topic_link (topic_id, kind, ref, note) VALUES (?,?,?,?)",
                (row["id"], l["kind"], str(l.get("ref") or ""), str(l.get("note") or "")))
        _conn.execute(
            """UPDATE topic SET state='discussed', state_changed_at=datetime('now'),
               state_changed_by=?, state_note=?, touched_at=datetime('now')
               WHERE id=?""", (actor, note or "converted", row["id"]))
        _event(row["id"], "converted", actor,
               "; ".join(f"{l['kind']}:{l.get('ref','')}" for l in links))
        _conn.commit()
    return {"ok": True, "links": len(links)}


def edit_topic(slug: str, actor: str, title: str | None = None,
               body: str | None = None, parent_slug: str | None = None,
               critical: bool | None = None) -> dict:
    with _lock:
        row = _conn.execute("SELECT id FROM topic WHERE slug=?", (slug,)).fetchone()
        if not row:
            return {"error": "not found"}
        tid = row["id"]
        if title is not None:
            _conn.execute("UPDATE topic SET title=? WHERE id=?", (title, tid))
        if body is not None:
            _conn.execute("UPDATE topic SET body=? WHERE id=?", (body, tid))
        if parent_slug is not None:
            if parent_slug == "":
                _conn.execute("UPDATE topic SET parent_id=NULL WHERE id=?", (tid,))
                _event(tid, "reparented", actor, "-> root")
            else:
                p = _conn.execute("SELECT id FROM topic WHERE slug=?", (parent_slug,)).fetchone()
                if not p:
                    return {"error": "parent not found"}
                # cycle guard: the new parent must not be inside this topic's subtree
                cur, seen = p["id"], set()
                while cur is not None and cur not in seen:
                    if cur == tid:
                        return {"error": "cycle: parent is inside this subtree"}
                    seen.add(cur)
                    nxt = _conn.execute("SELECT parent_id FROM topic WHERE id=?", (cur,)).fetchone()
                    cur = nxt["parent_id"] if nxt else None
                _conn.execute("UPDATE topic SET parent_id=? WHERE id=?", (p["id"], tid))
                _event(tid, "reparented", actor, f"-> {parent_slug}")
        if critical is not None:
            _conn.execute("UPDATE topic SET priority=? WHERE id=?",
                          ("critical" if critical else "normal", tid))
            _event(tid, "beacon_set" if critical else "beacon_cleared", actor)
        if title is not None or body is not None:
            _event(tid, "edited", actor)
        _touch(tid, actor)
        _conn.commit()
    return {"ok": True}


def search_in(query, topics, limit=40):
    """Ranked search over a given topic list (store-agnostic). SEMANTIC when the
    embedder is up (cosine over MiniLM vectors); keyword scoring otherwise."""
    ranked = semantic_rank(query, topics)
    if ranked is not None:
        return [{"slug": x["slug"], "score": round(s, 4), "state": x["state"],
                 "mode": "semantic"}
                for s, x in ranked if s > 0.22][:limit]
    q = _tokens(query)
    scored = []
    for x in topics:
        s = _score(q, x["title"] + " " + x["body"])
        if s > 0:
            scored.append({"slug": x["slug"], "score": round(s, 4),
                           "state": x["state"], "mode": "keyword"})
    scored.sort(key=lambda y: -y["score"])
    return scored[:limit]


def search(query: str, limit: int = 40) -> list[dict]:
    return search_in(query, _load_topics(include_archive=True), limit)


def rank_candidates(topics, context=""):
    """Serve ranking over a given list (store-agnostic): beacons > territory match
    (semantic when available) > age-decay resurfacing."""
    live = [x for x in topics if x["state"] in ("open", "seedling")]
    sem = semantic_rank(context, live) if context else None
    sem_by_slug = {x["slug"]: s for s, x in sem} if sem else {}
    ctx = _tokens(context)
    now = time.time()
    cands = []
    for x in live:
        age_days = max(0.0, (now - _parse_ts(x.get("touched_at") or x.get("created_at") or "")) / 86400.0)
        score = (100.0 if x["priority"] == "critical" else 0.0)
        if context:
            score += 40.0 * (sem_by_slug.get(x["slug"], 0.0) if sem
                             else _score(ctx, x["title"] + " " + x["body"]))
        score += min(20.0, age_days * 0.7)          # spaced resurfacing
        cands.append((score, x))
    cands.sort(key=lambda y: -y[0])
    return cands


def serve_card(context: str = "") -> dict:
    """ONE card (+2 alternates)."""
    cands = rank_candidates(_load_topics(), context)
    if not cands:
        return {"card": None, "alternates": []}
    card = cands[0][1]
    with _lock:
        _event(card["id"], "served", "server", f"context={context[:60]}")
        _touch(card["id"], "server", "served")
        _conn.commit()
    return {"card": card, "alternates": [c[1] for c in cands[1:3]]}


def _parse_ts(ts: str) -> float:
    try:
        return time.mktime(time.strptime(ts[:19], "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return time.time()


def expire_seedlings() -> int:
    """The noise valve: seedlings untouched ~21 days auto-expire (policy-level choice;
    counted in the groom report; browsable + resurrectable in the archive)."""
    with _lock:
        rows = _conn.execute(
            "SELECT id FROM topic WHERE state='seedling' AND "
            "julianday('now') - julianday(touched_at) > ?", (SEEDLING_EXPIRY_DAYS,)).fetchall()
        for r in rows:
            _conn.execute(
                "UPDATE topic SET state='expired', state_changed_at=datetime('now'), "
                "state_changed_by='server', state_note='seedling expiry' WHERE id=?",
                (r["id"],))
            _event(r["id"], "expired", "server", f"untouched > {SEEDLING_EXPIRY_DAYS}d")
        _conn.commit()
    return len(rows)


def health() -> dict:
    """The four vital signs of the seam loop (30-day window) + beacon ratio."""
    with _lock:
        def count(ev):
            return _conn.execute(
                "SELECT COUNT(*) c FROM topic_event WHERE event=? AND "
                "at > datetime('now', '-30 days')", (ev,)).fetchone()["c"]
        created, served = count("created"), count("served")
        converted, discussed = count("converted"), count("discussed")
        pruned, expired = count("pruned"), count("expired")
        live = _conn.execute(
            "SELECT COUNT(*) c FROM topic WHERE state IN ('seedling','open','discussed')"
        ).fetchone()["c"]
        beacons = _conn.execute(
            "SELECT COUNT(*) c FROM topic WHERE priority='critical' AND "
            "state IN ('seedling','open')").fetchone()["c"]
        opens = _conn.execute(
            "SELECT COUNT(*) c FROM topic WHERE state IN ('seedling','open')").fetchone()["c"]
    ratio = (beacons / opens) if opens else 0.0
    return {"window_days": 30, "captured": created, "served": served,
            "discussed": discussed, "converted": converted,
            "pruned": pruned, "expired": expired, "live_topics": live,
            "beacon_ratio": round(ratio, 3),
            "beacon_warning": ratio > BEACON_WARN_RATIO}


def groom_report() -> dict:
    """What the topics-groom skill needs, including the calibration feedback that
    teaches the AI from the human's actual behavior."""
    h = health()
    with _lock:
        by_actor = _conn.execute(
            """SELECT t.created_by AS actor,
                      SUM(CASE WHEN t.state IN ('open','discussed') THEN 1 ELSE 0 END) AS kept,
                      SUM(CASE WHEN t.state = 'expired' THEN 1 ELSE 0 END) AS expired,
                      SUM(CASE WHEN t.state = 'pruned' THEN 1 ELSE 0 END) AS pruned,
                      SUM(CASE WHEN t.state = 'seedling' THEN 1 ELSE 0 END) AS pending
               FROM topic t GROUP BY t.created_by""").fetchall()
        stale = _conn.execute(
            "SELECT slug, title FROM topic WHERE state='open' AND "
            "julianday('now') - julianday(touched_at) > 30 LIMIT 3").fetchall()
    return {"health": h,
            "capture_calibration": [dict(r) for r in by_actor],
            "expiry_candidates_full_topics": [dict(r) for r in stale]}


# ---------------------------------------------------------------- http ----
class Handler(BaseHTTPRequestHandler):
    web_root: Path | None = None

    def _json(self, code: int, obj) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/api/topics":
            return self._json(200, {"topics": _load_topics(
                include_archive=qs.get("include", [""])[0] == "archive")})
        if u.path == "/api/topics/search":
            return self._json(200, {"results": search(qs.get("q", [""])[0])})
        if u.path == "/api/topics/serve":
            return self._json(200, serve_card(qs.get("context", [""])[0]))
        if u.path == "/api/topics/health":
            return self._json(200, health())
        if u.path == "/api/topics/groom":
            return self._json(200, groom_report())
        # static web
        if self.web_root:
            rel = "index.html" if u.path == "/" else u.path.lstrip("/")
            f = (self.web_root / rel).resolve()
            if f.is_file() and self.web_root.resolve() in f.parents or f == (self.web_root / "index.html").resolve():
                ctype = {"html": "text/html", "js": "text/javascript",
                         "css": "text/css"}.get(f.suffix.lstrip("."), "application/octet-stream")
                data = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        try:
            body = self._body()
        except Exception:
            return self._json(400, {"error": "bad json"})
        actor = str(body.get("actor") or "unknown")
        if u.path == "/api/topics":
            items = body.get("topics") or ([body] if body.get("title") else [])
            return self._json(200, {"results": add_topics(items, actor)})
        m = re.match(r"^/api/topics/([a-z0-9-]+)/(state|links|edit)$", u.path)
        if m:
            slug, op = m.group(1), m.group(2)
            if op == "state":
                return self._json(200, set_state(slug, str(body.get("state")), actor,
                                                 str(body.get("note") or ""),
                                                 body.get("cascade")))
            if op == "links":
                return self._json(200, convert(slug, body.get("links") or [], actor,
                                               str(body.get("note") or "")))
            if op == "edit":
                return self._json(200, edit_topic(
                    slug, actor, body.get("title"), body.get("body"),
                    body.get("parent_slug"), body.get("critical")))
        self._json(404, {"error": "not found"})


def main() -> None:
    global _conn, DB_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="topics.db")
    ap.add_argument("--port", type=int, default=8991)
    ap.add_argument("--web", default=str(HERE.parent / "web"))
    args = ap.parse_args()
    DB_PATH = args.db
    _conn = open_db(args.db)
    expired = expire_seedlings()                       # the daily job, run at start too
    threading.Thread(target=_expiry_loop, daemon=True).start()
    Handler.web_root = Path(args.web)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(json.dumps({"topic_visualizer_server": f"http://127.0.0.1:{args.port}",
                      "db": args.db, "expired_on_start": expired}))
    srv.serve_forever()


def _expiry_loop():
    while True:
        time.sleep(24 * 3600)
        try:
            expire_seedlings()
        except Exception:
            pass


if __name__ == "__main__":
    main()
