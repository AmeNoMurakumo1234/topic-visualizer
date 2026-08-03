#!/usr/bin/env python3
"""Subtraction tests (0.50): prune preview, branch weight, and the discussed-is-not-free note.

A tree has to be able to get SMALLER. The report could always say it was too WIDE and never
that it was too BIG, so the only supported moves were additive. These cover the two verbs that
fix that - preview a prune before taking it, and see which branch carries the weight.

Direct-import unit tests (temp DB, no HTTP server).

    python server/test_subtraction.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402


class SubtractionTests(unittest.TestCase):
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

    def _add(self, title, parent=None, state="open", role="topic"):
        item = {"title": title, "state": state, "role": role}
        if parent:
            item["parent_slug"] = parent
        return server.add_topics([item], "t")[0]["slug"]

    def _live(self):
        return server._conn.execute(
            "SELECT COUNT(*) c FROM topic WHERE state IN "
            "('seedling','open','discussed')").fetchone()["c"]

    # -- preview ---------------------------------------------------------------
    def test_preview_writes_nothing(self):
        hub = self._add("a branch that has outgrown its reader", role="hub")
        for i in range(4):
            self._add(f"question number {i}", parent=hub)
        before = self._live()
        res = server.set_state(hub, "pruned", "t", preview=True)
        self.assertTrue(res["preview"])
        self.assertEqual(res["weight"]["total"], 5, "hub + 4 children")
        self.assertEqual(res["weight"]["undecided"], 4)
        self.assertEqual(res["weight"]["hubs"], 1)
        self.assertEqual(self._live(), before, "a PREVIEW must not change a single row")
        self.assertEqual(
            server._conn.execute("SELECT state FROM topic WHERE slug=?", (hub,)).fetchone()[0],
            "open", "the previewed node itself must survive untouched")

    def test_preview_matches_the_real_prune_exactly(self):
        """The whole point of sharing _prune_plan: the number you saw is the number you get."""
        hub = self._add("branch", role="hub")
        sub = self._add("sub branch", parent=hub, role="hub")
        for i in range(3):
            self._add(f"leaf {i}", parent=sub)
        self._add("direct child", parent=hub)
        preview = server.set_state(hub, "pruned", "t", preview=True)
        predicted = set(preview["cascade"])
        before = self._live()
        server.set_state(hub, "pruned", "t", "for real")
        actually_gone = {r["slug"] for r in server._conn.execute(
            "SELECT slug FROM topic WHERE state='pruned'")}
        self.assertEqual(predicted, actually_gone,
                         "preview promised a different set than the prune took")
        self.assertEqual(before - self._live(), preview["weight"]["total"])

    def test_preview_reports_survivors_spared_by_another_avenue(self):
        """A child reachable from OUTSIDE the pruned set is spared - the preview must say so,
        because that is exactly the case where a hand-counted subtree would be wrong."""
        doomed = self._add("doomed branch", role="hub")
        keeper = self._add("unrelated keeper branch", role="hub")
        child = self._add("child with two homes", parent=doomed)
        server.attach_parent(child, keeper, "t", "also belongs here")
        res = server.set_state(doomed, "pruned", "t", preview=True)
        self.assertIn(child, res["spared_by_another_avenue"])
        self.assertNotIn(child, res["cascade"])
        self.assertEqual(res["weight"]["total"], 1, "only the hub itself goes")

    def test_preview_refused_for_non_prune_states(self):
        from mcp_tools import _state_one

        class _B:
            def state(self, *a, **k):
                raise AssertionError("must not reach the backend")

            def priority(self, *a, **k):
                raise AssertionError("must not reach the backend")

        out = _state_one(_B(), {"slug": "x", "state": "discussed", "preview": True})
        self.assertIn("error", out)

    # -- branch weight ---------------------------------------------------------
    def test_subtraction_view_ranks_branches_by_undecided(self):
        heavy = self._add("heavy branch", role="hub")
        for i in range(6):
            self._add(f"heavy question {i}", parent=heavy)
        light = self._add("light branch", role="hub")
        self._add("light question", parent=light)
        sub = server.groom_report()["subtraction"]
        self.assertEqual(sub["branches"][0]["slug"], heavy,
                         "the branch carrying the most live questions must lead")
        self.assertEqual(sub["branches"][0]["prune_takes"]["undecided"], 6)
        self.assertGreater(sub["branches"][0]["share_of_live_pct"], 0)

    def test_weight_separates_closed_records_from_live_questions(self):
        hub = self._add("branch", role="hub")
        live = [self._add(f"still asking {i}", parent=hub) for i in range(2)]
        for i in range(3):
            s = self._add(f"already answered {i}", parent=hub)
            server.set_state(s, "discussed", "t", "covered by tracker item")
        w = server.set_state(hub, "pruned", "t", preview=True)["weight"]
        self.assertEqual(w["undecided"], len(live))
        self.assertEqual(w["discussed"], 3)
        self.assertEqual(w["total"], 6, "2 live + 3 records + the hub")

    def test_discussed_counts_toward_live_load_and_the_note_says_so(self):
        """The trap that made a groomer recommend freezing instead of pruning."""
        hub = self._add("branch", role="hub")
        s = self._add("a question", parent=hub)
        server.set_state(s, "discussed", "t", "talked through")
        sub = server.groom_report()["subtraction"]
        self.assertEqual(sub["live_load"]["discussed"], 1)
        self.assertEqual(sub["live_load"]["total"], 2,
                         "a discussed row is still carried by every scan")
        self.assertIn("reclaims NOTHING", sub["discussed_is_not_free"])

    def test_lone_leaves_are_not_reported_as_branches(self):
        for i in range(3):
            self._add(f"a lone leaf root {i}")
        self.assertEqual(server.groom_report()["subtraction"]["branches"], [],
                         "a single row is not a branch worth weighing")


if __name__ == "__main__":
    unittest.main(verbosity=2)
