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
            {"title": "the soul question: how do we measure feeling? (~1 hour)",
             "body": "THE QUESTION: can layered machinery move a stranger?",
             "priority": "critical"},
            {"title": "beta reader recruiting for the first stranger read (~30 min)",
             "body": "THE QUESTION: what is the minimum viable first read?"},
        ]})
        slugs = [x["slug"] for x in r["results"]]
        self.assertEqual(len(slugs), 2)
        # near-duplicate guard fires on a re-plant of the same idea
        r2 = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "measuring feeling: the soul question again",
             "body": "how do we measure whether prose moves a stranger?"}]})
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
        # make the soul topic the beacon (it already is from test_01/02 edits)
        r = call("/api/topics/serve?context=prose%20feeling%20stranger")
        self.assertIsNotNone(r["card"])
        self.assertEqual(r["card"]["priority"], "critical",
                         "beacons outrank everything")

    def test_04_child_parenting_and_cycle_guard(self):
        r = call("/api/topics", {"actor": "ai", "topics": [
            {"title": "questionnaire design for stranger reads (~20 min)",
             "parent_slug": call("/api/topics")["topics"][0]["slug"]}]})
        child = r["results"][0]["slug"]
        parent = call("/api/topics")["topics"][0]["slug"]
        # re-parenting the PARENT under its own CHILD must be refused
        bad = call(f"/api/topics/{parent}/edit", {"actor": "human", "parent_slug": child})
        self.assertIn("cycle", str(bad.get("error", "")))

    def test_05_search_ranks(self):
        r = call("/api/topics/search?q=stranger%20reads")
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
            {"title": "cars: a branch to prune"},
        ]})
        root = r["results"][0]["slug"]
        call("/api/topics", {"actor": "ai", "topics": [
            {"title": "cars: child one", "parent_slug": root},
            {"title": "cars: child two", "parent_slug": root}]})
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
