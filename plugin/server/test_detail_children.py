#!/usr/bin/env python3
"""get_topic's `children` must mean what every WIDTH rule in the server means by it.

The detail view used to return children unfiltered, while list_topics and the groom
report's over_wide both count only live states. Two instruments, two numbers, no marker
on either. A groom enumerating a hub's membership from the detail view therefore
inherited merge tombstones and pruned rows - which happened in the field: a row merged
away three days earlier was carried into a frozen member list, and the hub it described
read 13 children in the detail view against 12 in every width instrument.

These tests pin the agreement, not the implementation: whatever get_topic reports as
`children` must equal what the groom report counts for that same parent.

    python server/test_detail_children.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402


class DetailChildrenTests(unittest.TestCase):
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

    def _add(self, title, parent=None, state="open"):
        item = {"title": title, "state": state}
        if parent:
            item["parent_slug"] = parent
        return server.add_topics([item], "t")[0]["slug"]

    def _detail(self, slug):
        return server.get_topic(slug)["topic"]

    def _over_wide_count(self, slug):
        """What the groom report thinks this parent's child count is."""
        rep = server.groom_report()
        for row in rep.get("fan_out", {}).get("widest", []):
            if row["slug"] == slug:
                return row["children"]
        return 0

    def test_pruned_child_is_not_in_children(self):
        hub = self._add("hub")
        live = self._add("live child", parent=hub)
        dead = self._add("doomed child", parent=hub)
        server.set_state(dead, "pruned", "t", "no longer relevant")

        detail = self._detail(hub)
        self.assertEqual(detail["children"], [live],
                         "a pruned child must not be reported as a child")
        self.assertEqual(detail["children_archived"], [dead],
                         "the pruned child must stay reachable, not vanish")

    def test_merge_tombstone_is_not_in_children(self):
        hub = self._add("hub")
        survivor = self._add("survivor", parent=hub)
        absorbed = self._add("absorbed", parent=hub)
        # NOTE the argument order: merge_topics(into, from, ...), which is the REVERSE of
        # the topic_merge tool's (from, into). Getting it backwards here merged the
        # survivor away and produced a failure that looked exactly like a product defect.
        server.merge_topics(survivor, absorbed, "t")

        detail = self._detail(hub)
        self.assertNotIn(absorbed, detail["children"],
                         "a merge tombstone must not be reported as a live child")
        self.assertIn(absorbed, detail["children_archived"])

    def test_detail_agrees_with_the_groom_report(self):
        """The regression that actually bit: the two instruments disagreeing."""
        hub = self._add("wide hub")
        for i in range(11):
            self._add(f"child {i}", parent=hub)
        doomed = self._add("child 11", parent=hub)
        server.set_state(doomed, "pruned", "t", "")

        detail = self._detail(hub)
        self.assertEqual(len(detail["children"]), 11)
        self.assertEqual(len(detail["children"]), self._over_wide_count(hub),
                         "detail view and groom report must count the same children")

    def test_discussed_still_counts_as_live(self):
        """discussed is LIVE everywhere else in this file; do not quietly drop it."""
        hub = self._add("hub")
        kid = self._add("settled child", parent=hub)
        server.set_state(kid, "discussed", "t", "resolved")

        detail = self._detail(hub)
        self.assertEqual(detail["children"], [kid])
        self.assertEqual(detail["children_archived"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
