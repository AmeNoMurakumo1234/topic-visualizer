#!/usr/bin/env python3
"""find_duplicates must treat the SPINE as an edge, not only the avenues.

_annotate_judged was written for the case in front of it - a see_also edge carrying a
recorded decline - and its docstring says it marks "pairs that already carry an EDGE
between them" while querying exactly one of the two tables that hold edges. A direct
parent/child pair on the spine (topic.parent_id) came back completely unannotated.

WHY THAT IS THE DANGEROUS HALF. A genuine sub-question shares maximal vocabulary with
its parent, so spine pairs rank HIGH - the top-scoring pair in the live quantum-concepts
store (0.718) was one - and merging a child into its parent is the most destructive merge
available, because it collapses a deliberate nesting and dissolves the sub-question.

Measured on the live store before the fix: avenue pairs 3 of 3 annotated, spine pairs
0 of 5. Same call, same instrument, one difference.

    python server/test_dup_judged_spine.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402

P_TITLE = "The skill library documents a cancelled product"
P_BODY = ("Zero of the 98 skills name the live game, so the maintained library describes "
          "the website that was cancelled and the live project has almost no procedural layer.")
C_TITLE = "Can the live project reach the skill library across a repo boundary"
C_BODY = ("The live game repo carries one skill of its own plus carried-over craft skills it "
          "does not maintain, so reaching the maintained library means crossing a repo boundary.")


class SpineJudgedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db, self._conn = server.DB_PATH, server._conn
        server.DB_PATH = str(Path(self.tmp.name) / "t.db")
        server._conn = server.open_db(server.DB_PATH)
        self.p = self._add(P_TITLE, P_BODY)
        self.c = self._add(C_TITLE, C_BODY)

    def tearDown(self):
        try:
            server._conn.close()
        except Exception:
            pass
        server.DB_PATH, server._conn = self._db, self._conn
        self.tmp.cleanup()

    def _add(self, title, body):
        return server.add_topics([{"title": title, "body": body, "state": "open"}], "t")[0]["slug"]

    def _pair(self):
        for pr in server.find_duplicates("weak")["pairs"]:
            if {pr["a"], pr["b"]} == {self.p, self.c}:
                return pr
        return None

    def test_unparented_pair_carries_no_marker(self):
        """The control: siblings at root must NOT be annotated, or the marker means nothing."""
        pr = self._pair()
        self.assertIsNotNone(pr, "the fixture pair must surface at the weak band")
        self.assertNotIn("judged", pr)

    def test_spine_parent_child_pair_is_annotated(self):
        server.edit_topic(self.c, "Tare", parent_slug=self.p)
        judged = (self._pair() or {}).get("judged")
        self.assertIsNotNone(judged, "a direct parent/child pair must be reported as judged")
        self.assertEqual(judged["kind"], "parent")

    def test_spine_pair_is_still_reported(self):
        """Annotate, never suppress - same contract the avenue arm already holds."""
        server.edit_topic(self.c, "Tare", parent_slug=self.p)
        self.assertIsNotNone(self._pair(), "a spine pair must still be reported")

    def test_spine_annotation_names_who_nested_it_and_when(self):
        server.edit_topic(self.c, "Tare", parent_slug=self.p)
        judged = self._pair()["judged"]
        self.assertEqual(judged["added_by"], "Tare")
        self.assertTrue(judged.get("added_at"), "the date is what makes it skippable")
        self.assertIn("->", judged["direction"])

    def test_spine_note_says_a_merge_would_collapse_the_nesting(self):
        """A spine edge carries no authored note, so the text must be honestly STRUCTURAL
        rather than borrowing the avenue arm's voice of a recorded verdict."""
        server.edit_topic(self.c, "Tare", parent_slug=self.p)
        note = self._pair()["judged"]["note"].lower()
        self.assertIn("parent", note)
        self.assertTrue("collapse" in note or "nesting" in note,
                        "the note must say what a merge here would destroy")


    def test_the_spine_and_the_avenues_are_disjoint_for_a_pair(self):
        """No precedence rule is needed because a pair cannot carry both - two
        independent guards see to it. If either is ever relaxed, this reddens and
        whoever relaxed it inherits the precedence question instead of shipping a
        silent tie-break. (A first draft of the fix ranked avenues above the spine;
        the branch was unreachable.)"""
        server.edit_topic(self.c, "Tare", parent_slug=self.p)
        same = server.attach_parent(self.c, self.p, "Polaris", "n", False, "see_also")
        self.assertTrue(same.get("already"), "an avenue duplicating the spine must be a no-op")
        reverse = server.attach_parent(self.p, self.c, "Polaris", "n", False, "see_also")
        self.assertIn("cycle", str(reverse.get("error", "")), "the reverse avenue must be refused")
        rows = list(server._conn.execute("SELECT 1 FROM topic_parent"))
        self.assertEqual(rows, [], "neither guard may leave an avenue row behind")

if __name__ == "__main__":
    unittest.main(verbosity=2)
