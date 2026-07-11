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


if __name__ == "__main__":
    unittest.main(verbosity=2)
