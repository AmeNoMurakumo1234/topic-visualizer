# Export / Import / Reconcile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the sqlite backend a git-committable topic tree (`.topics/<slug>.json`), an additive+idempotent importer that returns a reconcile worklist, a `topic_merge` primitive that folds one topic into another, and a `topics-reconcile` skill that drives the merge/link/leave judgment.

**Architecture:** Four thin store functions in `server.py` (`export_topics`, `import_topics`, `merge_topics`, `find_duplicates`) plus an `expire_merged` sweep, each exposed over HTTP and mirrored as MCP tools in `mcp_tools.py`. Import is additive and dumb-but-safe; the intelligence lives in a new skill, not in code. A merged topic is soft-deleted (state `pruned` + a new `merged_into` column) and hard-removed after 14 days by the prune sweep. Spec: `docs/2026-07-12-export-import-reconcile-design.md`.

**Tech Stack:** Python 3 stdlib only (sqlite3, http.server, json, hashlib, pathlib). No new dependencies. Tests use `unittest` + the existing end-to-end harness that starts the real server on a temp DB.

## Global Constraints

- **Stdlib only.** No new third-party imports anywhere. (CHARTER: zero heavy deps.)
- **Version 0.8.0** (minor bump: new tools + new skill). Update `server.py` `VERSION`, `plugin/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `plugin/CHANGELOG.md`, and the tool lists in `plugin.json`'s description + `plugin/server/README.md`.
- **Author identity:** `Ame No Murakumo` only. No personal names, machine paths, business names, or project identifiers anywhere — including test data. Test topics use generic domain words (`auth`, `the API`, `widget`, `caching`).
- **Locking discipline:** every store mutation runs inside `with _lock:` (the reentrant `RLock`); error returns go through `_fail(msg)` which rolls back first. The pinned connection is the module global `_conn`.
- **Byte-stable export:** per-topic files serialize with `json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"`. Files carry only immutable fields (no `touched_at`) so re-exporting unchanged content produces identical bytes.
- **Both backends:** sqlite (`ServerBackend`) gets the full feature; `BoardBackend` gets read-only `export` + additive `import_`, and returns a clear "not supported" for `merge`.
- **Commit per task** with the `Murakumo <murikumo1234@gmail.com>` author (matches existing plugin history): `git -c user.name="Murakumo" -c user.email="murikumo1234@gmail.com" commit`.
- **Test commands run from** `plugin/server/`: `python test_server.py` and `python test_mcp.py`.

---

### Task 1: Schema — the `merged_into` tombstone column

**Files:**
- Modify: `plugin/server/schema.sql` (topic table)
- Modify: `plugin/server/server.py` (`open_db`, add `_ensure_columns`)
- Test: `plugin/server/test_server.py` (new `test_20_merged_into_column_migrates`)

**Interfaces:**
- Produces: a `topic.merged_into TEXT` column (NULL for live topics; set to the survivor's slug on a merge tombstone). New DBs get it from `schema.sql`; existing DBs get it via an idempotent `ALTER` in `open_db`.

- [ ] **Step 1: Write the failing test**

Add to `plugin/server/test_server.py` (a DIRECT test, like `test_18` — imports `server`, no HTTP):

```python
    def test_20_merged_into_column_migrates(self):
        import sys as _sys, tempfile as _tf
        _sys.path.insert(0, str(HERE))
        import server as srv
        # a fresh DB has the column (schema.sql)
        with _tf.TemporaryDirectory() as d:
            conn = srv.open_db(str(Path(d) / "fresh.db"))
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(topic)")}
            self.assertIn("merged_into", cols, "fresh schema carries merged_into")
            conn.close()
            # a legacy DB created WITHOUT the column gets it added idempotently
            import sqlite3 as _sql
            legacy = str(Path(d) / "legacy.db")
            c0 = _sql.connect(legacy)
            c0.execute("CREATE TABLE topic (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, "
                       "title TEXT NOT NULL, body TEXT DEFAULT '', state TEXT DEFAULT 'open', "
                       "priority TEXT DEFAULT 'normal', created_by TEXT NOT NULL DEFAULT 'x')")
            c0.commit(); c0.close()
            conn2 = srv.open_db(legacy)               # open_db must ALTER it in
            cols2 = {r["name"] for r in conn2.execute("PRAGMA table_info(topic)")}
            self.assertIn("merged_into", cols2, "open_db migrates a legacy DB")
            conn2.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_server.py SeamTests.test_20_merged_into_column_migrates`
Expected: FAIL — `merged_into` not in a legacy DB (and possibly fresh, before schema edit).

- [ ] **Step 3: Add the column to `schema.sql`**

In `plugin/server/schema.sql`, inside `CREATE TABLE IF NOT EXISTS topic`, add after the `state_note TEXT` line (the last column, before the closing `)`):

```sql
  state_note       TEXT,
  merged_into      TEXT          -- survivor slug when this topic was folded away (a merge
                                 -- tombstone: state='pruned' + merged_into set; prune sweep
                                 -- hard-removes it after 14 days)
```

(Change the existing `state_note TEXT` line to end with a comma, then add the `merged_into` line.)

- [ ] **Step 4: Add the idempotent migration in `server.py`**

In `plugin/server/server.py`, add this function just above `open_db` (near line 200):

```python
def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Idempotent migration for DBs created before a column existed. CREATE TABLE
    IF NOT EXISTS never alters an existing table, so additive columns are added here."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(topic)")}
    if "merged_into" not in cols:
        conn.execute("ALTER TABLE topic ADD COLUMN merged_into TEXT")
```

Then in `open_db`, call it after the schema script runs. Change:

```python
    conn.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    conn.commit()
    return conn
```

to:

```python
    conn.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
    _ensure_columns(conn)
    conn.commit()
    return conn
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python test_server.py SeamTests.test_20_merged_into_column_migrates`
Expected: PASS.

- [ ] **Step 6: Run the full server suite (no regressions)**

Run: `python test_server.py`
Expected: all tests PASS (the added column is nullable and unreferenced by existing queries).

- [ ] **Step 7: Commit**

```bash
git add plugin/server/schema.sql plugin/server/test_server.py
git -c user.name="Murakumo" -c user.email="murikumo1234@gmail.com" commit -m "feat(schema): add merged_into tombstone column + idempotent migration"
```

---

### Task 2: `export_topics` — write the per-topic dir + HTTP route

> **Amendment (2026-07-12, execution):** the brief's illustrative code wrote `index.json`'s
> `source_project` from the `_default_project` global, which mislabels the index for any
> non-default project (the HTTP route repoints `_conn` via `_use_project(key)` but never
> `_default_project`). Fixed during execution (commit `d36d6a5`): `export_topics` gained a
> `project=None` kwarg (defaults to `_default_project` for non-request callers), the route
> captures `key = _use_project(key)` and passes `project=key`, and `test_21` asserts
> `index["source_project"] == proj`. The MCP fallback keeps calling it positionally
> (`export_topics(dir, mode, scope)`), which is unaffected by the trailing kwarg.

**Files:**
- Modify: `plugin/server/server.py` (add `_content_hash`, `_topic_export_dict`, `_subtree_slugs`, `export_topics`; add POST route)
- Test: `plugin/server/test_server.py` (new `test_21_export_writes_stable_dir`)

**Interfaces:**
- Produces:
  - `_content_hash(title, body, state, priority, parents, links) -> str` — sha1 hex over content (not timestamps); `parents` = list of parent slugs, `links` = list of `"kind:ref"` strings; both sorted internally.
  - `export_topics(dir=None, mode="mirror", scope=None) -> dict` returning `{"dir","written","deleted","count","mode"}`. Default `dir` = `<repo-root>/.topics`. `mode` ∈ {`mirror`,`snapshot`}; mirror deletes stale `*.json`. `scope` = `None` (all live) | `"critical"` | a slug (subtree).
- Consumes: `_load_topics()`, `_repo_root()`, `_default_project` (all existing in `server.py`).

- [ ] **Step 1: Write the failing test**

Add to `plugin/server/test_server.py` (end-to-end via HTTP; writes to the class temp dir, never the repo):

```python
    def test_21_export_writes_stable_dir(self):
        proj = "exp1"
        call(f"/api/topics?project={proj}", {"actor": "ai", "topics": [
            {"title": "auth: session expiry policy (~30 min)", "body": "THE QUESTION: idle vs absolute?"},
            {"title": "auth: refresh token rotation", "body": "THE QUESTION: rotate on every use?"}]})
        out = str(Path(self.tmp.name) / "export1")
        r = call(f"/api/topics/export?project={proj}", {"dir": out, "mode": "mirror"})
        self.assertEqual(r["count"], 2)
        files = sorted(p.name for p in Path(out).glob("*.json"))
        self.assertIn("index.json", files)
        self.assertEqual(len([f for f in files if f != "index.json"]), 2)
        # byte-stable: a second export of unchanged content rewrites identical bytes
        topic_file = next(p for p in Path(out).glob("*.json") if p.name != "index.json")
        first = topic_file.read_bytes()
        call(f"/api/topics/export?project={proj}", {"dir": out, "mode": "mirror"})
        self.assertEqual(topic_file.read_bytes(), first, "unchanged topic -> identical bytes")
        # mirror deletes a file whose topic is gone: prune one, re-export
        gone_slug = topic_file.stem
        call(f"/api/topics/{gone_slug}/state?project={proj}", {"actor": "ai", "state": "pruned"})
        r2 = call(f"/api/topics/export?project={proj}", {"dir": out, "mode": "mirror"})
        self.assertEqual(r2["deleted"], 1, "mirror removes the pruned topic's file")
        self.assertFalse((Path(out) / f"{gone_slug}.json").exists())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_server.py SeamTests.test_21_export_writes_stable_dir`
Expected: FAIL — 404 / `export` route not defined.

- [ ] **Step 3: Add the export functions**

In `plugin/server/server.py`, add just below `list_topics` (near line 326):

```python
def _content_hash(title, body, state, priority, parents, links) -> str:
    """Stable identity of a topic's CONTENT (not its timestamps). Import compares this to
    decide 'same topic, unchanged'. parents/links are order-independent."""
    payload = json.dumps(
        {"title": title, "body": body, "state": state, "priority": priority,
         "parents": sorted(parents), "links": sorted(links)},
        sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _topic_export_dict(t: dict) -> dict:
    """One live topic (from _load_topics) -> its portable, byte-stable export record.
    Immutable fields only (no touched_at) so unchanged content re-exports identically."""
    parents = ([t["parent_slug"]] if t.get("parent_slug") else []) + \
              [x["slug"] for x in t.get("extra_parents", [])]
    links = [{"kind": l["kind"], "ref": l["ref"], "note": l.get("note", "")}
             for l in t.get("links", [])]
    return {
        "slug": t["slug"], "title": t["title"], "body": t["body"],
        "state": t["state"], "priority": t["priority"], "parents": parents,
        "links": links, "provenance": t.get("provenance", ""),
        "created_at": t.get("created_at", ""),
        "content_hash": _content_hash(t["title"], t["body"], t["state"], t["priority"],
                                      parents, [f'{l["kind"]}:{l["ref"]}' for l in links]),
    }


def _subtree_slugs(topics: list[dict], root: str) -> set:
    """root + every descendant (primary + extra-parent edges), for a scoped export."""
    bychild: dict = {}
    for t in topics:
        for p in ([t["parent_slug"]] if t.get("parent_slug") else []) + \
                 [x["slug"] for x in t.get("extra_parents", [])]:
            bychild.setdefault(p, []).append(t["slug"])
    out, fr = {root}, [root]
    while fr:
        for c in bychild.get(fr.pop(), []):
            if c not in out:
                out.add(c); fr.append(c)
    return out


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def export_topics(dir=None, mode="mirror", scope=None) -> dict:
    """Write the live tree to a directory of per-topic files (git-committable). mirror
    (default) makes the dir EXACTLY match the store (deletes stale files); snapshot only
    adds. scope: None=all live | 'critical' | a slug (that subtree)."""
    dest = Path(dir).expanduser() if dir else Path(_repo_root() or Path.cwd()) / ".topics"
    dest.mkdir(parents=True, exist_ok=True)
    topics = _load_topics()
    if scope == "critical":
        topics = [t for t in topics if t["priority"] == "critical"]
    elif scope:
        keep = _subtree_slugs(topics, scope)
        topics = [t for t in topics if t["slug"] in keep]
    exported = {}
    for t in topics:
        obj = _topic_export_dict(t)
        exported[t["slug"]] = obj
        _write_json(dest / f'{t["slug"]}.json', obj)
    _write_json(dest / "index.json",
                {"schema_version": 1, "source_project": _default_project,
                 "count": len(exported), "topics": sorted(exported)})
    deleted = 0
    if mode == "mirror":
        for f in dest.glob("*.json"):
            if f.name != "index.json" and f.stem not in exported:
                f.unlink(); deleted += 1
    return {"dir": str(dest), "written": len(exported), "deleted": deleted,
            "count": len(exported), "mode": mode}
```

- [ ] **Step 4: Wire the POST route**

In `plugin/server/server.py`, in `_post`, immediately after the `if u.path == "/api/topics":` add block (the one that returns `add_topics`, near line 1028), add:

```python
            if u.path == "/api/topics/export":
                return self._json(200, export_topics(
                    body.get("dir"), str(body.get("mode") or "mirror"), body.get("scope")))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python test_server.py SeamTests.test_21_export_writes_stable_dir`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/server/server.py plugin/server/test_server.py
git -c user.name="Murakumo" -c user.email="murikumo1234@gmail.com" commit -m "feat(export): topic_export writes a byte-stable per-topic dir (mirror/snapshot)"
```

---

### Task 3: `import_topics` — additive, idempotent, disambiguating + route

**Files:**
- Modify: `plugin/server/server.py` (add `_insert_imported`, `_wire_imported`, `_local_parent_slugs`, `_local_link_keys`, `_within_days`, `import_topics`; add POST route). NOTE: `import_topics` calls `_worklist_for`/`find_duplicates` (Task 6) — add a temporary stub now, replaced in Task 6.
- Test: `plugin/server/test_server.py` (new `test_22_import_roundtrip_and_idempotent`)

**Interfaces:**
- Consumes: `_content_hash`, `_load_topics`, `_repo_root`, `_event`, `MERGED_TOMBSTONE_DAYS` (Task 5 — add the constant here if not yet present; Task 5 keeps it).
- Produces: `import_topics(dir=None) -> dict` returning `{"added","skipped","disambiguated","bad","worklist"}`. Idempotent: identical `content_hash` → skip. Slug collision with different content → import under `<slug>-<hash6>`. A within-14-day merged tombstone slug is not resurrected.

- [ ] **Step 1: Write the failing test**

Add to `plugin/server/test_server.py`:

```python
    def test_22_import_roundtrip_and_idempotent(self):
        src = "imp_src"
        call(f"/api/topics?project={src}", {"actor": "ai", "topics": [
            {"title": "caching: eviction policy (~20 min)", "body": "THE QUESTION: LRU or LFU?"}]})
        parent = call(f"/api/topics?project={src}")["topics"][0]["slug"]
        call(f"/api/topics?project={src}", {"actor": "ai", "topics": [
            {"title": "caching: cold-start warmup", "body": "THE QUESTION: preload what?",
             "parent_slug": parent}]})
        out = str(Path(self.tmp.name) / "imp_export")
        call(f"/api/topics/export?project={src}", {"dir": out, "mode": "mirror"})
        # import into a DIFFERENT project -> tree reconstructed, parent edge preserved
        dst = "imp_dst"
        r = call(f"/api/topics/import?project={dst}", {"dir": out})
        self.assertEqual(r["added"], 2, r)
        got = {t["title"]: t for t in call(f"/api/topics?project={dst}")["topics"]}
        self.assertIn("caching: eviction policy (~20 min)", got)
        child = got["caching: cold-start warmup"]
        parent_titles = {t["slug"]: t["title"] for t in call(f"/api/topics?project={dst}")["topics"]}
        self.assertEqual(parent_titles.get(child["parent_slug"]),
                         "caching: eviction policy (~20 min)", "parent edge survived import")
        # idempotent: re-import adds nothing
        r2 = call(f"/api/topics/import?project={dst}", {"dir": out})
        self.assertEqual(r2["added"], 0, "unchanged re-import is a no-op")
        self.assertGreaterEqual(r2["skipped"], 2)
        # collision with DIFFERENT content -> disambiguated, not overwritten
        target = child["slug"]
        import json as _json
        pf = Path(out) / f"{target}.json"
        obj = _json.loads(pf.read_text(encoding="utf-8"))
        obj["body"] = "THE QUESTION: totally different body now"
        obj.pop("content_hash", None)
        pf.write_text(_json.dumps(obj), encoding="utf-8")
        r3 = call(f"/api/topics/import?project={dst}", {"dir": out})
        self.assertTrue(r3["disambiguated"], "different-content collision disambiguates")
        self.assertTrue(r3["disambiguated"][0]["as"].startswith(target + "-"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_server.py SeamTests.test_22_import_roundtrip_and_idempotent`
Expected: FAIL — `import` route not defined.

- [ ] **Step 3: Add the import helpers + `import_topics` (with a temp worklist stub)**

In `plugin/server/server.py`, add near the export functions. First, the constant (kept by Task 5) if not present:

```python
MERGED_TOMBSTONE_DAYS = 14      # a merge tombstone is hard-removed by the prune sweep after this
```

Then the helpers and importer:

```python
def _local_parent_slugs(tid: int) -> list:
    out = []
    r = _conn.execute("SELECT p.slug s FROM topic t LEFT JOIN topic p ON p.id=t.parent_id "
                      "WHERE t.id=?", (tid,)).fetchone()
    if r and r["s"]:
        out.append(r["s"])
    out += [x["slug"] for x in _conn.execute(
        "SELECT p.slug slug FROM topic_parent tp JOIN topic p ON p.id=tp.parent_id "
        "WHERE tp.topic_id=?", (tid,))]
    return out


def _local_link_keys(tid: int) -> list:
    return [f'{x["kind"]}:{x["ref"]}' for x in _conn.execute(
        "SELECT kind, ref FROM topic_link WHERE topic_id=?", (tid,))]


def _within_days(ts, days) -> bool:
    if not ts:
        return False
    r = _conn.execute("SELECT julianday('now') - julianday(?) d", (ts,)).fetchone()
    return r["d"] is not None and r["d"] <= days


def _insert_imported(obj: dict, slug: str) -> int:
    state = obj.get("state") if obj.get("state") in ("seedling", "open", "discussed") else "open"
    _conn.execute(
        """INSERT INTO topic (slug, title, body, state, priority, created_by,
                              created_at, touched_at, provenance)
           VALUES (?,?,?,?,?,?, COALESCE(NULLIF(?, ''), datetime('now')),
                   datetime('now'), ?)""",
        (slug, obj["title"], obj.get("body", ""), state,
         "critical" if obj.get("priority") == "critical" else "normal",
         "import", obj.get("created_at", ""), obj.get("provenance", "")))
    tid = _conn.execute("SELECT id FROM topic WHERE slug=?", (slug,)).fetchone()["id"]
    _event(tid, "imported", "import", f'from {obj["slug"]}')
    return tid


def _wire_imported(obj: dict, local_slug: str, remap: dict) -> None:
    tid = _conn.execute("SELECT id FROM topic WHERE slug=?", (local_slug,)).fetchone()["id"]

    def resolve(pslug):
        row = _conn.execute("SELECT id FROM topic WHERE slug=?",
                            (remap.get(pslug, pslug),)).fetchone()
        return row["id"] if row else None

    for i, pslug in enumerate(obj.get("parents") or []):
        pid = resolve(pslug)
        if pid is None or pid == tid:
            continue
        if i == 0:
            _conn.execute("UPDATE topic SET parent_id=? WHERE id=?", (pid, tid))
        else:
            try:
                _conn.execute("INSERT INTO topic_parent (topic_id, parent_id, note, added_by) "
                              "VALUES (?,?,?,?)", (tid, pid, "", "import"))
            except sqlite3.IntegrityError:
                pass
    for l in obj.get("links") or []:
        if isinstance(l, dict) and l.get("kind") in ("decision", "work_item", "document"):
            _conn.execute("INSERT INTO topic_link (topic_id, kind, ref, note) VALUES (?,?,?,?)",
                          (tid, l["kind"], str(l.get("ref") or ""), str(l.get("note") or "")))


def _worklist_for(slugs: set) -> list:
    return []          # TEMPORARY stub; Task 6 replaces this with find_duplicates filtering


def import_topics(dir=None) -> dict:
    """Additively merge a .topics dir into this project's store. Idempotent (identical
    content_hash -> skip); a slug collision with DIFFERENT content imports under a
    disambiguated slug; a within-window merge tombstone is not resurrected. Returns the
    reconcile worklist (candidate near-dup pairs touching the imported topics)."""
    src = Path(dir).expanduser() if dir else Path(_repo_root() or Path.cwd()) / ".topics"
    if not src.is_dir():
        return {"error": f"no import dir at {src}"}
    incoming, bad = [], []
    for f in sorted(p for p in src.glob("*.json") if p.name != "index.json"):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
            if not obj.get("slug") or not obj.get("title"):
                raise ValueError("missing slug/title")
            incoming.append(obj)
        except Exception as e:
            bad.append({"file": f.name, "error": str(e)})
    added, skipped, disambiguated, remap = [], [], [], {}
    with _lock:
        for obj in incoming:
            slug = obj["slug"]
            file_hash = obj.get("content_hash") or _content_hash(
                obj["title"], obj.get("body", ""), obj.get("state", "open"),
                obj.get("priority", "normal"),
                obj.get("parents") or [],
                [f'{l.get("kind")}:{l.get("ref")}' for l in (obj.get("links") or [])])
            local = _conn.execute(
                "SELECT id, title, body, state, priority, merged_into, state_changed_at "
                "FROM topic WHERE slug=?", (slug,)).fetchone()
            if local is not None:
                lh = _content_hash(local["title"], local["body"], local["state"],
                                   local["priority"], _local_parent_slugs(local["id"]),
                                   _local_link_keys(local["id"]))
                if lh == file_hash:
                    skipped.append(slug); remap[slug] = slug; continue
                if local["merged_into"] and _within_days(
                        local["state_changed_at"], MERGED_TOMBSTONE_DAYS):
                    skipped.append(slug); remap[slug] = slug; continue
                newslug, n = f"{slug}-{file_hash[:6]}", 1
                while _conn.execute("SELECT 1 FROM topic WHERE slug=?", (newslug,)).fetchone():
                    n += 1; newslug = f"{slug}-{file_hash[:6]}-{n}"
                _insert_imported(obj, newslug)
                remap[slug] = newslug
                disambiguated.append({"from": slug, "as": newslug})
            else:
                _insert_imported(obj, slug)
                remap[slug] = slug; added.append(slug)
        wired = set(added) | {d["as"] for d in disambiguated}
        for obj in incoming:
            local_slug = remap.get(obj["slug"])
            if local_slug in wired:
                _wire_imported(obj, local_slug, remap)
        _conn.commit()
    return {"added": len(added), "skipped": len(skipped),
            "disambiguated": disambiguated, "bad": bad,
            "worklist": _worklist_for(set(added) | {d["as"] for d in disambiguated})}
```

- [ ] **Step 4: Wire the POST route**

In `_post`, right after the export route added in Task 2:

```python
            if u.path == "/api/topics/import":
                return self._json(200, import_topics(body.get("dir")))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python test_server.py SeamTests.test_22_import_roundtrip_and_idempotent`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `python test_server.py`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add plugin/server/server.py plugin/server/test_server.py
git -c user.name="Murakumo" -c user.email="murikumo1234@gmail.com" commit -m "feat(import): additive+idempotent topic_import with slug-collision disambiguation"
```

---

### Task 4: `merge_topics` — fold B into A + route

**Files:**
- Modify: `plugin/server/server.py` (add `_descendants`, `_STATE_RANK`, `merge_topics`; add POST route)
- Test: `plugin/server/test_server.py` (new `test_23_merge_folds_and_guards`)

**Interfaces:**
- Consumes: `_lock`, `_conn`, `_fail`, `_event`.
- Produces: `merge_topics(into_slug, from_slug, actor, body=None) -> dict` returning `{"ok","into","from","moved_children"}` or `{"error": ...}`. Re-parents `from`'s children onto `into`, transfers `from`'s parent/extra edges + conversions, tombstones `from` (state `pruned` + `merged_into=into_slug`), and takes the stronger priority/state. Rejects self-merge and merging an ancestor into its own descendant.

- [ ] **Step 1: Write the failing test**

Add to `plugin/server/test_server.py`:

```python
    def test_23_merge_folds_and_guards(self):
        proj = "mrg"
        call(f"/api/topics?project={proj}", {"actor": "ai", "topics": [
            {"title": "widget: the survivor", "body": "keep me", "priority": "critical"},
            {"title": "widget: the duplicate", "body": "fold me"}]})
        rows = call(f"/api/topics?project={proj}")["topics"]
        into = next(t["slug"] for t in rows if t["title"] == "widget: the survivor")
        frm = next(t["slug"] for t in rows if t["title"] == "widget: the duplicate")
        # give `from` a child so re-parenting is observable
        call(f"/api/topics?project={proj}", {"actor": "ai", "topics": [
            {"title": "widget: a child of the duplicate", "parent_slug": frm}]})
        child = next(t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]
                     if t["title"] == "widget: a child of the duplicate")
        # self-merge refused
        self.assertIn("error", call(f"/api/topics/merge?project={proj}", {"into": into, "from": into}))
        # merge with a rewritten combined body
        r = call(f"/api/topics/merge?project={proj}",
                 {"into": into, "from": frm, "body": "keep me + fold me, combined"})
        self.assertTrue(r.get("ok"), r)
        live = {t["slug"]: t for t in call(f"/api/topics?project={proj}")["topics"]}
        self.assertNotIn(frm, live, "the folded topic leaves the live tree")
        self.assertIn(into, live)
        self.assertEqual(live[child]["parent_slug"], into, "child re-parented to the survivor")
        self.assertEqual(live[into]["body"], "keep me + fold me, combined", "body override applied")
        self.assertEqual(live[into]["priority"], "critical", "critical survivorship")
        arch = {t["slug"] for t in call(f"/api/topics?project={proj}&include=archive")["topics"]}
        self.assertIn(frm, arch, "the tombstone is recoverable in the archive")
        # cycle guard: merging an ancestor into its own descendant is refused
        call(f"/api/topics?project={proj}", {"actor": "ai", "topics": [
            {"title": "widget: ancestor"}]})
        anc = next(t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]
                   if t["title"] == "widget: ancestor")
        call(f"/api/topics?project={proj}", {"actor": "ai", "topics": [
            {"title": "widget: descendant", "parent_slug": anc}]})
        desc = next(t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]
                    if t["title"] == "widget: descendant")
        bad = call(f"/api/topics/merge?project={proj}", {"into": desc, "from": anc})
        self.assertIn("cycle", str(bad.get("error", "")))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_server.py SeamTests.test_23_merge_folds_and_guards`
Expected: FAIL — `merge` route not defined.

- [ ] **Step 3: Add `_descendants`, `_STATE_RANK`, and `merge_topics`**

In `plugin/server/server.py`, add below the import functions:

```python
_STATE_RANK = {"seedling": 1, "discussed": 2, "open": 3}


def _descendants(tid: int) -> set:
    """Every topic reachable downward from tid via primary + extra-parent edges."""
    out, fr = set(), [tid]
    while fr:
        cur = fr.pop()
        kids = [r["id"] for r in _conn.execute("SELECT id FROM topic WHERE parent_id=?", (cur,))]
        kids += [r["topic_id"] for r in _conn.execute(
            "SELECT topic_id FROM topic_parent WHERE parent_id=?", (cur,))]
        for k in kids:
            if k not in out:
                out.add(k); fr.append(k)
    return out


def merge_topics(into_slug: str, from_slug: str, actor: str, body: str | None = None) -> dict:
    """Fold `from` into `into`: re-parent from's children, transfer its parent/extra edges
    and conversions to into, take the stronger priority/state, optionally rewrite into's
    body, then tombstone from (state='pruned', merged_into=into). Reversible via the
    archive until the 14-day sweep. Refuses self-merge and ancestor-into-descendant."""
    with _lock:
        into = _conn.execute("SELECT id, state, priority FROM topic WHERE slug=?",
                             (into_slug,)).fetchone()
        frm = _conn.execute("SELECT id, state, priority FROM topic WHERE slug=?",
                            (from_slug,)).fetchone()
        if not into or not frm:
            return _fail("topic not found")
        if into["id"] == frm["id"]:
            return _fail("cannot merge a topic into itself")
        into_id, from_id = into["id"], frm["id"]
        if into_id in _descendants(from_id):
            return _fail("cycle: cannot merge an ancestor into its own descendant")
        into_desc = _descendants(into_id) | {into_id}
        # 1. children of `from` -> children of `into` (drop a now-redundant extra edge)
        moved = 0
        for c in _conn.execute("SELECT id FROM topic WHERE parent_id=?", (from_id,)).fetchall():
            _conn.execute("DELETE FROM topic_parent WHERE topic_id=? AND parent_id=?",
                          (c["id"], into_id))
            _conn.execute("UPDATE topic SET parent_id=? WHERE id=?", (into_id, c["id"]))
            moved += 1
        # 2. extra-parent edges where `from` is the PARENT -> repoint to `into`
        for e in _conn.execute("SELECT topic_id FROM topic_parent WHERE parent_id=?",
                               (from_id,)).fetchall():
            tid = e["topic_id"]
            _conn.execute("DELETE FROM topic_parent WHERE topic_id=? AND parent_id=?",
                          (tid, from_id))
            prim = _conn.execute("SELECT parent_id FROM topic WHERE id=?", (tid,)).fetchone()["parent_id"]
            dup = _conn.execute("SELECT 1 FROM topic_parent WHERE topic_id=? AND parent_id=?",
                                (tid, into_id)).fetchone()
            if tid != into_id and prim != into_id and not dup:
                _conn.execute("INSERT INTO topic_parent (topic_id, parent_id, note, added_by) "
                              "VALUES (?,?,?,?)", (tid, into_id, "", actor))
        # 3. parents of `from` -> extra parents of `into` (dedup, skip self/cycle/existing)
        fparents = [r["parent_id"] for r in _conn.execute(
            "SELECT parent_id FROM topic WHERE id=? AND parent_id IS NOT NULL", (from_id,))]
        fparents += [r["parent_id"] for r in _conn.execute(
            "SELECT parent_id FROM topic_parent WHERE topic_id=?", (from_id,))]
        into_prim = _conn.execute("SELECT parent_id FROM topic WHERE id=?", (into_id,)).fetchone()["parent_id"]
        for pid in fparents:
            if pid in into_desc or pid == into_prim:
                continue
            if _conn.execute("SELECT 1 FROM topic_parent WHERE topic_id=? AND parent_id=?",
                             (into_id, pid)).fetchone():
                continue
            try:
                _conn.execute("INSERT INTO topic_parent (topic_id, parent_id, note, added_by) "
                              "VALUES (?,?,?,?)", (into_id, pid, "merged avenue", actor))
            except sqlite3.IntegrityError:
                pass
        # 4. conversions transfer to the survivor; drop from's own leftover edges
        _conn.execute("UPDATE topic_link SET topic_id=? WHERE topic_id=?", (into_id, from_id))
        _conn.execute("DELETE FROM topic_parent WHERE topic_id=?", (from_id,))
        # 5. survivor body / priority / state
        if body is not None:
            _conn.execute("UPDATE topic SET body=? WHERE id=?", (body, into_id))
        if frm["priority"] == "critical":
            _conn.execute("UPDATE topic SET priority='critical' WHERE id=?", (into_id,))
        if _STATE_RANK.get(frm["state"], 0) > _STATE_RANK.get(into["state"], 0):
            _conn.execute("UPDATE topic SET state=? WHERE id=?", (frm["state"], into_id))
        _conn.execute("UPDATE topic SET touched_at=datetime('now') WHERE id=?", (into_id,))
        # 6. tombstone `from`
        _conn.execute(
            "UPDATE topic SET state='pruned', merged_into=?, state_changed_at=datetime('now'), "
            "state_changed_by=?, state_note=? WHERE id=?",
            (into_slug, actor, f"merged into {into_slug}", from_id))
        _event(into_id, "merged", actor, f"absorbed {from_slug}")
        _event(from_id, "merged", actor, f"into {into_slug}")
        _conn.commit()
    return {"ok": True, "into": into_slug, "from": from_slug, "moved_children": moved}
```

- [ ] **Step 4: Wire the POST route**

In `_post`, after the import route:

```python
            if u.path == "/api/topics/merge":
                return self._json(200, merge_topics(
                    str(body.get("into") or ""), str(body.get("from") or ""), actor,
                    body.get("body")))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python test_server.py SeamTests.test_23_merge_folds_and_guards`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `python test_server.py`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add plugin/server/server.py plugin/server/test_server.py
git -c user.name="Murakumo" -c user.email="murikumo1234@gmail.com" commit -m "feat(merge): topic_merge folds a topic into another (reparent, transfer, tombstone, guards)"
```

---

### Task 5: `expire_merged` sweep + wire into `expire_all`

**Files:**
- Modify: `plugin/server/server.py` (add `expire_merged`; call it in `expire_all`)
- Test: `plugin/server/test_server.py` (new `test_24_merged_tombstones_age_out`)

**Interfaces:**
- Consumes: `_lock`, `_conn`, `MERGED_TOMBSTONE_DAYS` (added in Task 3).
- Produces: `expire_merged() -> int` — hard-deletes merge tombstones (`merged_into IS NOT NULL`) whose `state_changed_at` is older than 14 days, cascading their `topic_event`/`topic_link`/`topic_parent` rows. Called per-project inside `expire_all`.

- [ ] **Step 1: Write the failing test (direct, with a hand-aged tombstone)**

Add to `plugin/server/test_server.py`:

```python
    def test_24_merged_tombstones_age_out(self):
        import sys as _sys, tempfile as _tf
        _sys.path.insert(0, str(HERE))
        import server as srv
        with _tf.TemporaryDirectory() as d:
            srv._conn = srv.open_db(str(Path(d) / "age.db"))
            srv._conn.execute(
                "INSERT INTO topic (slug, title, state, created_by, merged_into, "
                "state_changed_at) VALUES (?,?,?,?,?, datetime('now','-20 days'))",
                ("old-tomb", "old", "pruned", "ai", "survivor"))
            srv._conn.execute(
                "INSERT INTO topic (slug, title, state, created_by, merged_into, "
                "state_changed_at) VALUES (?,?,?,?,?, datetime('now','-3 days'))",
                ("young-tomb", "young", "pruned", "ai", "survivor"))
            srv._conn.commit()
            n = srv.expire_merged()
            self.assertEqual(n, 1, "only the >14d tombstone is swept")
            rows = {r["slug"] for r in srv._conn.execute("SELECT slug FROM topic")}
            self.assertNotIn("old-tomb", rows, "aged tombstone hard-deleted")
            self.assertIn("young-tomb", rows, "young tombstone kept for undo")
            srv._conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_server.py SeamTests.test_24_merged_tombstones_age_out`
Expected: FAIL — `expire_merged` not defined.

- [ ] **Step 3: Add `expire_merged` and wire it into `expire_all`**

In `plugin/server/server.py`, add next to `expire_seedlings`:

```python
def expire_merged() -> int:
    """Hard-remove merge tombstones older than MERGED_TOMBSTONE_DAYS - a merged topic is
    deliberately dead (folded into its survivor), so it ages faster than a seedling and is
    then gone for good, with its history/edges cascaded."""
    with _lock:
        rows = _conn.execute(
            "SELECT id FROM topic WHERE merged_into IS NOT NULL AND "
            "julianday('now') - julianday(state_changed_at) > ?",
            (MERGED_TOMBSTONE_DAYS,)).fetchall()
        for r in rows:
            tid = r["id"]
            _conn.execute("DELETE FROM topic_event WHERE topic_id=?", (tid,))
            _conn.execute("DELETE FROM topic_link WHERE topic_id=?", (tid,))
            _conn.execute("DELETE FROM topic_parent WHERE topic_id=? OR parent_id=?", (tid, tid))
            _conn.execute("DELETE FROM topic WHERE id=?", (tid,))
        _conn.commit()
    return len(rows)
```

Then in `expire_all`, change the per-project body from:

```python
            with _lock:
                _use_project(k)
                total += expire_seedlings()
```

to:

```python
            with _lock:
                _use_project(k)
                total += expire_seedlings()
                total += expire_merged()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python test_server.py SeamTests.test_24_merged_tombstones_age_out`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python test_server.py`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/server/server.py plugin/server/test_server.py
git -c user.name="Murakumo" -c user.email="murikumo1234@gmail.com" commit -m "feat(sweep): expire_merged hard-removes 14-day-old merge tombstones"
```

---

### Task 6: `find_duplicates` + real import worklist + route

**Files:**
- Modify: `plugin/server/server.py` (add `find_duplicates`; replace the `_worklist_for` stub; add GET route)
- Test: `plugin/server/test_server.py` (new `test_25_duplicates_and_worklist`)

**Interfaces:**
- Consumes: `_load_topics`, `near_duplicates_in`.
- Produces: `find_duplicates(min_band="kin") -> dict` returning `{"pairs":[{"a","b","score","mode","band"}], "count"}`, deduped and sorted by score. `_worklist_for(slugs)` now filters `find_duplicates` to pairs touching `slugs`.

- [ ] **Step 1: Write the failing test**

Add to `plugin/server/test_server.py`:

```python
    def test_25_duplicates_and_worklist(self):
        proj = "dup"
        call(f"/api/topics?project={proj}", {"actor": "ai", "topics": [
            {"title": "the API rate limit design question (~1 hour)",
             "body": "THE QUESTION: token bucket or fixed window?"},
            {"title": "designing the API rate limiter approach",
             "body": "THE QUESTION: token bucket versus fixed window for the API?"}]})
        d = call(f"/api/topics/duplicates?project={proj}")
        self.assertGreaterEqual(d["count"], 1, "the near-identical pair is surfaced")
        pair = d["pairs"][0]
        for k in ("a", "b", "score", "mode", "band"):
            self.assertIn(k, pair)
        # an import returns a worklist naming the freshly-imported near-dup
        out = str(Path(self.tmp.name) / "wl_export")
        call(f"/api/topics/export?project={proj}", {"dir": out, "mode": "mirror"})
        r = call(f"/api/topics/import?project=dup_target", {"dir": out})
        self.assertIn("worklist", r)
        self.assertTrue(isinstance(r["worklist"], list))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python test_server.py SeamTests.test_25_duplicates_and_worklist`
Expected: FAIL — `duplicates` route not defined (404).

- [ ] **Step 3: Add `find_duplicates` and replace the worklist stub**

In `plugin/server/server.py`, add:

```python
def find_duplicates(min_band="kin") -> dict:
    """Candidate near-duplicate PAIRS across the live tree - the reconcile worklist.
    Reuses the write-time dedup ranker (semantic when the embedder is up, keyword
    otherwise). min_band: 'weak' | 'kin' (default) | 'dup_likely'."""
    rank = {"weak": 0, "kin": 1, "dup_likely": 2}
    thr = rank.get(min_band, 1)
    topics = _load_topics()
    seen, pairs = set(), []
    for t in topics:
        others = [x for x in topics if x["slug"] != t["slug"]]
        for dpl in near_duplicates_in(t["title"], t["body"], others, limit=5):
            if rank.get(dpl.get("band", "weak"), 0) < thr:
                continue
            key = tuple(sorted((t["slug"], dpl["slug"])))
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"a": key[0], "b": key[1], "score": dpl["score"],
                          "mode": dpl["mode"], "band": dpl["band"]})
    pairs.sort(key=lambda p: -p["score"])
    return {"pairs": pairs, "count": len(pairs)}
```

Then REPLACE the temporary `_worklist_for` stub body (from Task 3) with:

```python
def _worklist_for(slugs: set) -> list:
    """The reconcile agenda after an import: candidate pairs touching the new topics."""
    return [p for p in find_duplicates().get("pairs", [])
            if p["a"] in slugs or p["b"] in slugs]
```

- [ ] **Step 4: Wire the GET route**

In `plugin/server/server.py`, in `_get`, inside the `if u.path.startswith("/api/topics"):` project-pinned block, add alongside the other `/api/topics/...` GETs (e.g. right after the `/api/topics/health` line):

```python
                if u.path == "/api/topics/duplicates":
                    return self._json(200, find_duplicates(qs.get("band", ["kin"])[0]))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python test_server.py SeamTests.test_25_duplicates_and_worklist`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `python test_server.py`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add plugin/server/server.py plugin/server/test_server.py
git -c user.name="Murakumo" -c user.email="murikumo1234@gmail.com" commit -m "feat(reconcile): find_duplicates worklist + wire it into import"
```

---

### Task 7: MCP tools — `topic_export/import/merge/duplicates` on both backends

**Files:**
- Modify: `plugin/server/mcp_tools.py` (ServerBackend + BoardBackend methods; 4 `TOOLS` entries; `_call` dispatch)
- Test: `plugin/server/test_mcp.py` (update handshake set; new `test_07_export_import_merge_duplicates`; new board-leg `test_03_board_export_and_merge_unsupported`)

**Interfaces:**
- Consumes: server functions from Task 2–6 (via HTTP or the direct fallback).
- Produces: MCP tools `topic_export` (`dir?`, `mode?`, `scope?`), `topic_import` (`dir?`), `topic_merge` (`into`, `from`, `body?`), `topic_duplicates` (`band?`). ServerBackend passes through / falls back to the store functions; BoardBackend does read-only `export` + additive `import_`, and returns a not-supported error for `merge`.

- [ ] **Step 1: Update the handshake test (failing) + add the MCP feature test**

In `plugin/server/test_mcp.py`, change the expected tool set in `test_01_handshake_and_list`:

```python
        self.assertEqual({t["name"] for t in tools},
                         {"topic_add", "topic_get", "topic_list", "topic_serve",
                          "topic_search", "topic_state", "topic_convert",
                          "topic_attach", "topic_groom_report",
                          "topic_export", "topic_import", "topic_merge", "topic_duplicates"})
```

Add a new test to `TestMCPServerBackendHTTP`:

```python
    def test_07_export_import_merge_duplicates(self):
        import tempfile as _tf
        out, _ = self.mcp.tool("topic_add", {"items": [
            {"title": "queue: retry backoff strategy", "body": "THE QUESTION: exp or jitter?",
             "state": "open"},
            {"title": "queue: retry backoff approach", "body": "THE QUESTION: exponential with jitter?",
             "state": "open"}]})
        a, b = [r["slug"] for r in out["results"]]
        # duplicates surfaces the near-identical pair
        dups, _ = self.mcp.tool("topic_duplicates", {})
        self.assertGreaterEqual(dups["count"], 1, dups)
        # export writes files to a temp dir (never the repo)
        with _tf.TemporaryDirectory() as d:
            ex, _ = self.mcp.tool("topic_export", {"dir": d, "mode": "mirror"})
            self.assertGreaterEqual(ex["count"], 2)
            im, _ = self.mcp.tool("topic_import", {"dir": d})
            self.assertIn("worklist", im)             # re-import of same store = idempotent
            self.assertEqual(im["added"], 0)
        # merge folds b into a
        mg, err = self.mcp.tool("topic_merge", {"into": a, "from": b})
        self.assertFalse(err, mg)
        self.assertTrue(mg.get("ok"), mg)
        g, _ = self.mcp.tool("topic_get", {"slug": b})
        self.assertTrue(g.get("error"), "the folded topic is no longer live")
```

- [ ] **Step 2: Run to verify failure**

Run: `python test_mcp.py TestMCPServerBackendHTTP.test_01_handshake_and_list`
Expected: FAIL — the four new names are missing from `tools/list`.

- [ ] **Step 3: Add the ServerBackend methods**

In `plugin/server/mcp_tools.py`, inside `class ServerBackend`, add after `groom`:

```python
    def export(self, dir=None, mode="mirror", scope=None):
        try:
            return _http("POST", f"{self.base}/api/topics/export",
                         self._p({"dir": dir, "mode": mode, "scope": scope}))
        except Unreachable:
            return self._fallback().export_topics(dir, mode, scope)

    def import_(self, dir=None):
        try:
            return _http("POST", f"{self.base}/api/topics/import", self._p({"dir": dir}))
        except Unreachable:
            return self._fallback().import_topics(dir)

    def merge(self, into, from_, body=None):
        try:
            return _http("POST", f"{self.base}/api/topics/merge",
                         self._p({"into": into, "from": from_, "body": body}))
        except Unreachable:
            return self._fallback().merge_topics(into, from_, ACTOR, body)

    def duplicates(self, band="kin"):
        try:
            return _http("GET", self._q(f"{self.base}/api/topics/duplicates?band={band}"))
        except Unreachable:
            return self._fallback().find_duplicates(band)
```

- [ ] **Step 4: Add the BoardBackend methods**

In `class BoardBackend`, add after `groom`:

```python
    def export(self, dir=None, mode="mirror", scope=None):
        from server import _content_hash
        dest = Path(dir).expanduser() if dir else Path.cwd() / ".topics"
        dest.mkdir(parents=True, exist_ok=True)
        topics = self._load()
        if scope == "critical":
            topics = [t for t in topics if t["priority"] == "critical"]
        exported = {}
        for t in topics:
            parents = ([t["parent_slug"]] if t.get("parent_slug") else []) + \
                      [x["slug"] for x in t.get("extra_parents", [])]
            obj = {"slug": t["slug"], "title": t["title"], "body": t["body"],
                   "state": t["state"], "priority": t["priority"], "parents": parents,
                   "links": [], "provenance": "", "created_at": t.get("created_at", ""),
                   "content_hash": _content_hash(t["title"], t["body"], t["state"],
                                                 t["priority"], parents, [])}
            exported[t["slug"]] = obj
            (dest / f'{t["slug"]}.json').write_text(
                json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8")
        (dest / "index.json").write_text(
            json.dumps({"schema_version": 1, "source_project": self.project,
                        "count": len(exported), "topics": sorted(exported)},
                       sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if mode == "mirror":
            for f in dest.glob("*.json"):
                if f.name != "index.json" and f.stem not in exported:
                    f.unlink()
        return {"dir": str(dest), "written": len(exported), "count": len(exported),
                "backend": "board"}

    def import_(self, dir=None):
        src = Path(dir).expanduser() if dir else Path.cwd() / ".topics"
        if not src.is_dir():
            return {"error": f"no import dir at {src}"}
        items = []
        for f in sorted(p for p in src.glob("*.json") if p.name != "index.json"):
            try:
                o = json.loads(f.read_text(encoding="utf-8"))
                items.append({"title": o["title"], "body": o.get("body", ""),
                              "parent_slug": (o.get("parents") or [None])[0],
                              "priority": o.get("priority", "normal"),
                              "state": o.get("state", "seedling")})
            except Exception:
                pass
        return self.add(items)          # additive; board's own near-dup guard applies

    def merge(self, into, from_, body=None):
        return {"error": "the board backend cannot merge topics (posts are append-only and "
                         "the board is already a shared store). Reconcile on the sqlite backend."}

    def duplicates(self, band="kin"):
        from server import near_duplicates_in
        topics = self._load()
        seen, pairs = set(), []
        for t in topics:
            others = [x for x in topics if x["slug"] != t["slug"]]
            for dpl in near_duplicates_in(t["title"], t["body"], others, limit=5):
                key = tuple(sorted((t["slug"], dpl["slug"])))
                if key in seen:
                    continue
                seen.add(key)
                pairs.append({"a": key[0], "b": key[1], "score": dpl["score"],
                              "mode": dpl["mode"], "band": dpl["band"]})
        return {"pairs": pairs, "count": len(pairs)}
```

- [ ] **Step 5: Add the 4 `TOOLS` entries**

In `plugin/server/mcp_tools.py`, append these to the `TOOLS` list (after the `topic_groom_report` entry, before the closing `]`):

```python
    {"name": "topic_export",
     "description": "Write this project's live topic tree to a directory of per-topic JSON "
                    "files (git-committable; default <repo>/.topics). mode='mirror' (default) "
                    "makes the dir exactly match the store (deletes stale files); 'snapshot' "
                    "only adds. scope: omit for all live, 'critical' for beacons only, or a "
                    "slug for that subtree. sqlite = full; board = read-only snapshot.",
     "inputSchema": {"type": "object", "properties": {
         "dir": {"type": "string", "description": "target dir (default <repo>/.topics)"},
         "mode": {"type": "string", "enum": ["mirror", "snapshot"]},
         "scope": {"type": "string", "description": "'critical' | a subtree slug | omit for all"}}}},
    {"name": "topic_import",
     "description": "Merge a .topics dir into this project's store, ADDITIVELY and "
                    "idempotently: unchanged topics skip, a slug collision with different "
                    "content imports under a disambiguated slug, a recently-merged slug is "
                    "not resurrected. Never auto-merges. Returns a reconcile WORKLIST of "
                    "candidate near-duplicate pairs touching the imported topics - walk it "
                    "next with the topics-reconcile skill (topic_get -> topic_merge/attach).",
     "inputSchema": {"type": "object", "properties": {
         "dir": {"type": "string", "description": "source dir (default <repo>/.topics)"}}}},
    {"name": "topic_merge",
     "description": "Fold topic `from` into topic `into`: re-parent from's children onto "
                    "into, transfer its parent/extra edges and conversions, take the stronger "
                    "priority/state, and tombstone from (recoverable in the archive; hard-"
                    "removed after 14 days). Optionally pass `body` to set into's combined, "
                    "rewritten body. The reconcile MERGE decision - always a judgment with "
                    "both bodies in view, never automatic. sqlite only. Cycle/self-guarded.",
     "inputSchema": {"type": "object", "properties": {
         "into": {"type": "string", "description": "the survivor slug"},
         "from": {"type": "string", "description": "the slug to fold away"},
         "body": {"type": "string", "description": "optional rewritten combined body"}},
       "required": ["into", "from"]}},
    {"name": "topic_duplicates",
     "description": "List candidate near-duplicate PAIRS across the live tree (the reconcile "
                    "worklist), semantic when the local embedder is up. band: 'kin' (default) "
                    "| 'dup_likely' | 'weak'. Above the band is a candidate to REVIEW, never "
                    "an instruction to merge.",
     "inputSchema": {"type": "object", "properties": {
         "band": {"type": "string", "enum": ["weak", "kin", "dup_likely"]}}}},
```

- [ ] **Step 6: Add the `_call` dispatch**

In `plugin/server/mcp_tools.py`, in `_call`, add before `if name == "topic_groom_report":`:

```python
    if name == "topic_export":
        return b.export(args.get("dir"), str(args.get("mode") or "mirror"), args.get("scope"))
    if name == "topic_import":
        return b.import_(args.get("dir"))
    if name == "topic_merge":
        return b.merge(str(args.get("into") or ""), str(args.get("from") or ""), args.get("body"))
    if name == "topic_duplicates":
        return b.duplicates(str(args.get("band") or "kin"))
```

- [ ] **Step 7: Add the board-leg test (gated)**

In `plugin/server/test_mcp.py`, add to `class TestMCPBoardBackend`:

```python
    def test_03_board_export_and_merge_unsupported(self):
        import tempfile as _tf
        with _tf.TemporaryDirectory() as d:
            ex, err = self.mcp.tool("topic_export", {"dir": d, "mode": "snapshot"})
            self.assertFalse(err, ex)
            self.assertEqual(ex.get("backend"), "board")
        mg, err = self.mcp.tool("topic_merge", {"into": "x", "from": "y"})
        self.assertTrue(err, "board merge must report not-supported")
        self.assertIn("cannot merge", mg.get("error", ""))
```

- [ ] **Step 8: Run the MCP suite**

Run: `python test_mcp.py`
Expected: PASS (HTTP + direct legs run; the board leg auto-skips unless `TOPICS_TEST_AUTHOR` + a live board are configured).

- [ ] **Step 9: Commit**

```bash
git add plugin/server/mcp_tools.py plugin/server/test_mcp.py
git -c user.name="Murakumo" -c user.email="murikumo1234@gmail.com" commit -m "feat(mcp): topic_export/import/merge/duplicates tools on both backends"
```

---

### Task 8: `topics-reconcile` skill

**Files:**
- Create: `plugin/skills/topics-reconcile/SKILL.md`
- Modify: `plugin/skills/topics-groom/SKILL.md` (add a one-line pointer to reconcile)

**Interfaces:**
- Consumes: the four new MCP tools + `topic_get`/`topic_attach`.
- Produces: the judgment doctrine for turning an import worklist (or `topic_duplicates`) into merge/link/leave decisions, then export+commit.

- [ ] **Step 1: Write the skill file**

Create `plugin/skills/topics-reconcile/SKILL.md`:

```markdown
---
name: topics-reconcile
description: Use after a topic_import returns a worklist, or when topic_duplicates shows near-duplicate pairs, to curate a merged topic pile into one living tree. Governs the add-both-reconcile-later discipline - import adds liberally, and THIS is where the judgment happens: combine, keep-both-linked, or leave. Also governs export back to the git-committable .topics dir.
---

# topics-reconcile: turn a merged pile into one living tree

Import is deliberately dumb: it ADDS (idempotently) and hands back a worklist. It never
merges. Reconcile is where a real mind, with both bodies in view, decides what the import
could not. This is the serving-side discipline the CHARTER demands: a duplicated pile
reads as "we're on top of this" while it rots. A merged tree is the cure.

## When to reconcile

- Right after `topic_import` returns a non-empty `worklist` - it IS the agenda; work it now.
- During a grooming round: run `topic_duplicates` (band `kin` by default) for the same
  worklist any time, not only after an import.
- Never reconcile a pair you have not READ. Similarity is a candidate signal, never an order.

## The three moves (per candidate pair)

Read BOTH with `topic_get` first. Then choose in context:

1. **Combine** -> `topic_merge(into, from, body?)`. The common case for "extremely similar."
   Pick the survivor (`into`), and pass a `body` that is the REWRITTEN combination of both -
   not a truncation, not a concatenation: the single best statement of the shared topic and
   its one question. Children, extra parents, and conversions move to the survivor
   automatically; `from` is tombstoned (recoverable ~14 days, then gone).

2. **Keep both, related** -> `topic_attach`. Same surface, genuinely distinct topics that
   share a destination or a parent. Link them as co-parents / cross-avenues so the tree
   shows the relationship; do NOT merge.

3. **Leave** -> do nothing. Distinct despite the score. Recording nothing is a valid,
   common outcome; a false candidate costs one read.

## Picking the survivor

Merge the thinner into the richer: the topic with more children, more provenance, or the
clearer question is `into`. When equal, the older `created_at` wins (it carries more
history). Priority and the more-alive state survive automatically - you do not have to
preserve a beacon by hand.

## After reconciling: propagate

When the pass is done, `topic_export` (mode `mirror`) to the project's `.topics` dir and
commit it. Mirror drops the tombstoned files, so the merge travels to teammates through
normal git - no server, no sync. The exported files are byte-stable: an unchanged topic
produces no diff, so a reconcile commit shows exactly what changed.

## What reconcile is NOT

- Not auto-merge. There is no threshold that merges for you; that was rejected by design.
- Not a place to prune. A dead branch is `topic_state pruned`, not a merge.
- Not export-for-its-own-sake. Export because a reconcile changed the tree, not to feel busy.
```

- [ ] **Step 2: Add the pointer from topics-groom**

Open `plugin/skills/topics-groom/SKILL.md`, and add one line near where it discusses duplicates/enumeration (append this sentence to the section that mentions `topic_list`/`topic_get`, or add a short paragraph at the end):

```markdown
When enumeration turns up near-duplicates, hand off to the **topics-reconcile** skill
(`topic_duplicates` -> `topic_get` both -> `topic_merge`/`topic_attach`) rather than
merging by hand - it carries the survivor-picking and propagation discipline.
```

- [ ] **Step 3: Verify the skill parses (frontmatter + no identifiers)**

Run: `python -c "import pathlib,re; t=pathlib.Path('../skills/topics-reconcile/SKILL.md').read_text(encoding='utf-8'); assert t.startswith('---'); assert 'name: topics-reconcile' in t; print('ok')"`
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add plugin/skills/topics-reconcile/SKILL.md plugin/skills/topics-groom/SKILL.md
git -c user.name="Murakumo" -c user.email="murikumo1234@gmail.com" commit -m "feat(skill): topics-reconcile - the add-both-reconcile-later judgment doctrine"
```

---

### Task 9: Version bump to 0.8.0 + docs + release

**Files:**
- Modify: `plugin/server/server.py` (`VERSION`), `plugin/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `plugin/CHANGELOG.md`, `plugin/server/README.md`
- Test: full suites

**Interfaces:**
- Produces: a consistent 0.8.0 across every manifest + a changelog entry + the tool count/list updated in docs.

- [ ] **Step 1: Bump `VERSION` in `server.py`**

Change line 29 in `plugin/server/server.py`:

```python
VERSION = "0.8.0"                     # single source of truth (MCP serverInfo reads this)
```

- [ ] **Step 2: Bump + extend `plugin.json`**

In `plugin/.claude-plugin/plugin.json`: set `"version": "0.8.0"`, and in `description` change the tool list `topic_add/get/list/serve/search/state/convert/attach/groom_report` to `topic_add/get/list/serve/search/state/convert/attach/groom_report/export/import/merge/duplicates`.

- [ ] **Step 3: Bump `marketplace.json`**

In `.claude-plugin/marketplace.json`: set both `"version": "0.8.0"` occurrences (the top-level plugin entry).

- [ ] **Step 4: Add the CHANGELOG entry**

At the top of `plugin/CHANGELOG.md` (below `# Changelog`), add:

```markdown
## 0.8.0 - 2026-07-12 - Export / import / reconcile

- **Share the tree through git, not a server.** `topic_export` writes this project's live
  tree to a directory of byte-stable per-topic files (`<repo>/.topics/<slug>.json`,
  git-committable); `mirror` mode makes the dir exactly match the store, `snapshot` only
  adds. No cloud, no daemon - sharing is a commit.
- **`topic_import` is additive + idempotent.** Unchanged topics skip (content-hash), a
  slug collision with different content imports under a disambiguated slug, a recently-
  merged slug is not resurrected. It NEVER auto-merges; it returns a reconcile WORKLIST of
  candidate near-duplicate pairs touching the imported topics.
- **`topic_merge` folds one topic into another** - re-parents children, transfers parent/
  extra edges and conversions to the survivor, takes the stronger priority/state, optional
  rewritten combined body, and tombstones the loser (recoverable in the archive, hard-
  removed after 14 days by the prune sweep). Cycle- and self-guarded.
- **`topic_duplicates`** lists candidate near-dup pairs on demand (the same worklist).
- **New `topics-reconcile` skill** carries the add-both-reconcile-later judgment: read both
  with topic_get, then combine / keep-both-linked / leave - similarity is a candidate
  signal, never an order.
- Board backend gets read-only `export` + additive `import`; `topic_merge` returns a clear
  "not supported" (the board is already a shared store). New `topic.merged_into` column
  (idempotent migration).
```

- [ ] **Step 5: Update the tool count/list in `README.md`**

In `plugin/server/README.md`, find the phrase naming the tool count (e.g. "Nine tools") and update it to "Thirteen tools", and add `export`, `import`, `merge`, `duplicates` wherever the HTTP surface / tool list is enumerated. (Grep first to locate: `grep -n -i "nine tools\|topic_attach\|/api/topics" plugin/server/README.md`.)

- [ ] **Step 6: Run BOTH full suites**

Run: `python test_server.py && python test_mcp.py`
Expected: all PASS; MCP handshake reports the 13-tool set; board leg skips.

- [ ] **Step 7: Verify the version is consistent everywhere**

Run: `grep -rn "0\.8\.0" plugin/.claude-plugin/plugin.json .claude-plugin/marketplace.json plugin/server/server.py plugin/CHANGELOG.md`
Expected: 0.8.0 appears in all four.

- [ ] **Step 8: Confirm no identifiers leaked into new code/tests/docs**

Run: `grep -rni "quantum\|fyibos\|murik\|espaulding\|joule\|lyra\|F:\\\\writing" plugin/server/server.py plugin/server/mcp_tools.py plugin/server/test_server.py plugin/server/test_mcp.py plugin/skills/topics-reconcile docs/2026-07-12-export-import-reconcile-*.md`
Expected: no matches (the "Ame No Murakumo" publisher brand is the only identity; the commit author line is separate from source).

- [ ] **Step 9: Commit**

```bash
git add plugin/server/server.py plugin/.claude-plugin/plugin.json .claude-plugin/marketplace.json plugin/CHANGELOG.md plugin/server/README.md
git -c user.name="Murakumo" -c user.email="murikumo1234@gmail.com" commit -m "release: 0.8.0 - export / import / reconcile"
```

---

## Self-Review

**Spec coverage** (each design section → task):
- Export format & layout (per-topic files, index, byte-stable, mirror/snapshot, repo-root default) → Task 2. ✓
- Tool surface (export/import/merge/duplicates) → server Tasks 2/3/4/6, MCP Task 7. ✓
- `topic_merge` semantics (reparent, re-link, cycle-safety, body, priority/state survivorship, tombstone, transactional) → Task 4. ✓
- Tombstone aging (14 days, prune sweep, mirror drops files, won't-resurrect) → Task 5 (aging) + Task 2 (mirror drops non-live files) + Task 3 (won't-resurrect). ✓
- Reconcile pass (skill, threshold as candidate signal) → Task 8 + `find_duplicates`/`min_band` Task 6. ✓
- Error handling (idempotent import, deterministic export, transactional merge, bad-input reported, both backends) → Tasks 2/3/4/7. ✓
- Testing (round-trips, idempotent, disambiguation, merge guards, mirror delete, won't-resurrect, prune aging) → Tasks 2–7 tests. ✓
- Versioning (0.8.0, all manifests, changelog, README count) → Task 9. ✓
- Out of scope (no live sync, no auto-merge, no three-way) → honored; nothing implements them. ✓

**Placeholder scan:** the only intentional temporary is `_worklist_for`'s stub in Task 3, explicitly replaced in Task 6 (called out in both tasks). No TBD/TODO/"add error handling"/"similar to Task N" — all code is shown in full.

**Type consistency:**
- `merge_topics(into_slug, from_slug, actor, body=None)` — the MCP `ServerBackend.merge(into, from_, body)` calls `merge_topics(into, from_, ACTOR, body)` (positional `actor` third). Consistent. ✓
- `find_duplicates(min_band="kin")` — called by the route with a positional band and by `duplicates(band)`; the `_worklist_for` call uses the default. Consistent. ✓
- `export_topics(dir, mode, scope)` / `import_topics(dir)` signatures match the route calls and the MCP passthrough/fallback calls. ✓
- Import worklist pairs and `find_duplicates` pairs share the `{a,b,score,mode,band}` shape. ✓
- `content_hash` is computed identically in `_topic_export_dict` (export) and `import_topics` (local recompute) via `_content_hash`. ✓

**Known simplifications (intentional, documented):** import does a self-edge guard only (no full cycle re-derivation) because it reconstructs a well-formed acyclic export; `index.json` omits a timestamp to stay byte-stable (a refinement over the spec's literal field list, serving the spec's byte-stable goal).
