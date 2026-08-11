#!/usr/bin/env python3
"""Per-item actor attribution + loud unknown item keys (the silently-eaten-key defect).

THE DEFECT (filed 2026-08-08, verified against source before fixing): add_topics took `actor`
only as a call-level argument, and an item carrying its own `actor` key had it SILENTLY dropped -
the capture landed attributed to the transport default ('ai' over MCP, 'unknown' over bare HTTP).
Nothing errored, the result looked normal, and the misattribution surfaced two layers away: the
groom report's per-actor capture CALIBRATION - the evidence base for tuning the auto-filer bars -
counts kept/pruned per actor, so quietly re-labelled captures poison the one instrument that is
supposed to learn from human behaviour. The live QC store carries 'unknown' and 'ai' calibration
rows that are really other agents' captures.

The same swallow generalises: ANY unknown per-item key vanishes. Capture must never FAIL on a
typo (an over-captured seedling costs nothing; a lost idea is gone), so unknown keys are not an
error - but they must be LOUD in the result, because a dropped key and an honoured key returning
the same shape is the absent-premise pattern this codebase keeps paying for.

    python server/test_item_actor.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402


class ItemActorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db = server.DB_PATH
        self._conn = server._conn
        self._embed = server._embed
        server.DB_PATH = str(Path(self.tmp.name) / "t.db")
        server._conn = server.open_db(server.DB_PATH)
        server._embed = lambda texts: None

    def tearDown(self):
        try:
            server._conn.close()
        except Exception:
            pass
        server.DB_PATH = self._db
        server._conn = self._conn
        server._embed = self._embed
        self.tmp.cleanup()

    def _created_by(self, slug):
        return server._conn.execute(
            "SELECT created_by FROM topic WHERE slug=?", (slug,)).fetchone()["created_by"]

    def test_per_item_actor_wins_over_the_call_level_default(self):
        """The defect itself: an item naming its own actor must be attributed to that actor."""
        r = server.add_topics([{"title": "captured on behalf of Joule", "actor": "Joule"}], "ai")
        self.assertEqual(self._created_by(r[0]["slug"]), "Joule")

    def test_items_without_their_own_actor_keep_the_call_level_one(self):
        r = server.add_topics([{"title": "plain capture"}], "Vera")
        self.assertEqual(self._created_by(r[0]["slug"]), "Vera")

    def test_mixed_batch_attributes_each_item_independently(self):
        r = server.add_topics([{"title": "one", "actor": "Iris"},
                               {"title": "two"}], "Codex")
        self.assertEqual(self._created_by(r[0]["slug"]), "Iris")
        self.assertEqual(self._created_by(r[1]["slug"]), "Codex")

    def test_unknown_item_keys_are_loud_in_the_result_not_swallowed(self):
        """A typo ('paren_slug') must not vanish. Not an error - capture never fails on a typo -
        but the result names what it ignored, so a dropped key and an honoured key can never
        return the same shape."""
        r = server.add_topics([{"title": "typo capture", "paren_slug": "somewhere",
                                "prority": "critical"}], "t")
        self.assertNotIn("error", r[0])
        self.assertEqual(sorted(r[0].get("ignored_keys", [])), ["paren_slug", "prority"])

    def test_known_keys_are_not_reported_as_ignored(self):
        r = server.add_topics([{"title": "full capture", "body": "b", "state": "seedling",
                                "priority": "critical", "tags": "x", "provenance": "p",
                                "role": "topic", "actor": "t2"}], "t")
        self.assertNotIn("ignored_keys", r[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
