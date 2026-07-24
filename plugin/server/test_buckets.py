#!/usr/bin/env python3
"""Grouped-triage tests (Polaris brief 2, owner-ratified pattern, 2026-07-24):
topic_buckets clusters live topics into hub-seeded buckets; topic_reconcile gains a
uniform bucket-level `decision` stamp and the first-class `leave_open` disposition.

Direct-import unit tests (temp DB, no HTTP server).

    python server/test_buckets.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db = server.DB_PATH
        self._conn = server._conn
        self._embed = server._embed
        server.DB_PATH = str(Path(self.tmp.name) / "t.db")
        server._conn = server.open_db(server.DB_PATH)

    def tearDown(self):
        try:
            server._conn.close()
        except Exception:
            pass
        server.DB_PATH = self._db
        server._conn = self._conn
        server._embed = self._embed
        self.tmp.cleanup()

    def _add(self, title, parent=None, state="open"):
        item = {"title": title, "state": state}
        if parent:
            item["parent_slug"] = parent
        return server.add_topics([item], "t")[0]["slug"]

    def _hub(self, title, kids=2):
        slug = self._add(title)
        for i in range(kids):
            self._add(f"{title} member {i}", parent=slug)
        return slug


class BucketTests(Base):
    def test_buckets_seed_from_hub_structure(self):
        a = self._hub("quantum computing research", kids=3)
        b = self._hub("sourdough baking experiments", kids=2)
        out = server.topic_buckets()
        keys = {bk["key"] for bk in out["buckets"]}
        self.assertEqual(keys, {a, b})
        by_key = {bk["key"]: bk for bk in out["buckets"]}
        # the hub root itself is live -> it is a member of its own bucket (a ruling may close it)
        self.assertEqual(by_key[a]["live_count"], 4)
        self.assertEqual(by_key[b]["live_count"], 3)

    def test_discussed_topics_are_not_members(self):
        a = self._hub("a real hub", kids=2)
        done = self._add("already answered", parent=a)
        server.set_state(done, "discussed", "t", "answered")
        out = server.topic_buckets()
        members = [m["slug"] for bk in out["buckets"] for m in bk["members"]]
        self.assertNotIn(done, members, "triage serves undecided topics only")

    def test_homeless_leaf_root_assigned_semantically(self):
        hub = self._hub("quantum error correction hub", kids=2)
        self._hub("gardening notes hub", kids=2)
        leaf = self._add("quantum decoherence question")     # childless root, no hub home
        server._embed = lambda texts: [
            [1.0, 0.0] if "quantum" in t else [0.0, 1.0] for t in texts]
        out = server.topic_buckets()
        by_key = {bk["key"]: bk for bk in out["buckets"]}
        m = {x["slug"]: x for x in by_key[hub]["members"]}
        self.assertIn(leaf, m, "a homeless leaf root joins its semantic hub bucket")
        self.assertEqual(m[leaf]["via"], "semantic")
        self.assertGreater(m[leaf].get("score", 0), 0)

    def test_embedder_down_leaves_homeless_unbucketed_loudly(self):
        self._hub("a hub", kids=2)
        leaf = self._add("a lone leaf root")
        server._embed = lambda texts: None
        out = server.topic_buckets()
        self.assertIn(leaf, [m["slug"] for m in out["unbucketed"]])
        self.assertIn("alert", out)
        self.assertIn("embedder", out["alert"].lower())

    def test_max_buckets_pools_smallest_into_other(self):
        big1 = self._hub("big one", kids=5)
        big2 = self._hub("big two", kids=4)
        small = [self._hub(f"small hub {i}", kids=1) for i in range(4)]
        out = server.topic_buckets(max_buckets=3)
        keys = [bk["key"] for bk in out["buckets"]]
        self.assertEqual(len(keys), 3)
        self.assertIn(big1, keys)
        self.assertIn(big2, keys)
        self.assertIn("other", keys)
        other = next(bk for bk in out["buckets"] if bk["key"] == "other")
        pooled_roots = {m.get("root") for m in other["members"]}
        self.assertTrue(set(small) <= pooled_roots,
                        "pooled members must remember their true root")

    def test_stale_and_links_ride_the_members(self):
        hub = self._hub("stale watch hub", kids=1)
        old = self._add("an old open question", parent=hub)
        with server._lock:
            server._conn.execute(
                "UPDATE topic SET engaged_at = datetime('now','-40 days') WHERE slug=?", (old,))
            server._conn.execute(
                "INSERT INTO topic_link (topic_id, kind, ref, note) "
                "SELECT id, 'work_item', 'TRK-42', '' FROM topic WHERE slug=?", (old,))
            server._conn.commit()
        out = server.topic_buckets()
        bk = next(b for b in out["buckets"] if b["key"] == hub)
        m = {x["slug"]: x for x in bk["members"]}
        self.assertTrue(m[old]["stale"])
        self.assertEqual(m[old]["links"], [{"kind": "work_item", "ref": "TRK-42"}])
        self.assertGreaterEqual(bk["stale_count"], 1)
        self.assertGreaterEqual(bk["linked_count"], 1)


class DecisionStampTests(Base):
    def test_decision_stamped_on_every_applied_member(self):
        t1 = self._add("bucket member one")
        t2 = self._add("bucket member two")
        res = server.reconcile(
            [{"slug": t1, "disposition": "discussed"},
             {"slug": t2, "disposition": "discussed", "note": "extra detail"}],
            "t", decision="owner ruling: covered by the auth epic")
        self.assertEqual(res["applied"], 2)
        with server._lock:
            notes = [r["note"] for r in server._conn.execute(
                "SELECT e.note FROM topic_event e JOIN topic t ON t.id=e.topic_id "
                "WHERE e.event='reconciled' AND t.slug IN (?,?)", (t1, t2))]
        for n in notes:
            self.assertIn("owner ruling: covered by the auth epic", n,
                          "the bucket-level decision must stamp EVERY member")
        self.assertTrue(any("extra detail" in n for n in notes),
                        "a per-item note rides along with the decision, not instead of it")

    def test_leave_open_records_ruling_without_touching_state(self):
        t = self._add("deliberately left open")
        with server._lock:
            before = server._conn.execute(
                "SELECT state, engaged_at FROM topic WHERE slug=?", (t,)).fetchone()
        res = server.reconcile(
            [{"slug": t, "disposition": "leave_open"}],
            "t", decision="owner ruling: park all except the beacon")
        self.assertEqual(res["applied"], 1)
        by = {r["slug"]: r for r in res["results"]}
        self.assertTrue(by[t]["ok"])
        self.assertEqual(by[t]["disposition"], "leave_open")
        with server._lock:
            after = server._conn.execute(
                "SELECT state, engaged_at FROM topic WHERE slug=?", (t,)).fetchone()
            ev = server._conn.execute(
                "SELECT e.note FROM topic_event e JOIN topic t2 ON t2.id=e.topic_id "
                "WHERE e.event='reconciled' AND t2.slug=?", (t,)).fetchone()
        self.assertEqual(after["state"], "open", "leave_open changes NO state")
        self.assertEqual(after["engaged_at"], before["engaged_at"],
                         "a bulk ruling must not reset the engagement/staleness clock")
        self.assertIn("park all except the beacon", ev["note"])

    def test_leave_open_seedling_is_not_flagged_as_closed(self):
        s = self._add("seedling left alone", state="seedling")
        res = server.reconcile([{"slug": s, "disposition": "leave_open"}], "t",
                               decision="ruling")
        self.assertEqual(res["seedlings_closed"], 0, "leave_open closes nothing")
        by = {r["slug"]: r for r in res["results"]}
        self.assertNotIn("was_seedling", by[s])

    def test_mixed_batch_sub_selection(self):
        keep = self._add("the beacon we keep")
        close1 = self._add("member covered by tracker")
        close2 = self._add("member absorbed into epic")
        res = server.reconcile(
            [{"slug": keep, "disposition": "leave_open"},
             {"slug": close1, "disposition": "discussed"},
             {"slug": close2, "disposition": "converted", "ref": "TRK-7"}],
            "t", decision="owner ruling on the research bucket")
        self.assertEqual(res["applied"], 3)
        self.assertEqual(res["errors"], 0)
        with server._lock:
            states = {r["slug"]: r["state"] for r in server._conn.execute(
                "SELECT slug, state FROM topic WHERE slug IN (?,?,?)",
                (keep, close1, close2))}
        self.assertEqual(states[keep], "open")
        self.assertEqual(states[close1], "discussed")
        self.assertEqual(states[close2], "discussed")   # converted lands as discussed+link


if __name__ == "__main__":
    unittest.main(verbosity=2)
