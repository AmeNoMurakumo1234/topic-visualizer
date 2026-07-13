#!/usr/bin/env python3
"""End-to-end test for the Topic Visualizer server: starts the real process on a temp
db and walks the seam's flows - batch capture w/ dedup, seedling->open touch
graduation, serve ranking (beacons first), search, edit/re-parent w/ cycle guard,
atomic conversion, prune cascade verification (TOCTOU guard), health + groom.

    python server/test_server.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8992
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


class SeamTests(unittest.TestCase):
    proc: subprocess.Popen | None = None
    tmp: tempfile.TemporaryDirectory | None = None

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.proc = subprocess.Popen(
            [sys.executable, str(HERE / "server.py"),
             "--db", str(Path(cls.tmp.name) / "topics.db"), "--port", str(PORT)],
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

    def test_01_batch_capture_and_dedup(self):
        r = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "auth: how long should a session stay alive? (~1 hour)",
             "body": "THE QUESTION: idle timeout vs absolute expiry?",
             "priority": "critical"},
            {"title": "caching: cold-start warmup budget (~30 min)",
             "body": "THE QUESTION: what do we preload on boot?"},
        ]})
        slugs = [x["slug"] for x in r["results"]]
        self.assertEqual(len(slugs), 2)
        # near-duplicate guard fires on a re-plant of the same idea
        r2 = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "session lifetime: the auth timeout question again",
             "body": "how long should an auth session stay valid before it expires?"}]})
        self.assertTrue(r2["results"][0]["near_duplicates"],
                        "write-time dedup must surface the existing kin topic")

    def test_02_seedling_graduates_on_touch(self):
        topics = call("/api/topics")["topics"]
        self.assertTrue(all(t["state"] == "seedling" for t in topics),
                        "silent captures enter as seedlings")
        slug = topics[0]["slug"]
        call(f"/api/topics/{slug}/edit", {"actor": "human", "critical": True})
        after = {t["slug"]: t for t in call("/api/topics")["topics"]}
        self.assertEqual(after[slug]["state"], "open", "first touch graduates")

    def test_03_serve_ranks_beacon_first(self):
        # the auth-session topic is the beacon (from test_01/02 edits)
        r = call("/api/topics/serve?context=auth%20session%20expiry")
        self.assertIsNotNone(r["card"])
        self.assertEqual(r["card"]["priority"], "critical",
                         "beacons outrank everything")

    def test_04_child_parenting_and_cycle_guard(self):
        r = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "auth: token rotation cadence (~20 min)",
             "parent_slug": call("/api/topics")["topics"][0]["slug"]}]})
        child = r["results"][0]["slug"]
        parent = call("/api/topics")["topics"][0]["slug"]
        # re-parenting the PARENT under its own CHILD must be refused
        bad = call(f"/api/topics/{parent}/edit", {"actor": "human", "parent_slug": child})
        self.assertIn("cycle", str(bad.get("error", "")))
        # POSITIVE reparent (the grooming reshape step): it must MOVE the primary spine, not overlay
        # a dangling avenue. Detach to root, then re-home - and the target must show a REAL child.
        self.assertTrue(call(f"/api/topics/{child}/edit",
                             {"actor": "human", "parent_slug": ""}).get("ok"))
        self.assertIsNone(call(f"/api/topics/{child}")["topic"]["parent_slug"])          # detached to root
        self.assertTrue(call(f"/api/topics/{child}/edit",
                             {"actor": "human", "parent_slug": parent}).get("ok"))
        self.assertEqual(call(f"/api/topics/{child}")["topic"]["parent_slug"], parent)   # primary spine moved
        self.assertIn(child, call(f"/api/topics/{parent}")["topic"]["children"])         # a real child, not a cross-link

    def test_05_search_ranks(self):
        r = call("/api/topics/search?q=auth%20session")
        self.assertTrue(r["results"])
        top = r["results"][0]
        self.assertGreater(top["score"], 0)

    def test_06_atomic_conversion(self):
        slug = call("/api/topics")["topics"][0]["slug"]
        r = call(f"/api/topics/{slug}/links", {"actor": "human", "links": [
            {"kind": "decision", "ref": "ledger-77", "note": "ratified"},
            {"kind": "work_item", "ref": "TICKET-123"}]})
        self.assertEqual(r.get("links"), 2)
        t = {x["slug"]: x for x in call("/api/topics")["topics"]}[slug]
        self.assertEqual(t["state"], "discussed", "conversion marks discussed atomically")
        self.assertEqual(len(t["links"]), 2)

    def test_07_prune_cascade_verified(self):
        # plant a small branch, then prune with a WRONG cascade -> refused
        r = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "widget: a branch to prune"},
        ]})
        root = r["results"][0]["slug"]
        call("/api/topics", {"actor": "ai", "topics": [
            {"title": "widget: child one", "parent_slug": root},
            {"title": "widget: child two", "parent_slug": root}]})
        bad = call(f"/api/topics/{root}/state",
                   {"actor": "human", "state": "pruned", "cascade": [root]})
        self.assertIn("subtree changed", str(bad.get("error", "")))
        # correct cascade prunes all three
        all_slugs = [t["slug"] for t in call("/api/topics")["topics"]
                     if t["slug"] == root or (t["parent_slug"] == root)]
        ok = call(f"/api/topics/{root}/state",
                  {"actor": "human", "state": "pruned", "cascade": all_slugs})
        self.assertEqual(ok.get("changed"), 3)
        live = [t["slug"] for t in call("/api/topics")["topics"]]
        self.assertNotIn(root, live, "pruned topics leave the live tree")
        arch = [t["slug"] for t in call("/api/topics?include=archive")["topics"]]
        self.assertIn(root, arch, "the archive keeps everything")

    def test_08_health_and_groom(self):
        h = call("/api/topics/health")
        self.assertGreaterEqual(h["captured"], 5)
        self.assertGreaterEqual(h["served"], 1)
        self.assertGreaterEqual(h["converted"], 1)
        self.assertGreaterEqual(h["pruned"], 1)
        g = call("/api/topics/groom")
        self.assertIn("capture_calibration", g)
        actors = {row["actor"] for row in g["capture_calibration"]}
        self.assertIn("ai", actors)

    def test_08b_facet_search(self):
        r = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "facet: the beacon topic", "priority": "critical"},
            {"title": "facet: plain grounding topic"}]})
        crit, plain = [x["slug"] for x in r["results"]]
        res = call("/api/topics/search?q=critical")["results"]
        slugs = [x["slug"] for x in res]
        self.assertIn(crit, slugs, "facet word matches the beacon chip")
        self.assertNotIn(plain, slugs)
        self.assertTrue(all(x["mode"] == "facet" for x in res))
        # facet + free text combine: critical topics ranked by the remaining words
        res2 = call("/api/topics/search?q=critical%20beacon%20topic")["results"]
        self.assertIn(crit, [x["slug"] for x in res2])
        self.assertNotIn(plain, [x["slug"] for x in res2])

    def test_09_multi_parent_attach_and_enrichment(self):
        r = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "dag: avenue one"}, {"title": "dag: avenue two"},
            {"title": "dag: the shared destination"}]})
        a1, a2, dest = [x["slug"] for x in r["results"]]
        call(f"/api/topics/{dest}/edit", {"actor": "ai", "parent_slug": a1})
        ok = call(f"/api/topics/{dest}/attach",
                  {"actor": "ai", "parent_slug": a2,
                   "note": "found again from the second avenue"})
        self.assertTrue(ok.get("ok"), ok)
        t = next(x for x in call("/api/topics")["topics"] if x["slug"] == dest)
        self.assertEqual([x["slug"] for x in t["extra_parents"]], [a2])
        self.assertIn("rediscovered", t["body"], "the later discovery enriches the body")
        self.assertIn("found again", t["body"])
        # re-attaching an existing avenue is IDEMPOTENT (ok+already), not an error (0.6.0)
        dup = call(f"/api/topics/{dest}/attach", {"actor": "ai", "parent_slug": a2})
        self.assertTrue(dup.get("ok") and dup.get("already"), dup)
        # cycles are still refused
        self.assertIn("error", call(f"/api/topics/{a1}/attach",
                                    {"actor": "ai", "parent_slug": dest}),
                      "attaching your own descendant is a cycle")
        # detach works
        rm = call(f"/api/topics/{dest}/attach",
                  {"actor": "ai", "parent_slug": a2, "remove": True})
        self.assertEqual(rm.get("removed"), 1)

    def test_11_refused_prune_leaves_dag_untouched(self):
        # audit HIGH-1: a prune refused by the cascade check must not mutate the
        # DAG (survivor promotion used to run BEFORE verification, and error
        # returns left uncommitted writes to ride out on the next commit)
        r = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "tocc: doomed"}, {"title": "tocc: haven"}]})
        doomed, haven = [x["slug"] for x in r["results"]]
        r2 = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "tocc: both ways", "parent_slug": doomed}]})
        both = r2["results"][0]["slug"]
        call(f"/api/topics/{both}/attach", {"actor": "ai", "parent_slug": haven})
        # stale cascade (pretends 'both' would be pruned) -> refusal
        bad = call(f"/api/topics/{doomed}/state",
                   {"actor": "human", "state": "pruned", "cascade": [doomed, both]})
        self.assertIn("subtree changed", str(bad.get("error", "")))
        live = {t["slug"]: t for t in call("/api/topics")["topics"]}
        self.assertEqual(live[both]["parent_slug"], doomed,
                         "refused prune must NOT promote the extra avenue")
        self.assertEqual([x["slug"] for x in live[both]["extra_parents"]], [haven],
                         "refused prune must NOT consume the extra edge")

    def test_12_convert_is_atomic_on_bad_link(self):
        r = call("/api/topics", {"actor": "ai", "topics": [{"title": "atomic convert"}]})
        slug = r["results"][0]["slug"]
        bad = call(f"/api/topics/{slug}/links",
                   {"actor": "ai", "links": [
                       {"kind": "decision", "ref": "good"}, {"kind": "bogus"}]})
        self.assertIn("error", bad)
        t = next(x for x in call("/api/topics")["topics"] if x["slug"] == slug)
        self.assertEqual(t["links"], [], "no phantom link from the failed batch")
        self.assertNotEqual(t["state"], "discussed")

    def test_10_prune_spares_multi_parent_survivors(self):
        r = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "spare: doomed branch"}, {"title": "spare: safe branch"}]})
        doomed, safe = [x["slug"] for x in r["results"]]
        r2 = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "spare: reachable two ways", "parent_slug": doomed},
            {"title": "spare: only via doomed", "parent_slug": doomed}]})
        both, only = [x["slug"] for x in r2["results"]]
        call(f"/api/topics/{both}/attach", {"actor": "ai", "parent_slug": safe})
        # prune the doomed branch WITHOUT a cascade check (cascade=None)
        ok = call(f"/api/topics/{doomed}/state", {"actor": "human", "state": "pruned"})
        self.assertEqual(ok.get("changed"), 2, "root + only-via-doomed die")
        live = {t["slug"]: t for t in call("/api/topics")["topics"]}
        self.assertIn(both, live, "the two-avenue topic SURVIVES the prune")
        self.assertNotIn(only, live)
        self.assertEqual(live[both]["parent_slug"], safe,
                         "the surviving avenue is promoted to primary")
        self.assertEqual(live[both]["extra_parents"], [])

    def test_13_projects_are_isolated_stores(self):
        # topics captured under different project keys never bleed across
        a = call("/api/topics?project=alpha",
                 {"actor": "ai", "title": "alpha-only topic (~10 min)"})["results"][0]["slug"]
        b = call("/api/topics?project=beta",
                 {"actor": "ai", "title": "beta-only topic (~10 min)"})["results"][0]["slug"]
        alpha = {t["slug"] for t in call("/api/topics?project=alpha")["topics"]}
        beta = {t["slug"] for t in call("/api/topics?project=beta")["topics"]}
        self.assertIn(a, alpha)
        self.assertNotIn(b, alpha, "beta's topic must not appear in alpha")
        self.assertIn(b, beta)
        self.assertNotIn(a, beta, "alpha's topic must not appear in beta")
        # and neither leaks into the default project (the harness store)
        default = {t["slug"] for t in call("/api/topics")["topics"]}
        self.assertNotIn(a, default)
        self.assertNotIn(b, default)

    def test_14_projects_endpoint_lists_and_flags_current(self):
        call("/api/topics?project=gamma", {"actor": "ai", "title": "seed gamma"})
        listing = call("/api/projects?project=gamma")
        keys = {p["key"] for p in listing["projects"]}
        self.assertIn("gamma", keys)
        self.assertEqual(listing["current"], "gamma")
        self.assertTrue(any(p["current"] and p["key"] == "gamma"
                            for p in listing["projects"]))
        # a state write is also project-scoped: touching gamma's topic doesn't need default
        g = call("/api/topics?project=gamma")["topics"][0]["slug"]
        touched = call(f"/api/topics/{g}/state?project=gamma",
                       {"actor": "human", "state": "discussed"})
        self.assertTrue(touched.get("ok"))
        gt = {t["slug"]: t for t in call("/api/topics?project=gamma")["topics"]}
        self.assertEqual(gt[g]["state"], "discussed", "the state write landed in gamma's store")


    def test_15_repo_root_keying_and_worktree_fold(self):
        import sys as _sys
        _sys.path.insert(0, str(HERE))
        import server as srv
        # dots encode like Claude (so a derived key matches the dropdown dir name)
        self.assertEqual(srv.encode_project_path(r"C:\repo\.claude\worktrees\x"),
                         "C--repo--claude-worktrees-x")
        # a Claude worktree project dir folds back to its repo key (dropdown = 1 per repo)
        self.assertEqual(srv._fold_worktree("C--Repos-MyApp--claude-worktrees-abc123"),
                         "C--Repos-MyApp")
        self.assertEqual(srv._fold_worktree("C--r--claude-worktrees-a-b-c"), "C--r")
        # a non-worktree dir is unchanged
        self.assertEqual(srv._fold_worktree("C--Repos-my-app"), "C--Repos-my-app")
        # project_key_from_cwd resolves to the git REPO ROOT, not the (sub)dir cwd:
        # the test runs from server/, a subdir of the plugin repo -> key is the repo root's.
        root = srv._repo_root()
        self.assertTrue(root, "the plugin dir is a git repo")
        self.assertEqual(srv.project_key_from_cwd(), srv.encode_project_path(root))
        self.assertNotIn("server", srv.project_key_from_cwd().rsplit("-", 1)[-1].lower(),
                         "key is the repo root, not the server/ subdir")


    def test_16_get_list_slug_bands(self):
        r = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "the grooming enumeration question versus documentation debt (~1 hour)",
             "body": "THE QUESTION: how does a groomer read a body they did not author?"}]})
        slug = r["results"][0]["slug"]
        # slug 10: word-boundary (never a mid-word cut) + a short hash suffix
        self.assertFalse(slug.endswith("-docume") or slug.endswith("-versu"), slug)
        self.assertRegex(slug, r"-[0-9a-f]{6}$")
        # topic_get 2: FULL detail incl. body + history (search only returns slug/score/state)
        g = call(f"/api/topics/{slug}")
        self.assertEqual(g["topic"]["slug"], slug)
        self.assertIn("THE QUESTION", g["topic"]["body"])
        self.assertEqual(g["topic"]["history"][0]["event"], "created")   # newest-first
        self.assertIn("children", g["topic"])
        # topic_list 3: enumeration (slug/title/state/priority/parent), paginated
        lst = call("/api/topics/list")
        self.assertIn(slug, [t["slug"] for t in lst["topics"]])
        self.assertIn("total", lst)
        self.assertTrue(all(("title" in t and "state" in t) for t in lst["topics"]))
        # near-duplicates carry a mode + a readable band (item 5)
        r2 = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "the grooming enumeration question versus documentation debt redux",
             "body": "THE QUESTION: same territory as before"}]})
        dups = r2["results"][0]["near_duplicates"]
        if dups:
            self.assertIn(dups[0].get("band"), ("dup_likely", "kin", "weak"))
            self.assertIn(dups[0].get("mode"), ("semantic", "keyword"))

    def test_17_health_current_vs_window(self):
        h = call("/api/topics/health")
        for k in ("by_state", "window", "converted_topics", "embedder"):
            self.assertIn(k, h)
        self.assertIn(h["embedder"]["status"], ("up", "down", "unknown"))
        self.assertIn("open", h["by_state"])


    def test_18_projects_dir_anchors_to_store_root(self):
        import sys as _sys
        _sys.path.insert(0, str(HERE))
        import server as srv
        # per-project dirs hang off DB_PATH's parent. Anchoring DB_PATH to the HOME default
        # keeps the zero-setup fallback store off the (throwaway worktree) cwd - audit 6.1 #1.
        srv.DB_PATH = srv.DEFAULT_DB
        self.assertEqual(srv._projects_dir(),
                         Path(srv.DEFAULT_DB).expanduser().resolve().parent / "projects")
        # a non-default key resolves a file UNDER that home projects dir, never cwd-relative
        p = Path(srv.project_db_path("some-repo-key"))
        self.assertEqual(p.parent, Path(srv.DEFAULT_DB).expanduser().resolve().parent / "projects")

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
            # full pre-merged_into column set (CREATE INDEX in schema.sql references
            # parent_id/state, so the fixture must carry every column those indexes and
            # other existing tables assume - only merged_into is missing here)
            c0.execute("CREATE TABLE topic (id INTEGER PRIMARY KEY, slug TEXT NOT NULL UNIQUE, "
                       "title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', "
                       "parent_id INTEGER REFERENCES topic(id), "
                       "state TEXT NOT NULL DEFAULT 'seedling', "
                       "priority TEXT NOT NULL DEFAULT 'normal', tags TEXT NOT NULL DEFAULT '', "
                       "created_by TEXT NOT NULL, "
                       "created_at TEXT NOT NULL DEFAULT (datetime('now')), "
                       "touched_at TEXT NOT NULL DEFAULT (datetime('now')), "
                       "provenance TEXT NOT NULL DEFAULT '', "
                       "state_changed_at TEXT, state_changed_by TEXT, state_note TEXT)")
            c0.commit(); c0.close()
            conn2 = srv.open_db(legacy)               # open_db must ALTER it in
            cols2 = {r["name"] for r in conn2.execute("PRAGMA table_info(topic)")}
            self.assertIn("merged_into", cols2, "open_db migrates a legacy DB")
            conn2.close()

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
        # index.json reports the project actually exported, not the server's startup default
        index = json.loads((Path(out) / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index["source_project"], proj)
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
        self.assertEqual(r.get("moved_children"), 1, "the folded topic's one child was re-parented")
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

    def test_26_import_wont_resurrect_merge_tombstone(self):
        # spec: a within-window merge tombstone must NOT be resurrected by a stale re-import
        proj = "resur"
        call(f"/api/topics?project={proj}", {"actor": "ai", "topics": [
            {"title": "queue: the survivor topic", "body": "keep"},
            {"title": "queue: the folded topic", "body": "fold"}]})
        rows = call(f"/api/topics?project={proj}")["topics"]
        into = next(t["slug"] for t in rows if "survivor" in t["title"])
        frm = next(t["slug"] for t in rows if "folded" in t["title"])
        out = str(Path(self.tmp.name) / "resur_export")
        # snapshot the PRE-merge tree, so the export dir still carries `frm`'s file
        call(f"/api/topics/export?project={proj}", {"dir": out, "mode": "snapshot"})
        # merge -> `frm` becomes a fresh (within-window) tombstone
        call(f"/api/topics/merge?project={proj}", {"into": into, "from": frm})
        self.assertNotIn(frm, [t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]])
        # re-importing the pre-merge dir must skip the tombstoned slug, not revive it.
        # If the guard were absent, `frm` (now pruned, differing from the file's seedling
        # content) would be DISAMBIGUATED into a new live slug - so added==0 AND
        # disambiguated==[] is what proves the tombstone guard actually fired.
        r = call(f"/api/topics/import?project={proj}", {"dir": out})
        live = [t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]]
        self.assertNotIn(frm, live, "a within-window merge tombstone is not resurrected on import")
        self.assertEqual(r["added"], 0, "nothing new is added (survivor idempotent, tombstone skipped)")
        self.assertEqual(r["disambiguated"], [], "the tombstoned slug is skipped, not disambiguated")

    def test_27_merge_transfers_edges_and_conversions(self):
        # merge steps 2-4: extra-parent edges (from as parent AND from as child) + conversions
        proj = "mtx"
        call(f"/api/topics?project={proj}", {"actor": "ai", "topics": [
            {"title": "mtx: survivor"}, {"title": "mtx: folded"},
            {"title": "mtx: a parent avenue"}, {"title": "mtx: a child via folded"}]})
        rows = {t["title"]: t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]}
        into, frm = rows["mtx: survivor"], rows["mtx: folded"]
        pav, child = rows["mtx: a parent avenue"], rows["mtx: a child via folded"]
        # `folded` gains an extra parent (pav); `child` gains `folded` as an extra parent;
        # `folded` records a conversion
        call(f"/api/topics/{frm}/attach?project={proj}", {"actor": "ai", "parent_slug": pav})
        call(f"/api/topics/{child}/attach?project={proj}", {"actor": "ai", "parent_slug": frm})
        call(f"/api/topics/{frm}/links?project={proj}",
             {"actor": "ai", "links": [{"kind": "decision", "ref": "d:mtx"}]})
        r = call(f"/api/topics/merge?project={proj}", {"into": into, "from": frm})
        self.assertTrue(r.get("ok"), r)
        live = {t["slug"]: t for t in call(f"/api/topics?project={proj}")["topics"]}
        self.assertIn(pav, [x["slug"] for x in live[into]["extra_parents"]],
                      "folded's parent avenue transfers to the survivor")
        child_parents = [live[child]["parent_slug"]] + [x["slug"] for x in live[child]["extra_parents"]]
        self.assertIn(into, child_parents, "folded's child edge repoints to the survivor")
        self.assertNotIn(frm, child_parents, "no dangling edge to the folded topic")
        g = call(f"/api/topics/{into}?project={proj}")
        self.assertIn("d:mtx", [l["ref"] for l in g["topic"]["links"]],
                      "folded's conversion transfers to the survivor")

    def test_28_groom_checkpoint_restore(self):
        """The grooming undo: checkpoint -> reshape (reparent + merge) + a capture ARRIVES during
        the groom -> restore. The reshape reverses, but the mid-groom capture MUST survive."""
        proj = "ckpt"
        call(f"/api/topics?project={proj}", {"actor": "ai", "topics": [
            {"title": "ckpt: root A"}, {"title": "ckpt: root B"},
            {"title": "ckpt: mover"}, {"title": "ckpt: folded"}]})
        rows = {t["title"]: t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]}
        A, B = rows["ckpt: root A"], rows["ckpt: root B"]
        mover, folded = rows["ckpt: mover"], rows["ckpt: folded"]
        call(f"/api/topics/{mover}/edit?project={proj}", {"actor": "ai", "parent_slug": A})
        # --- checkpoint BEFORE the groom ---
        cp = call(f"/api/topics/checkpoint?project={proj}", {"actor": "ai", "label": "pre-groom"})
        self.assertTrue(cp.get("ok")); self.assertEqual(cp["topics"], 4)
        # --- groom: reparent mover A->B, merge folded into A, AND a real capture lands mid-groom ---
        call(f"/api/topics/{mover}/edit?project={proj}", {"actor": "ai", "parent_slug": B})
        call(f"/api/topics/merge?project={proj}", {"into": A, "from": folded})
        call(f"/api/topics?project={proj}", {"actor": "ai",
             "topics": [{"title": "ckpt: captured DURING the groom"}]})
        newcap = [t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]
                  if "DURING" in t["title"]][0]
        self.assertEqual(call(f"/api/topics/{mover}?project={proj}")["topic"]["parent_slug"], B)
        self.assertNotIn(folded, [t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]],
                         "merge tombstoned folded before restore")
        # --- restore ---
        r = call(f"/api/topics/restore?project={proj}", {"actor": "human"})
        self.assertTrue(r.get("ok"), r)
        live = [t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]]
        self.assertEqual(call(f"/api/topics/{mover}?project={proj}")["topic"]["parent_slug"], A,
                         "reparent reversed")
        self.assertIn(folded, live, "merge reversed - the folded topic returns")
        self.assertIn(newcap, live, "THE guarantee: a capture made during the groom survives the undo")
        self.assertGreaterEqual(r["preserved_since"], 1)


    def test_29_groom_report_avenue_between_siblings(self):
        """Coherence lens: an avenue between two SIBLINGS surfaces as a reparent hint - the depth
        signal the width-first groom used to walk past."""
        proj = "coh"
        call(f"/api/topics?project={proj}", {"actor": "ai", "topics": [
            {"title": "coh: hub"}, {"title": "coh: sibling A"}, {"title": "coh: sibling B"}]})
        rows = {t["title"]: t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]}
        hub, A, B = rows["coh: hub"], rows["coh: sibling A"], rows["coh: sibling B"]
        call(f"/api/topics/{A}/edit?project={proj}", {"actor": "ai", "parent_slug": hub})
        call(f"/api/topics/{B}/edit?project={proj}", {"actor": "ai", "parent_slug": hub})
        # avenue: B is also reachable from A (its complement) -> B is probably a CHILD of A
        call(f"/api/topics/{B}/attach?project={proj}",
             {"actor": "ai", "parent_slug": A, "note": "the complement of A"})
        rpt = call(f"/api/topics/groom?project={proj}")
        pairs = [(h["child"], h["suggested_parent"]) for h in rpt["coherence"]["reparent_hints"]]
        self.assertIn((B, A), pairs, "avenue between siblings B<->A surfaces as 'reparent B under A'")


    def test_30_avenue_kind_default_and_reclassify(self):
        """An avenue defaults to co_parent (a real second parent); re-attaching with a kind
        reclassifies it - the judgment cosine can't make."""
        proj = "avk"
        call(f"/api/topics?project={proj}", {"actor": "ai",
             "topics": [{"title": "avk: A"}, {"title": "avk: B"}]})
        rows = {t["title"]: t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]}
        A, B = rows["avk: A"], rows["avk: B"]
        call(f"/api/topics/{A}/attach?project={proj}", {"actor": "ai", "parent_slug": B})
        kind = lambda: call(f"/api/topics/{A}?project={proj}")["topic"]["extra_parents"][0]["kind"]
        self.assertEqual(kind(), "co_parent", "avenues default to co_parent")
        call(f"/api/topics/{A}/attach?project={proj}",
             {"actor": "ai", "parent_slug": B, "kind": "see_also"})
        self.assertEqual(kind(), "see_also", "re-attaching with a kind reclassifies the avenue")


    def test_31_edit_title_and_body(self):
        """topic_edit's capability: /edit changes title/body in place (was reachable only via HTTP)."""
        proj = "ed"
        call(f"/api/topics?project={proj}", {"actor": "ai", "topics": [{"title": "ed: old title"}]})
        slug = call(f"/api/topics?project={proj}")["topics"][0]["slug"]
        r = call(f"/api/topics/{slug}/edit?project={proj}",
                 {"actor": "human", "title": "ed: renamed hub", "body": "a proper question now?"})
        self.assertTrue(r.get("ok"), r)
        t = call(f"/api/topics/{slug}?project={proj}")["topic"]
        self.assertEqual(t["title"], "ed: renamed hub")
        self.assertIn("proper question", t["body"])


    def test_32_restore_sweeps_empty_groom_hubs(self):
        """Undo removes groom-created EMPTY hubs (role='hub', post-checkpoint, childless), but keeps a
        real capture AND a hub still holding a mid-groom capture. 'Never lose a capture' stays intact."""
        proj = "hubsweep"
        call(f"/api/topics?project={proj}", {"actor": "ai",
             "topics": [{"title": "hs: A"}]})
        A = call(f"/api/topics?project={proj}")["topics"][0]["slug"]
        self.assertTrue(call(f"/api/topics/checkpoint?project={proj}", {"actor": "ai"}).get("ok"))
        # groom: mint an EMPTY hub, a hub that will HOLD a capture, and a real capture; nest under them
        call(f"/api/topics?project={proj}", {"actor": "ai", "topics": [
            {"title": "hs: EMPTY hub", "role": "hub"},
            {"title": "hs: FILLED hub", "role": "hub"},
            {"title": "hs: a real capture mid-groom"}]})
        r = {t["title"]: t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]}
        empt, fill, cap = r["hs: EMPTY hub"], r["hs: FILLED hub"], r["hs: a real capture mid-groom"]
        call(f"/api/topics/{A}/edit?project={proj}", {"actor": "ai", "parent_slug": empt})   # reverts away
        call(f"/api/topics/{cap}/edit?project={proj}", {"actor": "ai", "parent_slug": fill})  # stays
        res = call(f"/api/topics/restore?project={proj}", {"actor": "human"})
        self.assertTrue(res.get("ok"), res)
        live = [t["slug"] for t in call(f"/api/topics?project={proj}")["topics"]]
        self.assertNotIn(empt, live, "empty groom hub is swept on undo")
        self.assertIn(fill, live, "a hub still holding a mid-groom capture is kept (not empty)")
        self.assertIn(cap, live, "the mid-groom capture is never lost")
        self.assertIn(A, live, "A is restored")
        self.assertEqual(res["removed_hubs"], 1, "exactly the one empty hub was swept")


class VersionCoherenceTests(unittest.TestCase):
    """The version lives in THREE files that must move together (they have silently drifted before -
    plugin.json 0.10.0 while marketplace.json was still 0.9.0). This test makes that drift a red test,
    so a bump that misses a file cannot ship. If it fails: sync all three to the same value."""

    def _versions(self):
        import server as srv
        root = HERE.parent.parent            # repo root (…/topic-visualizer)
        pj = json.loads((root / "plugin" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        mk = json.loads((root / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        return {
            "server.VERSION": srv.VERSION,
            "plugin.json": pj["version"],
            "marketplace.json": mk["plugins"][0]["version"],
        }

    def test_version_fields_are_in_lockstep(self):
        v = self._versions()
        self.assertEqual(len(set(v.values())), 1,
                         f"version fields disagree - sync them: {v}")

    def test_changelog_covers_current_version(self):
        """The CHANGELOG silently rotted once (frozen at 0.9 while the plugin shipped to 0.28) because
        updating it wasn't part of the bump ritual. Now it IS the ritual: a release with no matching
        `## <VERSION>` heading is a red test. If it fails: add a CHANGELOG.md entry for this version."""
        import server as srv
        changelog = (HERE.parent / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## {srv.VERSION} ", changelog,
                      f"CHANGELOG.md has no entry for {srv.VERSION} - add one before shipping")


if __name__ == "__main__":
    unittest.main(verbosity=2)
