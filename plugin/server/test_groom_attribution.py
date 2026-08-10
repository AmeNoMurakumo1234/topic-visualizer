#!/usr/bin/env python3
"""groom_report must NAME the store it read (issue 0798).

WHY THIS FILE EXISTS. topic_groom_report returned confident numbers - live_topics,
stale_open_count, redundant_parents - and nothing in the payload said which tree they
described. A QA agent working from a second clone ran it as a verify handle, got a
different project's tree, and two of the five PASS criteria (stale_open_count 0,
redundant_parents []) were satisfied BY THE WRONG STORE. Nothing errored and the numbers
were plausible. That is the worst failure direction we have: an absent premise reads as
reassurance, so the report fails toward a FALSE PASS.

The fix is attribution, and it has to be derived from the CONNECTION that produced the
numbers rather than from a module global - a global can disagree with the pinned
connection (that is exactly the class of bug export_topics documents in its own
docstring), and a label that can disagree with the thing it labels is not attribution.

Direct-import unit tests (KeystoneUnit style: temp DB, no HTTP server).

    python server/test_groom_attribution.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402


class GroomStoreAttributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._db = server.DB_PATH
        self._conn = server._conn
        self._proj = server._default_project
        server.DB_PATH = str(Path(self.tmp.name) / "t.db")
        server._conn = server.open_db(server.DB_PATH)

    def tearDown(self):
        try:
            server._conn.close()
        except Exception:
            pass
        server.DB_PATH = self._db
        server._conn = self._conn
        server._default_project = self._proj
        self.tmp.cleanup()

    def test_groom_report_names_the_store_it_read(self):
        """The payload carries a store block naming the db path it actually read."""
        report = server.groom_report()
        self.assertIn("store", report, "groom_report names no store - an absent premise")
        self.assertEqual(Path(report["store"]["db_path"]).resolve(),
                         Path(server.DB_PATH).resolve())

    def test_project_label_is_derived_from_the_store_file(self):
        """A per-project store reports ITS OWN key, not whatever the global happens to
        hold. This assertion was originally written the other way round - expecting the
        global - which is precisely the bug this block exists to remove, so it is pinned
        in the direction that survives a request pinned to another project."""
        self.assertEqual(server.groom_report()["store"]["project"], "t")   # <tmp>/t.db

    def test_the_shared_default_store_still_reports_default(self):
        """The one store that is NOT named after its file keeps its conventional key."""
        real_default = server.DEFAULT_DB
        try:
            server.DEFAULT_DB = server.DB_PATH        # treat the temp file AS the default
            self.assertEqual(server.groom_report()["store"]["project"], "default")
        finally:
            server.DEFAULT_DB = real_default

    def test_store_follows_the_pinned_connection_not_the_global(self):
        """The load-bearing one: the reported path must come from the connection that
        produced the numbers. A request pins _conn per project WITHOUT moving DB_PATH, so
        a report labelled off the global would name a tree it did not read."""
        other = Path(self.tmp.name) / "other.db"
        server._conn.close()
        server._conn = server.open_db(str(other))     # pinned elsewhere, DB_PATH untouched
        report = server.groom_report()
        self.assertEqual(Path(report["store"]["db_path"]).resolve(), other.resolve(),
                         "the store block followed a global instead of the live connection")

    def test_numbers_and_attribution_describe_the_same_tree(self):
        """Attribution is only worth anything if it moves WITH the counts."""
        server.add_topics([{"title": "only in the first store"}], actor="test")
        first = server.groom_report()
        self.assertEqual(first["health"]["live_topics"], 1)

        other = Path(self.tmp.name) / "second.db"
        server._conn.close()
        server._conn = server.open_db(str(other))
        second = server.groom_report()

        self.assertEqual(second["health"]["live_topics"], 0)
        self.assertNotEqual(first["store"]["db_path"], second["store"]["db_path"],
                            "two different trees reported the same store")


if __name__ == "__main__":
    unittest.main(verbosity=2)
