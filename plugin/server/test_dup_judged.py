#!/usr/bin/env python3
"""find_duplicates must report that a pair has already been JUDGED.

The ranker reads titles and bodies and nothing else, so a candidate pair a groom
examined and deliberately declined returns at the identical score every run. The verdict
IS recorded - the convention is a see_also edge carrying the reasoning - but nothing read
it, so each groom re-derived the same judgment from two long bodies. One live pair
resurfaced across four consecutive grooms that way.

The contract these pin: annotate, never suppress. The pair must still be REPORTED (a
decline is revisitable, and bodies change); it must simply arrive carrying the note,
the author and the date of the existing edge.

    python server/test_dup_judged.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402

A_TITLE = "QA verification handle for cross repo rows"
A_BODY = ("The shipped_sha handle is null for rows whose subject lives in another repo, "
          "so the verification handle degrades to unstructured prose in a free text field.")
B_TITLE = "QA verification pre-flight for generated artifacts"
B_BODY = ("The shipped_sha resolves but the artifact under test is generated, so the tree "
          "at that sha is not the thing under test and the check cannot discriminate.")


class JudgedPairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db, self._conn = server.DB_PATH, server._conn
        server.DB_PATH = str(Path(self.tmp.name) / "t.db")
        server._conn = server.open_db(server.DB_PATH)
        self.a = self._add(A_TITLE, A_BODY)
        self.b = self._add(B_TITLE, B_BODY)

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
        pairs = server.find_duplicates("weak")["pairs"]
        for p in pairs:
            if {p["a"], p["b"]} == {self.a, self.b}:
                return p
        return None

    def test_unjudged_pair_carries_no_marker(self):
        """The control: without an edge there must be no judged key to read."""
        p = self._pair()
        self.assertIsNotNone(p, "the fixture pair must surface at the weak band")
        self.assertNotIn("judged", p)

    def test_declined_pair_is_still_reported(self):
        """Annotate, never suppress - a hidden pair is an instrument that cannot go red."""
        server.attach_parent(self.b, self.a, "Tare", "declined: two different questions",
                             False, "see_also")
        self.assertIsNotNone(self._pair(), "a judged pair must still be reported")

    def test_declined_pair_carries_the_reasoning(self):
        note = "DUPLICATE CANDIDATE DECLINED - one is a missing handle, the other a wrong object."
        server.attach_parent(self.b, self.a, "Tare", note, False, "see_also")
        judged = self._pair().get("judged")
        self.assertIsNotNone(judged, "an existing edge must be surfaced on the pair")
        self.assertEqual(judged["note"], note)
        self.assertEqual(judged["added_by"], "Tare")
        self.assertEqual(judged["kind"], "see_also")
        self.assertTrue(judged.get("added_at"), "the date is what makes it skippable")

    def test_edge_is_found_in_either_direction(self):
        """The edge is one-directional; the pair is not. Whichever way it was recorded,
        the groom must see it - a cycle guard can make the mutual form impossible."""
        server.attach_parent(self.a, self.b, "Tare", "declined from the other side",
                             False, "see_also")
        judged = self._pair().get("judged")
        self.assertIsNotNone(judged)
        self.assertEqual(judged["note"], "declined from the other side")
        self.assertIn("->", judged["direction"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
