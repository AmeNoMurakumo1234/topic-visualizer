#!/usr/bin/env python3
"""Duplicate-band reachability (0.56.1).

The tool offers three bands - dup_likely | kin | weak - and `weak` could never be reached.
near_duplicates_in EMITS only above a hardcoded floor (0.62 semantic / 0.55 keyword) while
_dup_band calls anything BELOW 0.6 / 0.55 'weak', so every hit that survived the floor was
already kin-or-better. find_duplicates('weak') therefore returned a byte-identical list to
find_duplicates('kin').

Why that is worse than a dead option: it fails in the REASSURING direction. An agent who
suspects a missed duplicate widens the band, gets the same answer, and reads a repeated
measurement as corroboration - when the tool never looked below the floor at all.

Deterministic on the KEYWORD path (the embedder is switched off in setUp), which carries the
same defect as the semantic path and needs no network.

    python server/test_dup_bands.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402


class DupBandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db, self._conn = server.DB_PATH, server._conn
        self._embed_url = server.EMBED_URL
        server.EMBED_URL = ""                      # force the deterministic keyword path
        server.DB_PATH = str(Path(self.tmp.name) / "t.db")
        server._conn = server.open_db(server.DB_PATH)

    def tearDown(self):
        try:
            server._conn.close()
        except Exception:
            pass
        server.DB_PATH, server._conn = self._db, self._conn
        server.EMBED_URL = self._embed_url
        self.tmp.cleanup()

    def _add(self, title):
        return server.add_topics([{"title": title, "state": "open"}], "t")[0]["slug"]

    def test_weak_band_reaches_a_pair_the_kin_band_does_not(self):
        """One shared token in five scores ~0.277 - squarely in the weak band, and below
        the 0.55 keyword emission floor, so ONLY a weak-band query can surface it."""
        self._add("alpha beta gamma delta epsilon")
        self._add("alpha zeta eta theta iota")

        kin = server.find_duplicates("kin")
        weak = server.find_duplicates("weak")

        self.assertEqual(kin["count"], 0,
                         "the pair is below the kin cutoff; kin must not return it")
        self.assertGreaterEqual(
            weak["count"], 1,
            "the weak band must reach BELOW the kin cutoff - otherwise widening the "
            "search returns the same list and reads as corroboration")
        self.assertEqual(weak["pairs"][0]["band"], "weak",
                         "a pair surfaced only by the weak band must be labelled weak")

    def test_kin_band_is_unchanged_by_the_fix(self):
        """The default band is the capture-time guard's own floor; lowering the weak
        floor must not quietly loosen what an ordinary groom or capture sees."""
        self._add("Duplicate detection floor and band")
        self._add("Duplicate detection band and floor thresholds")

        kin = server.find_duplicates("kin")

        self.assertEqual(kin["count"], 1, "a genuine kin pair still surfaces at kin")
        self.assertEqual(kin["pairs"][0]["band"], "kin")


class BoardBackendDupBandTests(unittest.TestCase):
    """The SIBLING of the same defect (must-know #45: one inline copy implies siblings).

    BoardBackend.duplicates re-implements find_duplicates inline and accepted a `band`
    argument it never applied - so on the board backend ALL THREE bands returned the same
    list, including dup_likely. Worse than the sqlite case, which at least honoured two of
    the three. _load is stubbed so this needs no live board; everything under test is real.
    """

    def setUp(self):
        self._embed_url = server.EMBED_URL
        server.EMBED_URL = ""                      # deterministic keyword path
        import mcp_tools
        self.backend = mcp_tools.BoardBackend()
        self.backend._load = lambda: [
            {"slug": "a", "title": "Duplicate detection floor and band", "body": ""},
            {"slug": "b", "title": "Duplicate detection band and floor thresholds",
             "body": ""},
        ]

    def tearDown(self):
        server.EMBED_URL = self._embed_url

    def test_dup_likely_does_not_return_a_merely_kin_pair(self):
        """The pair scores in the kin band. Asking for dup_likely must exclude it -
        before the fix the band argument was accepted and discarded."""
        kin = self.backend.duplicates("kin")
        strict = self.backend.duplicates("dup_likely")

        self.assertEqual(kin["count"], 1, "the kin pair surfaces at kin")
        self.assertEqual(kin["pairs"][0]["band"], "kin")
        self.assertEqual(strict["count"], 0,
                         "a kin-scored pair must not be returned when the caller asked "
                         "for dup_likely - the band argument has to be applied")


if __name__ == "__main__":
    unittest.main(verbosity=2)
