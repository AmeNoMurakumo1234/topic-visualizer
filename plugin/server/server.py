#!/usr/bin/env python3
"""Topic Visualizer server - one small process, two faces over one SQLite store.

HTTP face: the web views (and anything else local). MCP face: exposed separately by
mcp_tools.py, which imports the same operations. Localhost only; zero heavy deps.

    python server.py [--db topics.db] [--port 8991] [--web ../web]

Design: docs/2026-07-11-seam-design.md. Schema: schema.sql (v3).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
VERSION = "0.7.0"                     # single source of truth (MCP serverInfo reads this)
SEEDLING_EXPIRY_DAYS = 21
BEACON_WARN_RATIO = 0.10

_lock = threading.RLock()     # single-writer discipline; REENTRANT so a request can
                              # pin its project's connection and still call locked helpers
_conn: sqlite3.Connection | None = None
DB_PATH = "topics.db"


# ---------------------------------------------------------------- store ----
# One SQLite file = one topic tree = one PROJECT (schema.sql). Projects are scoped per
# machine and never hardcoded: the current one auto-derives from the loaded session's
# working directory, encoded the same way Claude names ~/.claude/projects
# (C:\Repos\my-app -> C--Repos-my-app), so the store lines up with the project the user
# is actually in. A downloaded plugin therefore carries the USER's projects.
DEFAULT_DB = str(Path.home() / ".topic-visualizer" / "topics.db")   # legacy single store
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"          # what projects exist

_conns: dict[str, sqlite3.Connection] = {}   # project key -> connection (lazily opened)
_default_project = "default"                  # set in main() from cwd / env / --db


def _projects_dir() -> Path:
    """Per-project DB files live beside the default store, so one root (DEFAULT_DB or an
    explicit --db) controls the whole thing and tests stay isolated."""
    return Path(DB_PATH).expanduser().resolve().parent / "projects"


def encode_project_path(p) -> str:
    """Encode an absolute path to the key Claude uses for ~/.claude/projects: the drive
    colon, every path separator, AND dots each become '-' (NOT collapsed, matching Claude
    exactly - it replaces the dot too, so `.claude` -> `-claude`). C:\\Repos\\MyApp ->
    C--Repos-MyApp ; Z:\\tools -> Z--tools. So keys line up with dropdown dir names even
    for paths carrying dots."""
    return re.sub(r"[:/\\.]", "-", str(p)) or "default"


def _repo_root(start=None) -> str | None:
    """The canonical MAIN working tree of the git repo at `start` (cwd by default),
    collapsing ALL linked worktrees to one root. Claude Code runs each session in a
    throwaway worktree (repo/.claude/worktrees/<rand>) as cwd; keying off that scatters
    every session into a different empty store. `git rev-parse --git-common-dir` returns
    the shared .git for every worktree of a repo, so its parent is the one true repo root.
    None if `start` is not inside a git repo (caller falls back to raw cwd)."""
    try:
        start = str(start or Path.cwd())
        kw = {}
        if sys.platform == "win32":
            kw["creationflags"] = 0x08000000   # CREATE_NO_WINDOW - no console flash (windowless MCP host)
        out = subprocess.run(["git", "-C", start, "rev-parse", "--git-common-dir"],
                             capture_output=True, text=True, timeout=5, **kw)
        common = (out.stdout or "").strip()
        if out.returncode != 0 or not common:
            return None
        # common may be relative to `start` (".git") or absolute; resolve either, take parent
        root = (Path(start) / common).resolve().parent
        return str(root)
    except Exception:
        return None


def project_key_from_cwd() -> str:
    """The project key for the currently loaded session. Resolves to the git REPO ROOT
    (not the ephemeral worktree cwd) so every session of a repo shares one store; falls
    back to the raw cwd when not in a git repo. `default` if undeterminable. The
    TOPICS_PROJECT env override (read by callers) is the manual escape hatch."""
    try:
        base = _repo_root() or str(Path.cwd())
    except Exception:
        return "default"
    return encode_project_path(base)


def _safe_key(k: str) -> str:
    """A filesystem-safe, machine-agnostic project key (never trust a raw query value)."""
    k = re.sub(r"[^A-Za-z0-9._-]", "-", (k or "").strip()).strip("-")
    return (k or "default")[:120]


def _fold_worktree(name: str) -> str:
    """A Claude worktree project dir (`<repo>/.claude/worktrees/<rand>`) encodes to
    `<repokey>-claude-worktrees-<rand>`. Fold it back to the repo key so the dropdown
    shows ONE entry per repo, not one per (throwaway) worktree."""
    return re.split(r"-+claude-worktrees-", name, maxsplit=1)[0]


def _repo_name_from_path(cwd: str) -> str:
    """The human-facing folder NAME for a path: strip a Claude worktree suffix
    (`/.claude/worktrees/<rand>`) to the repo, then take the last real path segment. So
    C:\\Repos\\MyApp -> MyApp, and .../my-cool-app stays my-cool-app (split on real
    separators, never the lossy encoded dashes). No path/drive leak in the label."""
    p = str(cwd).replace("\\", "/").rstrip("/")
    p = re.split(r"/\.claude/worktrees/", p, maxsplit=1)[0].rstrip("/")
    return p.split("/")[-1] or p


def _read_project_cwd(d: Path):
    """The real cwd recorded in the project's newest session transcript, or None. The
    ~/.claude/projects dir name is a LOSSY encoding (dashes are ambiguous), so a transcript
    is the only reliable source of the true path -> a clean folder-name label."""
    try:
        sessions = sorted(d.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in sessions[:1]:                      # newest session only
            chunk = f.read_bytes()[:65536]          # cwd appears early (~9 KB in)
            m = re.search(rb'"cwd"\s*:\s*"((?:[^"\\]|\\.)*)"', chunk)
            if m:
                return json.loads(b'"' + m.group(1) + b'"')
    except Exception:
        pass
    return None


def _label_fallback(key: str) -> str:
    """Best-effort label when no transcript exists: never the full path - just the tail
    token (imperfect for hyphenated names, but leaks no drive/path)."""
    if key == "default":
        return "default"
    return key.rsplit("-", 1)[-1] or key


def project_db_path(key: str) -> str:
    """DB file for a project key. 'default' keeps the pre-per-project single store so
    existing topics are never orphaned; every other key gets its own file."""
    key = _safe_key(key)
    return DEFAULT_DB if key == "default" else str(_projects_dir() / f"{key}.db")


def _use_project(key: str) -> str:
    """Point the module-global _conn at this project's (cached, lazily opened) connection.
    The CALLER MUST HOLD _lock for the whole request so the pin is stable under threading."""
    global _conn
    key = _safe_key(key)
    c = _conns.get(key)
    if c is None:
        c = open_db(project_db_path(key))
        _conns[key] = c
    _conn = c
    return key


def list_projects(current: str) -> dict:
    """Every project the dropdown should offer: the Claude projects present on THIS
    machine (so it knows what exists) plus any topic stores already created, current
    flagged. Nothing hardcoded to any one machine."""
    seen: dict[str, str] = {}                         # key -> clean display label
    if CLAUDE_PROJECTS_DIR.is_dir():
        for d in sorted(CLAUDE_PROJECTS_DIR.iterdir()):
            if d.is_dir() and not d.name.startswith("."):
                key = _safe_key(_fold_worktree(d.name))   # collapse N worktrees -> one repo entry
                if key in seen:
                    continue
                cwd = _read_project_cwd(d)                # real path -> just the folder name
                seen[key] = _repo_name_from_path(cwd) if cwd else _label_fallback(key)
    pdir = _projects_dir()
    if pdir.is_dir():
        for f in sorted(pdir.glob("*.db")):
            seen.setdefault(_safe_key(f.stem), _label_fallback(_safe_key(f.stem)))
    cur = _safe_key(current)
    if cur not in seen:                              # label the current project cleanly when
        root = _repo_root()                          # it is the server's own repo (real path
        if root and _safe_key(encode_project_path(root)) == cur:   # -> real folder name)
            seen[cur] = _repo_name_from_path(root)
        else:
            seen[cur] = _label_fallback(cur)
    seen.setdefault("default", "default")
    projects = [{"key": k, "label": lbl, "current": k == cur}
                for k, lbl in sorted(seen.items(), key=lambda kv: kv[1].lower())]
    return {"projects": projects, "current": cur}


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Idempotent migration for DBs created before a column existed. CREATE TABLE
    IF NOT EXISTS never alters an existing table, so additive columns are added here."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(topic)")}
    if "merged_into" not in cols:
        conn.execute("ALTER TABLE topic ADD COLUMN merged_into TEXT")


def open_db(path: str) -> sqlite3.Connection:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)     # a real, user-owned home path
    conn = sqlite3.connect(str(p), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    _ensure_columns(conn)
    conn.commit()
    return conn


def _slugify_locked(title: str, salt: int = 0) -> str:
    """Mint a free slug. CALLER MUST HOLD _lock (mint+insert under one hold closes the
    check-then-act race). Truncates on a WORD BOUNDARY (never mid-word like '...-docume')
    and appends a short content hash for stable uniqueness, so near-identical titles get
    distinct, still-readable slugs without a numeric-collision walk."""
    words = re.sub(r"[^a-z0-9]+", " ", title.lower()).split()
    base = ""
    for w in words:
        if base and len(base) + 1 + len(w) > 48:      # stop at the last WHOLE word that fits
            break
        base = f"{base}-{w}" if base else w
    base = base or "topic"
    h = hashlib.sha1((title + (f"#{salt}" if salt else "")).encode("utf-8")).hexdigest()[:6]
    slug, n = f"{base}-{h}", 1
    while _conn.execute("SELECT 1 FROM topic WHERE slug=?", (slug,)).fetchone():
        n += 1
        slug = f"{base}-{h}-{n}"
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
        xpq = """SELECT tp.topic_id, tp.note, tp.added_by, tp.added_at,
                        p.slug AS parent_slug
                 FROM topic_parent tp JOIN topic p ON p.id = tp.parent_id"""
        if not include_archive:
            xpq += " WHERE p.state IN ('seedling','open','discussed')"
        xp_rows = _conn.execute(xpq).fetchall()
    links: dict = {}
    for lr in link_rows:
        links.setdefault(lr["topic_id"], []).append(
            {"kind": lr["kind"], "ref": lr["ref"], "note": lr["note"]})
    xparents: dict = {}
    for xr in xp_rows:
        xparents.setdefault(xr["topic_id"], []).append(
            {"slug": xr["parent_slug"], "note": xr["note"],
             "added_by": xr["added_by"], "added_at": xr["added_at"]})
    out = []
    for r in rows:
        t = _row_to_topic(r, links)
        t["extra_parents"] = xparents.get(r["id"], [])
        out.append(t)
    return out


def get_topic(slug: str) -> dict:
    """FULL detail for ONE topic - what a groomer needs before deciding
    convert/prune/keep: title, body, the QUESTION, state, priority, tags, provenance,
    ALL parents (primary + extra avenues w/ their notes), children, recorded
    conversions, and recent history. (search only returns slug/score/state.)"""
    with _lock:
        r = _conn.execute(
            "SELECT t.*, p.slug AS parent_slug FROM topic t "
            "LEFT JOIN topic p ON p.id=t.parent_id WHERE t.slug=?", (slug,)).fetchone()
        if not r:
            return _fail("not found")
        tid = r["id"]
        links = [{"kind": x["kind"], "ref": x["ref"], "note": x["note"]}
                 for x in _conn.execute(
                     "SELECT kind, ref, note FROM topic_link WHERE topic_id=?", (tid,))]
        extra = [{"slug": x["parent_slug"], "note": x["note"], "added_by": x["added_by"],
                  "added_at": x["added_at"]}
                 for x in _conn.execute(
                     "SELECT tp.note, tp.added_by, tp.added_at, p.slug AS parent_slug "
                     "FROM topic_parent tp JOIN topic p ON p.id=tp.parent_id "
                     "WHERE tp.topic_id=?", (tid,))]
        children = [x["slug"] for x in _conn.execute(
            "SELECT slug FROM topic WHERE parent_id=?", (tid,))]
        events = [{"event": x["event"], "actor": x["actor"], "note": x["note"], "at": x["at"]}
                  for x in _conn.execute(
                      "SELECT event, actor, note, at FROM topic_event WHERE topic_id=? "
                      "ORDER BY id DESC LIMIT 12", (tid,))]
    t = _row_to_topic(r)
    t.pop("id", None)
    t.update({"extra_parents": extra, "links": links, "children": children,
              "history": events})
    return {"topic": t}


def list_topics(include_archive=False, limit=500, offset=0) -> dict:
    """ENUMERATE the store (compact): slug, title, state, priority, primary parent, per
    row. The inventory a groom needs - search only surfaces matches, so 41 topics used to
    take a hand-unioned keyword sweep. Paginated (total returned so the caller can page)."""
    try:
        limit = max(1, min(int(limit), 2000)); offset = max(0, int(offset))
    except Exception:
        limit, offset = 500, 0
    q = ("SELECT t.slug, t.title, t.state, t.priority, p.slug AS parent "
         "FROM topic t LEFT JOIN topic p ON p.id=t.parent_id")
    if not include_archive:
        q += " WHERE t.state IN ('seedling','open','discussed')"
    q += " ORDER BY t.id"
    with _lock:
        rows = _conn.execute(q).fetchall()
    page = [dict(r) for r in rows[offset:offset + limit]]
    return {"topics": page, "total": len(rows), "offset": offset,
            "limit": limit, "returned": len(page)}


def _fail(msg: str, **extra) -> dict:
    """Error return from inside an action: roll back any pending writes FIRST -
    on a shared autocommit-off connection they would otherwise be committed by
    whichever unrelated action commits next (audit 2026-07-11, HIGH)."""
    _conn.rollback()
    out = {"error": msg}
    out.update(extra)
    return out


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
_embed_failed_at = 0.0
_embed_cache = {}


def _embed(texts):
    global _embed_up
    if not EMBED_URL:
        return None
    if _embed_up is False and time.time() - _embed_failed_at < 60:
        return None                      # re-probe after a minute, never latch forever
    if len(_embed_cache) > 4000:
        _embed_cache.clear()             # crude bound beats an unbounded leak
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
            globals()["_embed_failed_at"] = time.time()
            return None
    return [_embed_cache[x] for x in texts]


def _embed_status() -> str:
    """up | down | unknown - so a groomer KNOWS whether semantic ranking actually engaged
    (vs silently falling back to keyword). Reflects the last probe of TOPICS_EMBED_URL."""
    return "up" if _embed_up is True else "down" if _embed_up is False else "unknown"


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


def _dup_band(score, mode):
    """A readable confidence band beside the raw score - the caller shouldn't have to
    guess where 'same territory, plant no twin' begins. Semantic scores are cosine (0..1);
    keyword scores are unbounded, so its cutoffs are heuristic (documented as such)."""
    if mode == "semantic":
        return "dup_likely" if score >= 0.85 else "kin" if score >= 0.6 else "weak"
    return "dup_likely" if score >= 1.2 else "kin" if score >= 0.55 else "weak"


def near_duplicates_in(title, body, topics, limit=3):
    """Write-time dedup guard over a given topic list (store-agnostic; the MCP board
    backend reuses this). Semantic when the embedder is up, keyword otherwise. Each hit
    carries `mode` + a `band` (dup_likely | kin | weak) beside the raw score."""
    ranked = semantic_rank(title + " " + body[:200], topics)
    out = []
    if ranked is not None:
        out = [{"slug": x["slug"], "title": x["title"], "score": round(s, 3),
                "mode": "semantic", "band": _dup_band(s, "semantic")}
               for s, x in ranked if s > 0.62]
    else:
        q = _tokens(title + " " + body[:200])
        for x in topics:
            s = _score(q, x["title"] + " " + x["body"][:200])
            if s > 0.55:
                out.append({"slug": x["slug"], "title": x["title"], "score": round(s, 3),
                            "mode": "keyword", "band": _dup_band(s, "keyword")})
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
        with _lock:
            parent_id = None
            if it.get("parent_slug"):
                row = _conn.execute("SELECT id FROM topic WHERE slug=?",
                                    (it["parent_slug"],)).fetchone()
                parent_id = row["id"] if row else None
            state = it.get("state") or "seedling"
            if state not in ("seedling", "open"):
                state = "seedling"
            # mint + INSERT under ONE lock hold; retry on the (now rare) collision
            for attempt in range(4):
                slug = _slugify_locked(title, attempt)
                try:
                    cur = _conn.execute(
                        """INSERT INTO topic (slug, title, body, parent_id, state, priority,
                                              tags, created_by, provenance)
                           VALUES (?,?,?,?,?,?,?,?,?)""",
                        (slug, title, str(it.get("body") or ""), parent_id, state,
                         "critical" if it.get("priority") == "critical" else "normal",
                         str(it.get("tags") or ""), actor, str(it.get("provenance") or "")))
                    break
                except sqlite3.IntegrityError:
                    if attempt == 3:
                        _conn.rollback()
                        results.append({"error": "slug collision", "near_duplicates": dups})
                        slug = None
                        break
            if slug is None:
                continue
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
            return _fail("not found")
        ids = [row["id"]]
        if state == "pruned":
            # collect the live PRIMARY subtree
            def closure(root_ids):
                out, fr = list(root_ids), list(root_ids)
                while fr:
                    marks = ",".join("?" for _ in fr)
                    kids = _conn.execute(
                        f"SELECT id FROM topic WHERE parent_id IN ({marks}) "
                        "AND state IN ('seedling','open','discussed')", fr).fetchall()
                    fr = [k["id"] for k in kids if k["id"] not in out]
                    out.extend(fr)
                return out
            subtree = closure([row["id"]])
            # SURVIVORS (multi-parent law): a descendant reachable via an extra
            # parent OUTSIDE the pruned set has another reason to exist - it is
            # spared, and that outside avenue is promoted to its primary parent.
            # (Mirrored in the web core's pruneSet(); keep the two in sync.)
            promoted = []
            while True:
                sset = set(subtree)
                spared = None
                for tid2 in subtree:
                    if tid2 == row["id"]:
                        continue
                    xp = _conn.execute(
                        """SELECT tp.parent_id FROM topic_parent tp
                           JOIN topic p ON p.id = tp.parent_id
                           WHERE tp.topic_id=? AND p.state IN
                             ('seedling','open','discussed')""", (tid2,)).fetchall()
                    outside = [x["parent_id"] for x in xp if x["parent_id"] not in sset]
                    if outside:
                        spared = (tid2, outside[0])
                        break
                if spared is None:
                    break
                tid2, new_pid = spared
                keep = set(closure([tid2]))
                subtree = [i for i in subtree if i not in keep]
                promoted.append((tid2, new_pid))
            # verify the client-confirmed cascade BEFORE any promotion writes:
            # a REFUSED prune must leave the DAG untouched (audit HIGH-1)
            if cascade is not None:
                slugs = set(cascade)
                actual = {r2["slug"] for r2 in _conn.execute(
                    f"SELECT slug FROM topic WHERE id IN ({','.join('?' for _ in subtree)})",
                    subtree)}
                if actual != slugs:
                    return _fail("subtree changed since the confirm dialog; reload",
                                 expected=sorted(slugs), actual=sorted(actual))
            for tid2, new_pid in promoted:
                _conn.execute("UPDATE topic SET parent_id=? WHERE id=?", (new_pid, tid2))
                _conn.execute("DELETE FROM topic_parent WHERE topic_id=? AND parent_id=?",
                              (tid2, new_pid))
                _event(tid2, "reparented", actor, "promoted surviving avenue on prune")
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
            return _fail("not found")
        # validate the WHOLE batch before writing any of it (atomic conversion)
        for l in links:
            if not isinstance(l, dict) or l.get("kind") not in (
                    "decision", "work_item", "document"):
                kind = l.get("kind") if isinstance(l, dict) else l
                return _fail(f"bad link kind {kind!r}")
        for l in links:
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
            return _fail("not found")
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
                p = _conn.execute("SELECT id, state FROM topic WHERE slug=?",
                                  (parent_slug,)).fetchone()
                if not p:
                    return _fail("parent not found")
                if p["state"] in ("pruned", "expired"):
                    return _fail("parent is archived - resurrect it first")
                # cycle guard over the FULL DAG: walk every ancestor path (primary +
                # extra edges) up from the new parent; hitting this topic = a cycle
                frontier, seen = [p["id"]], set()
                while frontier:
                    cur = frontier.pop()
                    if cur == tid:
                        return _fail("cycle: parent is inside this subtree")
                    if cur in seen:
                        continue
                    seen.add(cur)
                    nxt = _conn.execute("SELECT parent_id FROM topic WHERE id=?", (cur,)).fetchone()
                    if nxt and nxt["parent_id"] is not None:
                        frontier.append(nxt["parent_id"])
                    frontier += [x["parent_id"] for x in _conn.execute(
                        "SELECT parent_id FROM topic_parent WHERE topic_id=?", (cur,))]
                _conn.execute("UPDATE topic SET parent_id=? WHERE id=?", (p["id"], tid))
                # if the new primary was also an extra edge, collapse the duplicate
                _conn.execute("DELETE FROM topic_parent WHERE topic_id=? AND parent_id=?",
                              (tid, p["id"]))
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


def attach_parent(slug: str, parent_slug: str, actor: str, note: str = "",
                  remove: bool = False) -> dict:
    """Multi-parent: the same semantic topic reached from a SECOND conversational
    avenue. Adds an extra edge (never a duplicate subtree) and enriches the topic
    with what the later discovery added: a 'rediscovered' event + a body append.
    remove=True detaches the extra edge (the primary parent is edit_topic's job)."""
    with _lock:
        row = _conn.execute(
            "SELECT id, parent_id, body FROM topic WHERE slug=?", (slug,)).fetchone()
        p = _conn.execute("SELECT id, state FROM topic WHERE slug=?",
                          (parent_slug,)).fetchone()
        if not row or not p:
            return _fail("topic or parent not found")
        tid, pid = row["id"], p["id"]
        if not remove and p["state"] in ("pruned", "expired"):
            return _fail("parent is archived - resurrect it first")
        if remove:
            n = _conn.execute("DELETE FROM topic_parent WHERE topic_id=? AND parent_id=?",
                              (tid, pid)).rowcount
            if n:
                _event(tid, "detached", actor, f"<- {parent_slug}")
                _touch(tid, actor)
            _conn.commit()
            return {"ok": True, "removed": n}
        if tid == pid:
            return _fail("a topic cannot parent itself")
        if row["parent_id"] == pid:                  # idempotent: already parented -> not an error
            return {"ok": True, "already": True, "attached": parent_slug,
                    "note": "already the primary parent"}
        # cycle guard over the FULL DAG: the new parent must not sit anywhere inside
        # this topic's descendant closure (primary + extra edges both count)
        frontier, seen = [tid], {tid}
        while frontier:
            marks = ",".join("?" for _ in frontier)
            kids = [k["id"] for k in _conn.execute(
                f"SELECT id FROM topic WHERE parent_id IN ({marks})", frontier)]
            kids += [k["topic_id"] for k in _conn.execute(
                f"SELECT topic_id FROM topic_parent WHERE parent_id IN ({marks})", frontier)]
            frontier = [k for k in kids if k not in seen]
            seen.update(frontier)
            if pid in seen:
                return _fail("cycle: that parent is inside this topic's subtree")
        try:
            _conn.execute(
                "INSERT INTO topic_parent (topic_id, parent_id, note, added_by) "
                "VALUES (?,?,?,?)", (tid, pid, note, actor))
        except sqlite3.IntegrityError:               # idempotent: this avenue already exists
            _conn.rollback()
            return {"ok": True, "already": True, "attached": parent_slug,
                    "note": "already attached to that parent"}
        # rediscovery enrichment: the later avenue leaves a visible trace on the topic
        stamp = time.strftime("%Y-%m-%d")
        addendum = f"\n\n[rediscovered {stamp} via {parent_slug}]" + (f" {note}" if note else "")
        _conn.execute("UPDATE topic SET body = body || ? WHERE id=?", (addendum, tid))
        _event(tid, "rediscovered", actor, f"via {parent_slug}" + (f": {note}" if note else ""))
        _touch(tid, actor)
        _conn.commit()
    return {"ok": True, "attached": parent_slug}


# FACET terms: state / beacon words act as FILTERS, so "critical" finds every
# beacon and "critical grounding" ranks beacons by "grounding". Mirrored in the
# web core's client-side fallback (topics-core.js) - keep the two in sync.
_FACETS = {
    "critical": lambda t: t["priority"] == "critical",
    "beacon":   lambda t: t["priority"] == "critical",
    "seedling": lambda t: t["state"] == "seedling",
    "open":     lambda t: t["state"] == "open",
    "discussed": lambda t: t["state"] == "discussed",
    "pruned":   lambda t: t["state"] == "pruned",
    "expired":  lambda t: t["state"] == "expired",
    "archived": lambda t: t["state"] in ("pruned", "expired"),
}


def search_in(query, topics, limit=40):
    """Ranked search over a given topic list (store-agnostic). Facet words filter
    by state/beacon; the rest of the query ranks SEMANTICALLY when the embedder is
    up (cosine over MiniLM vectors), by keyword scoring otherwise."""
    words = query.lower().split()
    facets = [_FACETS[w] for w in words if w in _FACETS]
    rest = " ".join(w for w in words if w not in _FACETS)
    if facets:
        topics = [t for t in topics if all(f(t) for f in facets)]
        if not rest.strip():
            return [{"slug": t["slug"], "score": 1.0, "state": t["state"],
                     "mode": "facet"} for t in topics][:limit]
        query = rest
    ranked = semantic_rank(query, topics)
    if ranked is not None:
        return [{"slug": x["slug"], "score": round(s, 4), "state": x["state"],
                 "mode": "semantic", "band": _dup_band(s, "semantic")}
                for s, x in ranked if s > 0.22][:limit]
    q = _tokens(query)
    scored = []
    for x in topics:
        s = _score(q, x["title"] + " " + x["body"])
        if s > 0:
            scored.append({"slug": x["slug"], "score": round(s, 4),
                           "state": x["state"], "mode": "keyword",
                           "band": _dup_band(s, "keyword")})
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
        _conn.execute("UPDATE topic SET touched_at = datetime('now') WHERE id=?",
                      (card["id"],))          # resurface clock resets; NO graduation
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
        # CURRENT-STATE snapshot (distinct from the 30-day activity window above): the real
        # distribution right now, so 'live' vs 'converted' is never ambiguous.
        by_state = {s: 0 for s in ("seedling", "open", "discussed", "pruned", "expired")}
        for r in _conn.execute("SELECT state, COUNT(*) c FROM topic GROUP BY state"):
            by_state[r["state"]] = r["c"]
        converted_topics = _conn.execute(
            "SELECT COUNT(DISTINCT topic_id) c FROM topic_link").fetchone()["c"]
    ratio = (beacons / opens) if opens else 0.0
    return {"window_days": 30,
            # 30-day ACTIVITY window (events), not current state:
            "window": {"captured": created, "served": served, "discussed": discussed,
                       "converted": converted, "pruned": pruned, "expired": expired},
            # CURRENT state snapshot:
            "by_state": by_state, "converted_topics": converted_topics,
            "live_topics": live, "beacons": beacons,
            "beacon_ratio": round(ratio, 3), "beacon_warning": ratio > BEACON_WARN_RATIO,
            "embedder": {"url": EMBED_URL, "status": _embed_status()},
            # legacy flat keys (kept for back-compat; prefer window{} / by_state{}):
            "captured": created, "served": served, "discussed": discussed,
            "converted": converted, "pruned": pruned, "expired": expired}


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
        n = max(0, int(self.headers.get("Content-Length") or 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        return body

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        try:
            return self._get()
        except Exception as e:
            try:
                self._json(500, {"error": str(e)})
            except Exception:
                pass

    def _get(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        if u.path == "/api/projects":
            with _lock:
                return self._json(200, list_projects(
                    qs.get("project", [None])[0] or _default_project))
        if u.path.startswith("/api/topics"):
            key = qs.get("project", [None])[0] or _default_project
            with _lock:                          # pin this project's connection for the request
                _use_project(key)
                if u.path == "/api/topics":
                    return self._json(200, {"topics": _load_topics(
                        include_archive=qs.get("include", [""])[0] == "archive")})
                if u.path == "/api/topics/list":
                    return self._json(200, list_topics(
                        include_archive=qs.get("include", [""])[0] == "archive",
                        limit=qs.get("limit", ["500"])[0], offset=qs.get("offset", ["0"])[0]))
                if u.path == "/api/topics/search":
                    return self._json(200, {"results": search(qs.get("q", [""])[0])})
                if u.path == "/api/topics/serve":
                    return self._json(200, serve_card(qs.get("context", [""])[0]))
                if u.path == "/api/topics/health":
                    return self._json(200, health())
                if u.path == "/api/topics/groom":
                    return self._json(200, groom_report())
                mget = re.match(r"^/api/topics/([a-z0-9][a-z0-9._-]*)$", u.path)
                if mget:                             # GET /api/topics/<slug> -> full detail
                    return self._json(200, get_topic(mget.group(1)))
        # background images: whatever PNGs live in the plugin's backgrounds/ folder
        # (empty -> the web falls back to the generated canvas scene). The user
        # picks one; images are meant to be rendered mostly-transparent.
        if u.path == "/api/backgrounds":
            bg = HERE.parent / "backgrounds"
            # discover WHATEVER images the user has dropped in (any common type),
            # never a hardcoded list
            exts = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif")
            files = sorted(p.name for p in bg.iterdir()
                           if p.is_file() and p.suffix.lower() in exts) if bg.is_dir() else []
            return self._json(200, {"backgrounds": files})
        # static web + backgrounds
        if self.web_root:
            rel = "index.html" if u.path == "/" else u.path.lstrip("/")
            bg_root = (HERE.parent / "backgrounds").resolve()
            if u.path.startswith("/backgrounds/"):
                f = (bg_root / u.path[len("/backgrounds/"):]).resolve()
                f = f if (f.is_file() and bg_root in f.parents) else None
            else:
                f = (self.web_root / rel).resolve()
                if f == (self.web_root / "index.html").resolve():
                    f = f if f.is_file() else None
                elif not (f.is_file() and self.web_root.resolve() in f.parents):
                    f = None
            if f is not None:
                ctype = {"html": "text/html", "js": "text/javascript",
                         "css": "text/css", "png": "image/png",
                         "jpg": "image/jpeg", "jpeg": "image/jpeg",
                         "webp": "image/webp"}.get(
                             f.suffix.lstrip("."), "application/octet-stream")
                data = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            return self._post()
        except Exception as e:
            try:
                self._json(500, {"error": str(e)})
            except Exception:
                pass

    def _post(self):
        u = urlparse(self.path)
        try:
            body = self._body()
        except Exception:
            return self._json(400, {"error": "bad json"})
        actor = str(body.get("actor") or "unknown")
        key = (parse_qs(u.query).get("project", [None])[0]
               or body.get("project") or _default_project)
        with _lock:                              # pin this project's connection for the request
            _use_project(key)
            if u.path == "/api/topics":
                items = body.get("topics") or ([body] if body.get("title") else [])
                return self._json(200, {"results": add_topics(items, actor)})
            m = re.match(r"^/api/topics/([a-z0-9-]+)/(state|links|edit|attach)$", u.path)
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
                if op == "attach":
                    return self._json(200, attach_parent(
                        slug, str(body.get("parent_slug") or ""), actor,
                        str(body.get("note") or ""), bool(body.get("remove"))))
        self._json(404, {"error": "not found"})


def main() -> None:
    global _conn, DB_PATH, _default_project
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB, help="DB for the 'default' project (back-compat)")
    ap.add_argument("--project", default=None, help="default project key (else auto from cwd)")
    ap.add_argument("--port", type=int, default=8991)
    ap.add_argument("--web", default=str(HERE.parent / "web"))
    args = ap.parse_args()
    DB_PATH = args.db
    # The default project: explicit --project / TOPICS_PROJECT, else auto from the loaded
    # session's cwd. An explicit non-standard --db (tests, custom store) pins 'default' to
    # that file so existing single-store setups keep working unchanged.
    _default_project = args.project or os.environ.get("TOPICS_PROJECT") or project_key_from_cwd()
    if args.db != DEFAULT_DB:
        _conns["default"] = open_db(args.db)
        _default_project = args.project or "default"
    with _lock:
        _use_project(_default_project)
    expired = expire_all()                              # the daily job, run at start too
    threading.Thread(target=_expiry_loop, daemon=True).start()
    Handler.web_root = Path(args.web)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(json.dumps({"topic_visualizer_server": f"http://127.0.0.1:{args.port}",
                      "db": args.db, "default_project": _default_project,
                      "expired_on_start": expired}))
    srv.serve_forever()


def expire_all() -> int:
    """Sweep seedling expiry across EVERY project store, not just the pinned one - each
    per-project DB has its own seedlings on the same ~21-day clock."""
    keys = set(_conns) | {_default_project}
    pdir = _projects_dir()
    if pdir.is_dir():
        keys |= {_safe_key(f.stem) for f in pdir.glob("*.db")}
    total = 0
    for k in keys:
        try:
            with _lock:
                _use_project(k)
                total += expire_seedlings()
        except Exception:
            pass
    return total


def _expiry_loop():
    while True:
        time.sleep(24 * 3600)
        try:
            expire_all()
        except Exception:
            pass


if __name__ == "__main__":
    main()
