#!/usr/bin/env python3
"""0.44 Projects management tests (owner design 2026-07-20: a 4th page where the BOARDS
are the objects - copy topics between boards, trash/restore, hard-delete empty mints).

What this locks:
  COPY  - merge-copy with dedup: identical topics skip, colliding slugs rename, parent
          structure + extra avenues land, the REAL engagement clock carries (no
          laundering), source is byte-untouched, rerunning is a no-op.
  DELETE- trash moves the store (restorable), hard delete works ONLY on an empty board
          (the bogus-URL-mint cleanup) and refuses a non-empty one.
  LOCKS - a store with a LIVE cached connection can still be trashed (Windows holds an
          open sqlite handle as a file lock - the conn must be closed first).
  RESTORE - a trashed store comes back; restore refuses to clobber a live store.
  PURGE - trash older than the cutoff is unlinked; younger survives.

Unit-level, drives server.py against temp per-project stores (no HTTP).

    python server/test_projects_admin.py
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402


class ProjectsAdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self._orig = (server.DB_PATH, server.DEFAULT_DB, getattr(server, "_conn", None),
                      dict(server._conns), server._default_project)
        root = Path(self.tmp.name)
        server.DEFAULT_DB = str(root / "topics.db")
        server.DB_PATH = server.DEFAULT_DB
        server._conns.clear()
        server._default_project = "alpha"
        with server._lock:
            server._use_project("alpha")

    def tearDown(self):
        for c in server._conns.values():
            try:
                c.close()
            except Exception:
                pass
        server._conns.clear()
        (server.DB_PATH, server.DEFAULT_DB, server._conn,
         conns, server._default_project) = self._orig
        server._conns.update(conns)
        self.tmp.cleanup()

    def _add(self, key, items):
        with server._lock:
            prev = server._default_project
            server._use_project(key)
            out = server.add_topics(items, "t")
            server._use_project(prev)
        return out

    def _rows(self, key, q="SELECT slug, title, state FROM topic ORDER BY slug"):
        c = sqlite3.connect(f"file:{Path(server.project_db_path(key)).as_posix()}?mode=ro",
                            uri=True)
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(q)]
        c.close()
        return rows

    # --- COPY ---
    def test_01_copy_preserves_structure_and_clock(self):
        hub = self._add("alpha", [{"title": "a hub", "state": "open"}])[0]["slug"]
        kid = self._add("alpha", [{"title": "a child", "parent_slug": hub,
                                   "state": "seedling"}])[0]["slug"]
        with server._lock:
            server._use_project("alpha")
            server._conn.execute(
                "UPDATE topic SET engaged_at = '2026-05-01 00:00:00' WHERE slug=?", (kid,))
            server._conn.commit()
            server._use_project("beta")   # mint the target store
        res = server.project_copy("alpha", "beta")
        self.assertEqual((res["copied"], res["skipped_identical"]), (2, 0))
        c = sqlite3.connect(f"file:{Path(server.project_db_path('beta')).as_posix()}?mode=ro",
                            uri=True)
        c.row_factory = sqlite3.Row
        got = {r["slug"]: dict(r) for r in c.execute(
            """SELECT t.slug, t.engaged_at, p.slug AS parent FROM topic t
               LEFT JOIN topic p ON p.id = t.parent_id""")}
        c.close()
        self.assertEqual(got[kid]["parent"], hub, "parent structure must land")
        self.assertEqual(got[kid]["engaged_at"], "2026-05-01 00:00:00",
                         "the REAL engagement clock carries - no laundering")

    def test_02_copy_rerun_is_a_noop_and_source_untouched(self):
        self._add("alpha", [{"title": "one", "state": "open"},
                            {"title": "two", "state": "open"}])
        with server._lock:
            server._use_project("beta")
        before = Path(server.project_db_path("alpha")).read_bytes()
        server.project_copy("alpha", "beta")
        res2 = server.project_copy("alpha", "beta")
        self.assertEqual((res2["copied"], res2["skipped_identical"]), (0, 2),
                         "rerun must dedup everything")
        self.assertEqual(Path(server.project_db_path("alpha")).read_bytes(), before,
                         "copy must never write the source store")

    def test_03_copy_slug_collision_renames(self):
        self._add("alpha", [{"title": "same slug seed", "state": "open"}])
        with server._lock:
            server._use_project("beta")
        slug = self._rows("alpha")[0]["slug"]
        with server._lock:
            server._use_project("beta")
            server.add_topics([{"title": "same slug seed", "state": "open"}], "t")
            server._conn.execute("UPDATE topic SET body='DIFFERENT content' WHERE slug=?",
                                 (self._rows("beta")[0]["slug"],))
            server._conn.commit()
        # force identical slugs across stores for the collision case
        with server._lock:
            server._use_project("beta")
            server._conn.execute("UPDATE topic SET slug=? WHERE 1=1", (slug,))
            server._conn.commit()
        res = server.project_copy("alpha", "beta")
        self.assertEqual(res["renamed_collisions"], 1)
        slugs = [r["slug"] for r in self._rows("beta")]
        self.assertIn(f"{slug}-copy2", slugs)

    def test_04_copy_refuses_self_and_missing(self):
        self.assertTrue(server.project_copy("alpha", "alpha").get("error"))
        self.assertTrue(server.project_copy("alpha", "never-made").get("error"))
        self.assertTrue(server.project_copy("ghost", "alpha").get("error"))

    # --- DELETE / RESTORE / PURGE ---
    def test_05_trash_and_restore_roundtrip(self):
        self._add("alpha", [{"title": "keep me", "state": "open"}])
        res = server.project_delete("alpha", "trash")
        self.assertTrue(res.get("ok"))
        self.assertFalse(Path(server.project_db_path("alpha")).exists())
        name = res["as"]
        back = server.project_restore(name)
        self.assertTrue(back.get("ok"))
        self.assertEqual(self._rows("alpha")[0]["title"], "keep me")

    def test_06_trash_closes_the_live_cached_connection(self):
        """Windows: an open sqlite handle locks the file - trash must close it first."""
        self._add("alpha", [{"title": "locked", "state": "open"}])
        with server._lock:
            server._use_project("alpha")   # conn now cached + open
        self.assertIn("alpha", server._conns)
        res = server.project_delete("alpha", "trash")
        self.assertTrue(res.get("ok"), f"trash must succeed with a cached conn: {res}")
        self.assertNotIn("alpha", server._conns, "the cached conn must be dropped")

    def test_07_hard_delete_only_for_empty_boards(self):
        self._add("alpha", [{"title": "not empty", "state": "open"}])
        self.assertIn("refused", server.project_delete("alpha", "hard").get("error", ""))
        with server._lock:
            server._use_project("bogus-mint")   # the mangled-URL case: minted, empty
        res = server.project_delete("bogus-mint", "hard")
        self.assertTrue(res.get("ok"))
        self.assertFalse(Path(server.project_db_path("bogus-mint")).exists())
        self.assertEqual(list(server._trash_dir().glob("*bogus-mint*")), [],
                         "hard delete must not leave a trash copy")

    def test_08_restore_refuses_to_clobber_a_live_store(self):
        self._add("alpha", [{"title": "v1", "state": "open"}])
        name = server.project_delete("alpha", "trash")["as"]
        with server._lock:
            server._use_project("alpha")   # a NEW live store under the same key
        res = server.project_restore(name)
        self.assertTrue(res.get("error"), "restore must refuse to clobber a live store")

    def test_09_purge_respects_the_cutoff(self):
        self._add("alpha", [{"title": "old", "state": "open"}])
        server.project_delete("alpha", "trash")
        old = next(server._trash_dir().glob("*.db"))
        import os
        os.utime(old, (time.time() - 40 * 86400, time.time() - 40 * 86400))
        self._add("beta", [{"title": "young", "state": "open"}])
        server.project_delete("beta", "trash")
        n = server.purge_trash(30)
        self.assertEqual(n, 1, "only the aged-out store purges")
        self.assertEqual(len(list(server._trash_dir().glob("*.db"))), 1)

    def test_11_expire_sweep_releases_the_handles_it_opened(self):
        """0.44.1: the sweep opened+cached a conn to EVERY store forever, making the
        server a Windows file-lock on all of them - deletes from any other process hit
        WinError 32. Sweep-only opens must be released; in-use stores stay cached."""
        self._add("alpha", [{"title": "used", "state": "open"}])       # alpha = in use
        with server._lock:
            server._use_project("beta")                                # beta exists,
            server._use_project(server._default_project)               # then released? no -
        server._close_project_conn("beta")                             # simulate not-in-use
        server.expire_all()
        self.assertNotIn("beta", server._conns,
                         "a store only the sweep touched must not stay cached")
        self.assertIn(server._safe_key(server._default_project), server._conns,
                      "the default store stays pinned")

    def test_10_overview_reads_without_minting(self):
        self._add("alpha", [{"title": "x", "state": "open"}])
        before = set(Path(server.project_db_path("alpha")).parent.glob("*.db"))
        ov = server.projects_overview()
        after = set(Path(server.project_db_path("alpha")).parent.glob("*.db"))
        self.assertEqual(before, after, "an overview must never mint a store")
        row = next(b for b in ov["boards"] if b["key"] == "alpha")
        self.assertEqual(row["live"], 1)
        self.assertFalse(row["empty"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
