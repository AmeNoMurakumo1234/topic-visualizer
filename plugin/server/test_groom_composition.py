#!/usr/bin/env python3
"""Field-groom upgrade tests: composition-aware breadth,
hub-orphan suppression, embedder-down loud alert, over-wide reparent echo, list child
counts, seedlings-closed surfacing, and the groom_report verbose flag.

Direct-import unit tests (KeystoneUnit style: temp DB, no HTTP server).

    python server/test_groom_composition.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402


class GroomCompositionTests(unittest.TestCase):
    """Each test gets a fresh store; server module state is restored after."""

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

    # -- fixtures --------------------------------------------------------
    def _add(self, title, parent=None, state="open"):
        item = {"title": title, "state": state}
        if parent:
            item["parent_slug"] = parent
        return server.add_topics([item], "t")[0]["slug"]

    def _hub(self, title, kids=2):
        slug = self._add(title)
        for i in range(kids):
            self._add(f"{title} child {i}", parent=slug)
        return slug

    # -- (1) composition-aware breadth ------------------------------------
    def test_hub_roots_do_not_trip_breadth_warning(self):
        for i in range(server.ROOT_WARN_COUNT + 2):     # 12 roots, ALL healthy hubs
            self._hub(f"domain hub number {i}")
        g = server.groom_report()
        f = g["fan_out"]
        self.assertEqual(f["leaf_root_count"], 0)
        self.assertEqual(f["hub_root_count"], server.ROOT_WARN_COUNT + 2)
        self.assertEqual(f["root_count"], server.ROOT_WARN_COUNT + 2)
        self.assertFalse(f["breadth_warning"],
                         "hub roots are healthy structure - raw root count must not warn")

    def test_leaf_roots_trip_breadth_warning(self):
        for i in range(server.ROOT_WARN_COUNT + 2):     # 12 un-nested leaf roots = sprawl
            self._add(f"loose leaf root {i}")
        g = server.groom_report()
        f = g["fan_out"]
        self.assertEqual(f["leaf_root_count"], server.ROOT_WARN_COUNT + 2)
        self.assertTrue(f["breadth_warning"], "un-nested leaf roots are the real sprawl")

    # -- (2) hubs are never offered as orphans -----------------------------
    def test_hub_root_not_offered_as_orphan(self):
        big = self._hub("quantum computing research hub", kids=2)
        small = self._hub("quantum error mitigation hub", kids=2)   # root hub, similar to big
        leaf = self._add("quantum decoherence question")            # leaf root, similar
        server._embed = lambda texts: [
            [1.0, 0.0] if "quantum" in t else [0.0, 1.0] for t in texts]
        hints, note = server._root_orphan_hints()
        by_orphan = {h["orphan"]: h for h in hints}
        self.assertIn(leaf, by_orphan, "a leaf root still gets its hint")
        self.assertNotIn(small, by_orphan,
                         "a root that IS a hub (>=2 live children) must not be offered "
                         "as an orphan - hub-under-hub hints bury top-level domains")
        self.assertNotIn(big, by_orphan)

    # -- (3) embedder-down alert leads the report --------------------------
    def test_embedder_down_alert_leads_groom_report(self):
        self._hub("some hub")                    # a hub exists, so hints WOULD be computed
        self._add("a lone leaf root")
        server._embed = lambda texts: None       # embedder down
        g = server.groom_report()
        self.assertIn("alert", g)
        self.assertEqual(list(g.keys())[0], "alert",
                         "the embedder-down alert must be the FIRST key, not buried")
        self.assertIn("embedder", g["alert"].lower())

    def test_no_alert_when_embedder_up(self):
        self._hub("some hub")
        self._add("a lone leaf root")
        server._embed = lambda texts: [[1.0, 0.0] for _ in texts]
        g = server.groom_report()
        self.assertNotIn("alert", g, "no alert key when the embedder answered")

    # -- (4a) reparent echoes an over-wide push ----------------------------
    def test_reparent_echoes_over_wide_hub(self):
        hub = self._hub("busy hub", kids=server.FANOUT_WARN_CHILDREN)   # at the threshold
        extra = self._add("one more child")
        res = server.edit_topic(extra, "t", parent_slug=hub)            # pushes it OVER
        self.assertTrue(res.get("ok"))
        ow = res.get("over_wide")
        self.assertIsNotNone(ow, "a reparent that pushes a hub over-wide must say so")
        self.assertEqual(ow["parent"], hub)
        self.assertEqual(ow["children"], server.FANOUT_WARN_CHILDREN + 1)

    def test_reparent_under_threshold_stays_quiet(self):
        hub = self._hub("small hub", kids=1)
        extra = self._add("second child")
        res = server.edit_topic(extra, "t", parent_slug=hub)
        self.assertTrue(res.get("ok"))
        self.assertNotIn("over_wide", res, "no noise when the hub stays in band")

    # -- (4b) topic_list carries child counts + state_note ------------------
    def test_list_topics_children_and_state_note(self):
        hub = self._hub("counted hub", kids=3)
        leaf = self._add("counted leaf")
        server.set_state(leaf, "discussed", "t", "decided: covered by tracker item X")
        rows = {r["slug"]: r for r in server.list_topics(include_archive=True)["topics"]}
        self.assertEqual(rows[hub]["children"], 3)
        self.assertEqual(rows[leaf]["children"], 0)
        self.assertIn("decided", rows[leaf]["state_note"])

    # -- (5) reconcile surfaces seedling closes -----------------------------
    def test_reconcile_counts_closed_seedlings(self):
        s = self._add("tentative seedling", state="seedling")
        o = self._add("a normal open topic")
        res = server.reconcile([
            {"slug": s, "disposition": "discussed", "note": "board-covered, owner call"},
            {"slug": o, "disposition": "discussed"}], "t")
        self.assertEqual(res["applied"], 2)
        self.assertEqual(res["seedlings_closed"], 1,
                         "closing a seedling is legal but must be SURFACED, not silent")
        by = {r["slug"]: r for r in res["results"]}
        self.assertTrue(by[s].get("was_seedling"))
        self.assertNotIn("was_seedling", by[o])

    # -- (6) verbose=False drops the repeated guidance prose ----------------
    def test_groom_report_verbose_false_drops_prose(self):
        self._hub("a hub")
        g = server.groom_report(verbose=False)
        self.assertNotIn("target", g["fan_out"])
        self.assertNotIn("note", g["coherence"])
        gv = server.groom_report()               # default stays verbose
        self.assertIn("target", gv["fan_out"])
        self.assertIn("note", gv["coherence"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class SeeAlsoIsNotAStructuralParent(unittest.TestCase):
    """A see_also is a WEAK cross-link by its own tool's definition ('a quiet dashed see-also'),
    but the redundant_parents detector built ancestry from every topic_parent row with no filter
    on rel. Measured consequence (2026-08-10, live QC store): a node with a real hub parent and
    one see_also to a SIBLING under that hub was reported with the HUB edge as redundant and the
    see_also target as keep_parent - i.e. the highest-trust hint in the report recommended
    deleting the correct spine edge and re-hanging the node off a weak cross-link. The
    recommendation INVERTS, on the hint whose own note says 'a near-certain cleanup'."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db = server.DB_PATH
        self._conn = server._conn
        self._embed = server._embed
        server.DB_PATH = str(Path(self.tmp.name) / "t.db")
        server._conn = server.open_db(server.DB_PATH)
        server._embed = lambda texts: None          # keyword mode: deterministic, no embedder

    def tearDown(self):
        try:
            server._conn.close()
        except Exception:
            pass
        server.DB_PATH = self._db
        server._conn = self._conn
        server._embed = self._embed
        self.tmp.cleanup()

    def _add(self, title, parent=None):
        item = {"title": title}
        if parent:
            item["parent_slug"] = parent
        return server.add_topics([item], "t")[0]["slug"]

    def test_see_also_to_a_sibling_is_not_redundancy(self):
        """The measured inversion, reproduced exactly: hub -> {node, sibling}, node --see_also-->
        sibling. The hub edge is CORRECT and must not be reported redundant."""
        hub = self._add("the hub")
        node = self._add("the node", parent=hub)
        sib = self._add("the sibling", parent=hub)
        server.attach_parent(node, sib, "t", note="related", kind="see_also")
        red = server.groom_report(verbose=False)["coherence"]["redundant_parents"]
        self.assertEqual([r for r in red if r["child"] == node], [],
                         "a weak see_also conferred ancestry and inverted the recommendation")

    def test_real_co_parent_ancestor_is_still_caught(self):
        """The filter must not lobotomise the detector: a genuine ancestor-as-second-parent
        (grandparent AND parent both parenting one node, via a real co_parent edge) is the
        true positive this hint exists for, and must still be reported."""
        grand = self._add("grandparent")
        parent = self._add("parent", parent=grand)
        node = self._add("node", parent=parent)
        server.attach_parent(node, grand, "t", note="direct too", kind="co_parent")
        red = server.groom_report(verbose=False)["coherence"]["redundant_parents"]
        mine = [r for r in red if r["child"] == node]
        self.assertEqual(len(mine), 1, "the true-positive case stopped being detected")
        self.assertEqual(mine[0]["redundant_parent"], grand)
        self.assertEqual(mine[0]["keep_parent"], parent)

    def test_see_also_chain_does_not_carry_ancestry_transitively(self):
        """Ancestry must not flow THROUGH a see_also either: node's co_parent X, where X has a
        see_also to node's other ancestor, must not convict the ancestor edge."""
        top = self._add("top")
        mid = self._add("mid", parent=top)
        node = self._add("node", parent=mid)
        other = self._add("other")
        server.attach_parent(node, other, "t", note="real second parent", kind="co_parent")
        server.attach_parent(other, top, "t", note="loose reference", kind="see_also")
        red = server.groom_report(verbose=False)["coherence"]["redundant_parents"]
        self.assertEqual([r for r in red if r["child"] == node], [],
                         "ancestry flowed through a see_also edge")
