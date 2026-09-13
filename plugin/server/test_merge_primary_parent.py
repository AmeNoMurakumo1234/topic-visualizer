#!/usr/bin/env python3
"""A merge must not leave the survivor stranded at ROOT.

topic_merge's own description promises it will "transfer its parent/extra edges". Step 3
folded EVERY parent of the absorbed topic - its primary included - into the survivor's
extra_parents as a "merged avenue". When the survivor already has a primary parent that is
correct: the absorbed topic's parent is a genuine second avenue. When the survivor has NO
primary parent there is nothing to conflict with, and demoting the absorbed topic's PRIMARY
edge to an avenue silently strands the survivor at root.

WHY IT IS NOT COSMETIC. The primary parent IS the tree spine. A survivor left at root keeps
counting as a LEAF ROOT in the groom report's fan_out, so every merge of this shape nudges
leaf_root_count up and pushes breadth_warning toward tripping, while the hub the survivor
belongs under reads thinner than it is. Both effects are invisible at the call site: ok true,
no warning, and moved_children counts CHILDREN, not the parent edge. The next groom sees a new
un-nested leaf root and cannot tell it from organic sprawl.

Filed as quantum-concepts 1524 with this repro.

    python server/test_merge_primary_parent.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402


class MergePrimaryParentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db, self._conn = server.DB_PATH, server._conn
        server.DB_PATH = str(Path(self.tmp.name) / "t.db")
        server._conn = server.open_db(server.DB_PATH)

    def tearDown(self):
        try:
            server._conn.close()
        except Exception:
            pass
        server.DB_PATH, server._conn = self._db, self._conn
        self.tmp.cleanup()

    def _add(self, title, parent=None):
        item = {"title": title, "body": title + " body text for the ranker to chew on.",
                "state": "open"}
        if parent:
            item["parent_slug"] = parent
        return server.add_topics([item], "t")[0]["slug"]

    def test_absorbed_primary_becomes_survivors_primary_when_survivor_is_at_root(self):
        p = self._add("Hub about measurement instruments")
        a = self._add("Absorbed topic under the hub", parent=p)
        b = self._add("Survivor topic sitting at root")
        server.merge_topics(b, a, "Tare")          # (into, from)
        got = server.get_topic(b)["topic"]
        self.assertEqual(got["parent_slug"], p,
                         "the absorbed topic's PRIMARY parent must become the survivor's primary")

    def test_survivor_is_no_longer_counted_as_a_leaf_root(self):
        """The reason the bug matters: it inflates the breadth alarm's own input."""
        p = self._add("Hub about measurement instruments")
        a = self._add("Absorbed topic under the hub", parent=p)
        b = self._add("Survivor topic sitting at root")
        before = server.groom_report()["fan_out"]["leaf_root_count"]
        server.merge_topics(b, a, "Tare")
        after = server.groom_report()["fan_out"]["leaf_root_count"]
        # Assert on the ALARM'S OWN INPUT, not on a field name I might read wrong: the first
        # draft of this test filtered list_topics on "parent_slug", a key that payload does not
        # carry (it is "parent"), so every row looked like a root and the test could not have
        # passed on correct code either. The groom report is the surface the bug actually
        # corrupts, so let it be the witness.
        self.assertEqual(after, before - 1,
                         "absorbing a parented topic must REMOVE a leaf root, not preserve one")
        roots = [t for t in server.list_topics()["topics"]
                 if not t.get("parent") and t["state"] in ("seedling", "open", "discussed")]
        self.assertNotIn(b, [t["slug"] for t in roots],
                         "a merged survivor must not be left counting as an un-nested leaf root")

    def test_promoted_edge_is_not_also_left_as_a_duplicate_avenue(self):
        p = self._add("Hub about measurement instruments")
        a = self._add("Absorbed topic under the hub", parent=p)
        b = self._add("Survivor topic sitting at root")
        server.merge_topics(b, a, "Tare")
        avenues = [e["slug"] for e in server.get_topic(b)["topic"]["extra_parents"]]
        self.assertNotIn(p, avenues,
                         "the edge was promoted to primary, so it must not ALSO be an avenue")

    def test_existing_primary_is_never_overwritten(self):
        """The control. When the survivor HAS a primary, current behaviour is correct and the
        absorbed topic's parent is a real second avenue - this must not change."""
        p1 = self._add("First hub about instruments")
        p2 = self._add("Second hub about scope and reach")
        a = self._add("Absorbed topic under the second hub", parent=p2)
        b = self._add("Survivor topic under the first hub", parent=p1)
        server.merge_topics(b, a, "Tare")
        got = server.get_topic(b)["topic"]
        self.assertEqual(got["parent_slug"], p1, "an existing primary must be left alone")
        self.assertIn(p2, [e["slug"] for e in got["extra_parents"]],
                      "the absorbed topic's parent is still a genuine second avenue")

    def test_a_root_to_root_merge_still_leaves_the_survivor_at_root(self):
        """The other control: nothing to promote means nothing invented."""
        a = self._add("Absorbed topic at root about instruments")
        b = self._add("Survivor topic at root about instruments")
        server.merge_topics(b, a, "Tare")
        self.assertIsNone(server.get_topic(b)["topic"]["parent_slug"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
