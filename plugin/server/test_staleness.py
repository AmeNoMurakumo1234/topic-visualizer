#!/usr/bin/env python3
"""0.42 "fight staleness" tests (design: docs/2026-07-20-fight-staleness-design.md).

What this locks, per the field feedback that drove the release:
  KEYSTONE - touched_at no longer conflates three meanings. Structural ops (reparent/attach)
  stop graduating seedlings; serve stops writing touched_at (it was laundering staleness);
  engagement ops (content edit, deliberate state change, convert) write engaged_at and are
  the only graduators.
  COOLDOWN - a served card is demoted for TOPICS_SERVE_COOLDOWN_DAYS so a re-serve advances,
  unless it is the only live candidate (never a blank card).
  STALENESS - health() leads with a staleness block (served:live, stale opens on engaged_at,
  never-served, warning flag) and reports whether expiry has ever actually run.
  RECONCILE - one bulk verb applies {slug, disposition} batches with per-item results.
  HINTS - groom root_orphan_hints are semantic-only and honestly absent when the embedder is
  down (no keyword guess); never suggest a hub inside the orphan's own subtree.
  VISIBILITY - recent_human_activity surfaces last-7d human actions to the co-driving agent.

Two layers, same file:
  StalenessE2E - the real HTTP server on a temp db (house test pattern, own port).
  KeystoneUnit - imports server directly for migration backfill + fake-embedder hint tests.

    python server/test_staleness.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8993
BASE = f"http://127.0.0.1:{PORT}"


def call(path: str, payload: dict | None = None) -> dict:
    if payload is None:
        req = urllib.request.Request(BASE + path)
    else:
        req = urllib.request.Request(
            BASE + path, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


class StalenessE2E(unittest.TestCase):
    proc: subprocess.Popen | None = None
    tmp: tempfile.TemporaryDirectory | None = None
    db: str = ""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.db = str(Path(cls.tmp.name) / "topics.db")
        cls.proc = subprocess.Popen(
            [sys.executable, str(HERE / "server.py"), "--db", cls.db, "--port", str(PORT)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(50):
            try:
                call("/api/topics")
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)
        cls.tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    @classmethod
    def _direct(cls) -> sqlite3.Connection:
        c = sqlite3.connect(cls.db)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=4000")
        return c

    def _backdate(self, slug: str, days: float, *fields: str):
        c = self._direct()
        sets = ", ".join(f"{f} = datetime('now', '-{days} days')" for f in fields)
        c.execute(f"UPDATE topic SET {sets} WHERE slug=?", (slug,))
        c.commit()
        c.close()

    def _topic(self, slug: str) -> dict:
        for t in call("/api/topics")["topics"]:
            if t["slug"] == slug:
                return t
        raise AssertionError(f"topic {slug} not in /api/topics")

    def _capture(self, title: str, state: str = "open", parent: str | None = None,
                 priority: str = "normal", actor: str = "test") -> str:
        item = {"title": title, "state": state, "priority": priority}
        if parent:
            item["parent_slug"] = parent
        r = call("/api/topics", {"topics": [item], "actor": actor})
        return r["results"][0]["slug"]

    # -- serve cooldown --------------------------------------------------
    def test_01_only_candidate_still_serves(self):
        lone = self._capture("lone survivor question")
        c1 = call("/api/topics/serve")["card"]
        c2 = call("/api/topics/serve")["card"]
        self.assertEqual(c1["slug"], lone)
        self.assertEqual(c2["slug"], lone, "the only live candidate must keep serving")

    def test_02_cooldown_advances_past_the_served_card(self):
        cls = type(self)
        cls.slug_a = self._capture("beacon alpha priority question", priority="critical")
        cls.slug_b = self._capture("normal beta question")
        c1 = call("/api/topics/serve")["card"]
        self.assertEqual(c1["slug"], cls.slug_a, "fresh beacon outranks everything")
        c2 = call("/api/topics/serve")["card"]
        self.assertEqual(c2["slug"], cls.slug_b,
                         "re-serve must advance: the served beacon is in cooldown, the "
                         "un-served normal card must win")

    def test_03_cooldown_expires(self):
        a = type(self).slug_a
        self._backdate(a, 4, "served_at")        # 4d > the 3d default window
        card = call("/api/topics/serve")["card"]
        self.assertEqual(card["slug"], a, "out of cooldown, the beacon leads again")

    def test_04_serve_writes_served_at_not_touched_or_engaged(self):
        s = self._capture("serve semantics probe")
        self._backdate(s, 10, "touched_at", "engaged_at")
        # force-serve it: cooldown will advance through the small pool until it lands
        for _ in range(6):
            card = call("/api/topics/serve")["card"]
            if card["slug"] == s:
                break
        else:
            self.fail("probe card never served")
        t = self._topic(s)
        self.assertIsNotNone(t.get("served_at"), "serve must record served_at")
        c = self._direct()
        row = c.execute("SELECT julianday('now')-julianday(touched_at) AS td, "
                        "julianday('now')-julianday(engaged_at) AS ed, state "
                        "FROM topic WHERE slug=?", (s,)).fetchone()
        c.close()
        self.assertGreater(row["td"], 9, "serve must NOT reset touched_at (the launderer)")
        self.assertGreater(row["ed"], 9, "serve must NOT reset engaged_at")

    # -- keystone: graduation semantics ---------------------------------
    def test_05_reparent_does_not_graduate_a_seedling(self):
        cls = type(self)
        hub = self._capture("a stable hub for reparents")
        s = cls.slug_seed = self._capture("tentative seedling idea", state="seedling")
        self._backdate(s, 5, "engaged_at")
        r = call(f"/api/topics/{s}/edit", {"parent_slug": hub, "actor": "assay"})
        self.assertTrue(r.get("ok"))
        t = self._topic(s)
        self.assertEqual(t["state"], "seedling",
                         "structural reshaping is not engagement - no graduation")
        c = self._direct()
        row = c.execute("SELECT julianday('now')-julianday(engaged_at) AS ed "
                        "FROM topic WHERE slug=?", (s,)).fetchone()
        c.close()
        self.assertGreater(row["ed"], 4, "reparent must not reset engaged_at")

    def test_06_noop_reparent_does_not_graduate(self):
        s = type(self).slug_seed
        parent = self._topic(s)["parent_slug"]
        call(f"/api/topics/{s}/edit", {"parent_slug": parent, "actor": "assay"})
        self.assertEqual(self._topic(s)["state"], "seedling",
                         "the no-op reparent was the original graduation repro")

    def test_07_attach_does_not_graduate(self):
        hub2 = self._capture("a second avenue hub")
        s = type(self).slug_seed
        r = call(f"/api/topics/{s}/attach", {"parent_slug": hub2, "actor": "assay"})
        self.assertTrue(r.get("ok"))
        self.assertEqual(self._topic(s)["state"], "seedling",
                         "attach is structural - no graduation")

    def test_08_content_edit_graduates_and_engages(self):
        s = type(self).slug_seed
        r = call(f"/api/topics/{s}/edit",
                 {"title": "tentative seedling idea, sharpened", "actor": "assay"})
        self.assertTrue(r.get("ok"))
        t = self._topic(s)
        self.assertEqual(t["state"], "open", "a content edit IS engagement - graduate")
        c = self._direct()
        row = c.execute("SELECT julianday('now')-julianday(engaged_at) AS ed "
                        "FROM topic WHERE slug=?", (s,)).fetchone()
        c.close()
        self.assertLess(row["ed"], 0.1, "content edit must refresh engaged_at")

    def test_09_deliberate_state_change_engages(self):
        s2 = self._capture("another seedling", state="seedling")
        self._backdate(s2, 5, "engaged_at")
        call(f"/api/topics/{s2}/state", {"state": "discussed", "actor": "human"})
        t = self._topic(s2)
        self.assertEqual(t["state"], "discussed")
        c = self._direct()
        row = c.execute("SELECT julianday('now')-julianday(engaged_at) AS ed "
                        "FROM topic WHERE slug=?", (s2,)).fetchone()
        c.close()
        self.assertLess(row["ed"], 0.1, "a deliberate state change must refresh engaged_at")

    # -- staleness health block ------------------------------------------
    def test_10_health_leads_with_staleness(self):
        for i in range(5):
            slug = self._capture(f"stale open topic number {i}")
            self._backdate(slug, 31, "engaged_at")
        h = call("/api/topics/health")
        self.assertEqual(list(h.keys())[0], "staleness",
                         "staleness must be the FIRST key - the loudest signal")
        st = h["staleness"]
        self.assertGreaterEqual(st["stale_open_count"], 5)
        self.assertTrue(st["warning"], "5 stale opens >= default threshold must warn")
        self.assertIn("served_to_live", st)
        self.assertGreaterEqual(st["never_served_count"], 5)
        self.assertIn("expiry", h)
        # the server sweeps expiry once AT STARTUP (main calls expire_all), so evaluated
        # is True here and last_run must agree; the False case belongs to stores read
        # outside a server (the MCP direct fallback), not to this e2e
        self.assertEqual(h["expiry"]["evaluated"], h["expiry"]["last_run"] is not None,
                         "evaluated must be exactly 'last_run recorded'")
        self.assertTrue(h["expiry"]["evaluated"],
                        "this server swept at startup - the report must say so")

    def test_11_recent_human_activity_surfaces(self):
        s = self._capture("human touched this one")
        call(f"/api/topics/{s}/edit", {"body": "human note", "actor": "human"})
        h = call("/api/topics/health")
        acts = h.get("recent_human_activity", [])
        self.assertTrue(any(a["slug"] == s for a in acts),
                        "a human edit within 7d must appear")
        agent_slugs = [a["slug"] for a in acts if a["slug"] == type(self).slug_b]
        self.assertEqual(agent_slugs, [], "agent-actor events must not appear")

    def test_12_groom_gains_counts_and_honest_hints(self):
        g = call("/api/topics/groom")
        self.assertIn("expiry_candidates_count", g)
        self.assertGreaterEqual(g["expiry_candidates_count"], 5)
        coh = g["coherence"]
        self.assertIn("root_orphan_hints", coh)
        self.assertEqual(coh["root_orphan_hints"], [],
                         "no embedder in the test env - hints must be EMPTY, not guessed")
        self.assertIn("unavailable", str(coh.get("root_orphan_note", "")).lower(),
                      "the emptiness must be labeled honest-unavailable")

    # -- reconcile --------------------------------------------------------
    def test_13_reconcile_bulk_dispositions(self):
        r1 = self._capture("reconcile me discussed")
        r2 = self._capture("reconcile me pruned childless")
        r3 = self._capture("reconcile me converted")
        r4 = self._capture("reconcile parent with child")
        self._capture("the child under r4", parent=r4)
        res = call("/api/topics/reconcile", {"actor": "assay", "items": [
            {"slug": r1, "disposition": "discussed", "note": "shipped as gh#41"},
            {"slug": r2, "disposition": "pruned"},
            {"slug": r3, "disposition": "converted", "ref": "gh#12"},
            {"slug": r4, "disposition": "pruned"},
            {"slug": "no-such-slug", "disposition": "discussed"},
            {"slug": r1, "disposition": "converted"},
        ]})
        by_slug = {}
        for item in res["results"]:
            by_slug.setdefault(item["slug"], []).append(item)
        self.assertTrue(by_slug[r1][0].get("ok"))
        self.assertTrue(by_slug[r2][0].get("ok"))
        self.assertTrue(by_slug[r3][0].get("ok"))
        self.assertIn("error", by_slug[r4][0], "pruning a parent in bulk must refuse")
        self.assertIn("error", by_slug["no-such-slug"][0])
        self.assertIn("error", by_slug[r1][1], "converted without ref must refuse")
        self.assertEqual(res["applied"], 3)
        self.assertEqual(res["errors"], 3)
        self.assertEqual(self._topic(r1)["state"], "discussed")
        self.assertEqual(self._topic(r3)["state"], "discussed")
        self.assertEqual(self._topic(r4)["state"], "open", "refused prune must not apply")
        c = self._direct()
        pruned_state = c.execute("SELECT state FROM topic WHERE slug=?", (r2,)).fetchone()["state"]
        self.assertEqual(pruned_state, "pruned")
        link = c.execute(
            "SELECT l.ref FROM topic_link l JOIN topic t ON t.id=l.topic_id WHERE t.slug=?",
            (r3,)).fetchone()
        self.assertEqual(link["ref"], "gh#12")
        ev = c.execute(
            "SELECT COUNT(*) n FROM topic_event e JOIN topic t ON t.id=e.topic_id "
            "WHERE e.event='reconciled' AND t.slug IN (?,?,?)", (r1, r2, r3)).fetchone()["n"]
        c.close()
        self.assertEqual(ev, 3, "each applied item leaves a reconciled audit event")


class KeystoneUnit(unittest.TestCase):
    """Direct-import tests: migration backfill + fake-embedder hint semantics."""

    def _old_schema_db(self, path: str) -> None:
        """A pre-0.42 store: topic table WITHOUT engaged_at/served_at, plus events."""
        c = sqlite3.connect(path)
        c.executescript("""
            CREATE TABLE topic (
              id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, title TEXT NOT NULL,
              body TEXT NOT NULL DEFAULT '', parent_id INTEGER,
              state TEXT NOT NULL DEFAULT 'open', priority TEXT NOT NULL DEFAULT 'normal',
              tags TEXT NOT NULL DEFAULT '', created_by TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              touched_at TEXT NOT NULL DEFAULT (datetime('now')),
              provenance TEXT NOT NULL DEFAULT '', state_changed_at TEXT,
              state_changed_by TEXT, state_note TEXT NOT NULL DEFAULT '');
            CREATE TABLE topic_event (
              id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL, event TEXT NOT NULL,
              actor TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
              at TEXT NOT NULL DEFAULT (datetime('now')));
            INSERT INTO topic (slug, title, touched_at)
              VALUES ('veteran', 'a pre-migration topic', datetime('now', '-9 days'));
            INSERT INTO topic (slug, title) VALUES ('unserved', 'never served topic');
            INSERT INTO topic_event (topic_id, event, actor, at)
              VALUES (1, 'served', 'server', datetime('now', '-2 days'));
        """)
        c.commit()
        c.close()

    def test_backfill_engaged_and_served(self):
        sys.path.insert(0, str(HERE))
        import server
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            p = str(Path(tmp) / "old.db")
            self._old_schema_db(p)
            conn = server.open_db(p)
            r = conn.execute(
                "SELECT engaged_at, touched_at, served_at FROM topic WHERE slug='veteran'"
            ).fetchone()
            self.assertEqual(r["engaged_at"], r["touched_at"],
                             "backfill: engaged_at = touched_at (least-wrong)")
            self.assertIsNotNone(r["served_at"], "served_at backfilled from the served event")
            r2 = conn.execute(
                "SELECT engaged_at, served_at FROM topic WHERE slug='unserved'").fetchone()
            self.assertIsNotNone(r2["engaged_at"])
            self.assertIsNone(r2["served_at"], "never served -> stays NULL, honestly")
            conn.close()

    def test_root_orphan_hints_semantic(self):
        sys.path.insert(0, str(HERE))
        import server
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            server.DB_PATH = str(Path(tmp) / "t.db")
            server._conn = server.open_db(server.DB_PATH)
            add = server.add_topics
            hub = add([{"title": "quantum error correction hub", "state": "open"}], "t")[0]["slug"]
            add([{"title": "child one", "parent_slug": hub, "state": "open"},
                 {"title": "child two", "parent_slug": hub, "state": "open"}], "t")
            orphan_near = add([{"title": "quantum decoherence question",
                                "state": "open"}], "t")[0]["slug"]
            orphan_far = add([{"title": "sourdough starter hydration",
                               "state": "open"}], "t")[0]["slug"]

            def fake_embed(texts):
                return [[1.0, 0.0] if "quantum" in t else [0.0, 1.0] for t in texts]

            orig = server._embed
            server._embed = fake_embed
            try:
                hints, note = server._root_orphan_hints()
            finally:
                server._embed = orig
            by_orphan = {h["orphan"]: h for h in hints}
            self.assertIn(orphan_near, by_orphan, "similar orphan must be hinted")
            self.assertEqual(by_orphan[orphan_near]["hub"], hub)
            self.assertNotIn(orphan_far, by_orphan, "dissimilar orphan must not be hinted")
            self.assertNotIn(hub, by_orphan, "a hub is not its own orphan")

    def test_root_orphan_hint_never_suggests_own_subtree(self):
        sys.path.insert(0, str(HERE))
        import server
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            server.DB_PATH = str(Path(tmp) / "t2.db")
            server._conn = server.open_db(server.DB_PATH)
            add = server.add_topics
            root = add([{"title": "quantum root umbrella", "state": "open"}], "t")[0]["slug"]
            mid = add([{"title": "quantum middle hub", "parent_slug": root,
                        "state": "open"}], "t")[0]["slug"]
            add([{"title": "quantum leaf a", "parent_slug": mid, "state": "open"},
                 {"title": "quantum leaf b", "parent_slug": mid, "state": "open"}], "t")

            def fake_embed(texts):
                return [[1.0, 0.0] for _ in texts]     # everything maximally similar

            orig = server._embed
            server._embed = fake_embed
            try:
                hints, note = server._root_orphan_hints()
            finally:
                server._embed = orig
            for h in hints:
                self.assertNotEqual(
                    (h["orphan"], h["hub"]), (root, mid),
                    "hinting a root under a hub inside its own subtree suggests a cycle")


class AuditFixUnit(unittest.TestCase):
    """0.42.1 pre-marketplace audit fixes. Each test pins a defect the four-lens audit
    confirmed: no-op state re-assertion re-laundered the staleness clock; reconcile
    accepted a bare string (per-char error amplification) and double-applied in-batch
    duplicate slugs; the flat cooldown penalty pinned serving to one card once EVERY
    candidate was cooling; import stamped engaged_at=now (a 60d-stale export read as
    fresh); expiry.evaluated's False leg and the first-of-day tuple contract were
    unpinned."""

    def setUp(self):
        sys.path.insert(0, str(HERE))
        import server
        self.server = server
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._orig_db, self._orig_conn = server.DB_PATH, getattr(server, "_conn", None)
        server.DB_PATH = str(Path(self.tmp.name) / "t.db")
        server._conn = server.open_db(server.DB_PATH)

    def tearDown(self):
        try:
            self.server._conn.close()
        except Exception:
            pass
        self.server.DB_PATH, self.server._conn = self._orig_db, self._orig_conn
        self.tmp.cleanup()

    def _backdate(self, slug, col, days):
        self.server._conn.execute(
            f"UPDATE topic SET {col} = datetime('now', '-{days} days') WHERE slug=?", (slug,))
        self.server._conn.commit()

    def _col(self, slug, col):
        return self.server._conn.execute(
            f"SELECT {col} v FROM topic WHERE slug=?", (slug,)).fetchone()["v"]

    def test_noop_state_reassertion_does_not_engage(self):
        s = self.server.add_topics([{"title": "held open", "state": "open"}], "t")[0]["slug"]
        self._backdate(s, "engaged_at", 40)
        old = self._col(s, "engaged_at")
        self.server.set_state(s, "open", "t", "bulk sweep re-assert")   # no-op change
        self.assertEqual(self._col(s, "engaged_at"), old,
                         "a no-op state re-assertion must not refresh the staleness clock")
        self.server.set_state(s, "discussed", "t", "real change")       # genuine change
        self.assertNotEqual(self._col(s, "engaged_at"), old,
                            "a real state change is engagement and must refresh it")

    def test_reconcile_rejects_non_list_items(self):
        res = self.server.reconcile("abc", "t")
        self.assertTrue(res.get("error"), "a bare string must be rejected outright")
        self.assertNotIn("results", res,
                         "must not iterate a string into per-character error entries")

    def test_reconcile_in_batch_duplicate_slug_errors(self):
        s = self.server.add_topics([{"title": "dup target", "state": "open"}], "t")[0]["slug"]
        res = self.server.reconcile(
            [{"slug": s, "disposition": "discussed"},
             {"slug": s, "disposition": "pruned"}], "t")
        self.assertEqual((res["applied"], res["errors"]), (1, 1))
        self.assertEqual(self._col(s, "state"), "discussed",
                         "first occurrence applies; the duplicate must not flip it to pruned")

    def test_cooldown_rotates_when_every_candidate_is_cooling(self):
        for i in range(3):
            self.server.add_topics([{"title": f"rotation card {i}", "state": "open"}], "t")
        first_round = [self.server.serve_card("")["card"]["slug"] for _ in range(3)]
        self.assertEqual(len(set(first_round)), 3, "un-served candidates serve first")
        second_round = [self.server.serve_card("")["card"]["slug"] for _ in range(3)]
        self.assertEqual(len(set(second_round)), 3,
                         "all-cooling candidates must rotate least-recently-served-first, "
                         "not pin to the highest base score")

    def test_import_keeps_the_original_engagement_clock(self):
        old = "2026-05-01 12:00:00"
        with self.server._lock:
            self.server._insert_imported(
                {"slug": "old-import", "title": "old idea", "created_at": old}, "old-import")
            self.server._conn.commit()
        self.assertEqual(self._col("old-import", "engaged_at"), old,
                         "import must not stamp engaged_at=now - that laundered a "
                         "60-day-stale export into looking engaged today")

    def test_expiry_evaluated_false_leg(self):
        h = self.server.health()
        self.assertFalse(h["expiry"]["evaluated"],
                         "a store whose expiry sweep never ran must say so - its "
                         "'expired: 0' is uninformative, not healthy")

    def test_first_of_day_serve_returns_a_tuple_on_the_empty_fallback(self):
        import importlib.util
        hook = HERE.parent / "hooks" / "first_of_day.py"
        env_backup = {k: os.environ.get(k) for k in
                      ("TOPICS_SERVER_URL", "TOPICS_DB", "TOPICS_PROJECT")}
        # dead server + nonexistent store BEFORE loading: the hook runs its main at
        # module level (sys.exit inside), so exec under this env is side-effect-free
        os.environ["TOPICS_SERVER_URL"] = "http://127.0.0.1:9"
        os.environ["TOPICS_DB"] = str(Path(self.tmp.name) / "nonexistent.db")
        try:
            spec = importlib.util.spec_from_file_location("fod_test", hook)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)   # module-level main exits; defs survive
            except SystemExit:
                pass
            card, stale = mod._serve()   # must unpack - the audited bare-None broke this
            self.assertIsNone(card)
            self.assertIsNone(stale)
        finally:
            for k, v in env_backup.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class BoardReconcileGuardUnit(unittest.TestCase):
    """The audit MAJOR: BoardBackend.reconcile must enforce the same safety contract the
    tool description promises (childless-only prune, topic identity) - stubbed board, no
    server required, so the previously-untested board leg gets pinned."""

    class _Stub:
        def __init__(self, topics):
            self._topics = topics
            self.calls = []

        def _load(self):
            return self._topics

        def state(self, slug, st, note=""):
            self.calls.append(("state", slug, st))
            return {"ok": True}

        def convert(self, slug, kind, ref, note=""):
            self.calls.append(("convert", slug, ref))
            return {"ok": True}

    def _backend(self, topics):
        sys.path.insert(0, str(HERE))
        import mcp_tools
        stub = self._Stub(topics)
        # borrow the real reconcile, bound to the stub - it must only use _load/state/convert
        stub.reconcile = mcp_tools.BoardBackend.reconcile.__get__(stub)
        return stub

    TOPICS = [
        {"slug": "hub-1", "state": "open", "parentSlug": None},
        {"slug": "leaf-1", "state": "open", "parentSlug": "hub-1"},
        {"slug": "lone-1", "state": "open", "parentSlug": None},
    ]

    def test_prune_with_live_children_refused_and_untouched(self):
        b = self._backend(list(self.TOPICS))
        res = b.reconcile([{"slug": "hub-1", "disposition": "pruned"}])
        self.assertEqual(res["errors"], 1)
        self.assertIn("live child", res["results"][0]["error"])
        self.assertEqual(b.calls, [], "a refused prune must not touch the board")

    def test_non_topic_slug_refused(self):
        b = self._backend(list(self.TOPICS))
        res = b.reconcile([{"slug": "some-board-issue", "disposition": "discussed"}])
        self.assertEqual(res["errors"], 1)
        self.assertIn("not a topic", res["results"][0]["error"])
        self.assertEqual(b.calls, [])

    def test_valid_items_still_apply(self):
        b = self._backend(list(self.TOPICS))
        res = b.reconcile([{"slug": "lone-1", "disposition": "pruned"},
                           {"slug": "leaf-1", "disposition": "discussed"}])
        self.assertEqual((res["applied"], res["errors"]), (2, 0))
        self.assertEqual(len(b.calls), 2)

    def test_string_items_and_duplicates_guarded(self):
        b = self._backend(list(self.TOPICS))
        self.assertTrue(b.reconcile("abc").get("error"))
        res = b.reconcile([{"slug": "lone-1", "disposition": "discussed"},
                           {"slug": "lone-1", "disposition": "pruned"}])
        self.assertEqual((res["applied"], res["errors"]), (1, 1))
        self.assertEqual(b.calls, [("state", "lone-1", "discussed")],
                         "the duplicate must not reach the board")


if __name__ == "__main__":
    unittest.main(verbosity=2)
