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

    # --- 0.44.2 audit pins ---
    def test_12_copy_failure_rolls_back_no_poisoned_txn(self):
        """Audit HIGH: an exception mid-copy left partial inserts PENDING on the cached
        dst conn; whichever unrelated action committed next silently landed them."""
        self._add("alpha", [{"title": "one", "state": "open"},
                            {"title": "two", "state": "open"}])
        with server._lock:
            server._use_project("beta")
        orig_event = server._event
        calls = {"n": 0}

        def bomb(*a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("boom mid-copy")
            return orig_event(*a, **k)

        server._event = bomb
        try:
            with self.assertRaises(RuntimeError):
                server.project_copy("alpha", "beta")
        finally:
            server._event = orig_event
        # the unrelated next write must NOT drag the half-copy in with it
        self._add("beta", [{"title": "unrelated later add", "state": "open"}])
        titles = [r["title"] for r in self._rows("beta", "SELECT slug, title, state FROM topic")]
        self.assertEqual(titles, ["unrelated later add"],
                         "a failed copy must leave the target byte-honest")

    def test_13_refusal_does_not_destroy_concurrent_writes(self):
        """Audit HIGH: admin refusals ran _fail() -> rollback on the SHARED pinned conn,
        lock-free - erasing another request's in-flight writes. Refusals write nothing
        and must touch nothing."""
        with server._lock:
            server._use_project("alpha")
            server._conn.execute(
                "INSERT INTO topic (slug, title, created_by, engaged_at) "
                "VALUES ('inflight', 'uncommitted victim', 't', datetime('now'))")
            # in-flight, uncommitted - now an admin typo arrives on another 'thread'
            res = server.project_copy("ghost-src", "alpha")
            self.assertTrue(res.get("error"))
            server._conn.commit()
        rows = [r["slug"] for r in self._rows("alpha")]
        self.assertIn("inflight", rows,
                      "an admin refusal must not roll back a concurrent request's writes")

    def test_14_root_store_is_not_a_manageable_board(self):
        """Audit MEDIUM: trashing the legacy root store misroutes its data to a board
        named 'topics' on restore. Admin verbs refuse it."""
        self.assertIn("root store", server.project_delete("default", "trash").get("error", ""))
        self.assertIn("root store", server.project_delete("default", "hard").get("error", ""))
        self.assertIn("root store", server.project_copy("default", "alpha").get("error", ""))
        self.assertIn("root store", server.project_copy("alpha", "default").get("error", ""))

    def test_15_same_second_double_trash_does_not_collide(self):
        """Audit LOW/MED: second-resolution trash names collided; POSIX rename would
        silently clobber the first trashed store."""
        self._add("alpha", [{"title": "first life", "state": "open"}])
        r1 = server.project_delete("alpha", "trash")
        self._add("alpha", [{"title": "second life", "state": "open"}])   # re-mint
        r2 = server.project_delete("alpha", "trash")
        self.assertTrue(r1.get("ok") and r2.get("ok"))
        self.assertNotEqual(r1["as"], r2["as"], "trash names must be unique")
        self.assertEqual(len(list(server._trash_dir().glob("alpha.*.db"))), 2,
                         "both trashed stores must survive")

    # --- 0.44.3 confirmation-audit pins ---
    def test_18_partial_trash_move_is_undone_and_refusal_is_true(self):
        """Audit F1: the .db renamed, a sidecar rename failed -> the refusal said
        'nothing happened' while the board sat HALF in trash. Move-with-undo now."""
        self._add("alpha", [{"title": "whole or nothing", "state": "open"}])
        server._close_project_conn("alpha")
        db_file = Path(server.project_db_path("alpha"))
        wal = db_file.with_name(db_file.name + "-wal")
        wal.write_bytes(b"fake wal from another process")
        orig_rename = Path.rename

        def flaky_rename(self_p, target):
            if str(self_p).endswith("-wal"):
                raise PermissionError(13, "pinned by AV", str(self_p))
            return orig_rename(self_p, target)

        Path.rename = flaky_rename
        try:
            res = server.project_delete("alpha", "trash")
        finally:
            Path.rename = orig_rename
        self.assertIn("nothing was moved", res.get("error", ""))
        self.assertTrue(db_file.exists(), "the .db must be back in projects/ (undone)")
        self.assertTrue(wal.exists(), "the sidecar stays in projects/")
        self.assertEqual(list(server._trash_dir().glob("alpha.*")), [],
                         "no residue may be stranded in trash")
        with server._lock:   # audit F8: the pinned conn must be usable after refusal
            server._conn.execute("SELECT 1")

    def test_19_restore_brings_the_sidecars_back(self):
        """Audit F2: restore moved only the .db - committed-but-uncheckpointed WAL data
        was silently dropped and the sidecars rotted in trash until the purge."""
        self._add("alpha", [{"title": "seed", "state": "open"}])
        td = server._trash_dir()
        td.mkdir(parents=True, exist_ok=True)
        (td / "ghost.20260101-000000.db").write_bytes(
            Path(server.project_db_path("alpha")).read_bytes())
        (td / "ghost.20260101-000000.db-wal").write_bytes(b"wal payload")
        res = server.project_restore("ghost.20260101-000000.db")
        self.assertTrue(res.get("ok"), res)
        base = Path(server.project_db_path("ghost"))
        self.assertTrue(base.exists())
        self.assertEqual(base.with_name(base.name + "-wal").read_bytes(), b"wal payload",
                         "the WAL sidecar must come back with the .db")

    def test_20_raced_identical_row_is_skipped_not_duplicated(self):
        """Audit F3: the IntegrityError path had no identity check - a racer committing
        an IDENTICAL topic mid-copy got silently duplicated as -copyN. The retry loop
        now re-runs the same dedup check. Also pins F4: renamed counted once per row."""
        self._add("alpha", [{"title": "raced twin", "state": "open"}])
        src_slug = self._rows("alpha")[0]["slug"]
        with server._lock:
            server._use_project("beta")
        orig = server._copy_dst_row
        state = {"hidden_once": False}

        def racing_probe(slug):
            if slug == src_slug and not state["hidden_once"]:
                state["hidden_once"] = True
                # racer commits the IDENTICAL row right after our blind check
                c = sqlite3.connect(str(Path(server.project_db_path("beta"))))
                r = self._rows("alpha", "SELECT slug, title, body, state FROM topic")[0]
                c.execute("INSERT INTO topic (slug, title, body, state, created_by, engaged_at) "
                          "VALUES (?,?,?,?, 'racer', datetime('now'))",
                          (r["slug"], r["title"], r["body"], r["state"]))
                c.commit()
                c.close()
                return None          # our check ran before the racer's commit
            return orig(slug)

        server._copy_dst_row = racing_probe
        try:
            res = server.project_copy("alpha", "beta")
        finally:
            server._copy_dst_row = orig
        self.assertEqual(res.get("skipped_identical"), 1,
                         "the raced identical row must be SKIPPED, not duplicated")
        self.assertEqual(res.get("renamed_collisions"), 0)
        slugs = [r["slug"] for r in self._rows("beta")]
        self.assertNotIn(f"{src_slug}-copy2", slugs, "no silent duplicate")

    def test_21_rerun_heals_orphaned_halfcopy_parents_and_reports(self):
        """Audit F5: pre-0.44.2 half-copy damage (created rows, parents never set) had
        become permanently unhealable under created-only reparenting. A re-run now fills
        a skipped row's NULL parent and REPORTS it; an existing parent is never touched."""
        hub = self._add("alpha", [{"title": "the hub", "state": "open"}])[0]["slug"]
        self._add("alpha", [{"title": "orphaned child", "parent_slug": hub, "state": "open"}])
        child = next(r["slug"] for r in self._rows("alpha") if "orphaned-child" in r["slug"])
        with server._lock:
            server._use_project("beta")
        server.project_copy("alpha", "beta")                       # clean full copy
        with server._lock:                                         # simulate old damage
            server._use_project("beta")
            server._conn.execute("UPDATE topic SET parent_id=NULL WHERE slug=?", (child,))
            server._conn.commit()
        res = server.project_copy("alpha", "beta")                 # the healing re-run
        self.assertEqual(res["healed_parents"], 1, res)
        c = sqlite3.connect(f"file:{Path(server.project_db_path('beta')).as_posix()}?mode=ro",
                            uri=True)
        got = c.execute("SELECT parent_id FROM topic WHERE slug=?", (child,)).fetchone()[0]
        c.close()
        self.assertIsNotNone(got, "the orphaned child must be re-parented")
        res2 = server.project_copy("alpha", "beta")                # already healed
        self.assertEqual(res2["healed_parents"], 0, "an existing parent is never touched")

    def test_22_trash_dir_normalizes_a_repointed_db_path(self):
        """Audit F7: with DB_PATH repointed at projects/<key>.db (the MCP fallback
        shape), naive parenting rooted the trash INSIDE projects/."""
        orig = server.DB_PATH
        try:
            server.DB_PATH = str(Path(self.tmp.name) / "projects" / "somekey.db")
            self.assertEqual(server._trash_dir(), Path(self.tmp.name) / "trash")
        finally:
            server.DB_PATH = orig

    def test_16_skipped_identical_rows_are_not_reparented(self):
        """Audit LOW: pass 2 mutated PRE-EXISTING dst rows (filled their NULL parent),
        contradicting the identical-topics-skip contract."""
        hub = self._add("alpha", [{"title": "src hub", "state": "open"}])[0]["slug"]
        self._add("alpha", [{"title": "shared child", "parent_slug": hub, "state": "open"}])
        with server._lock:
            server._use_project("beta")
        # beta already holds an IDENTICAL 'shared child' - but as a ROOT topic
        shared = self._add("beta", [{"title": "shared child", "state": "open"}])[0]["slug"]
        # force identical slug+content so the copy skips it
        src_child = next(r["slug"] for r in self._rows("alpha") if "shared-child" in r["slug"])
        with server._lock:
            server._use_project("beta")
            server._conn.execute("UPDATE topic SET slug=? WHERE slug=?", (src_child, shared))
            server._conn.commit()
        res = server.project_copy("alpha", "beta")
        self.assertEqual(res["skipped_identical"], 1)
        # 0.44.3 contract update (audit F5): a skipped identical row with a NULL parent
        # where the source carries one gets HEALED - and the heal is REPORTED, never
        # silent. (0.44.2's created-only rule made pre-fix half-copy damage unhealable.)
        self.assertEqual(res["healed_parents"], 1,
                         "the fill must be reported, not silent")
        parent = sqlite3.connect(
            f"file:{Path(server.project_db_path('beta')).as_posix()}?mode=ro", uri=True)
        parent.row_factory = sqlite3.Row
        row = parent.execute(
            "SELECT parent_id FROM topic WHERE slug=?", (src_child,)).fetchone()
        parent.close()
        self.assertIsNotNone(row["parent_id"], "the NULL parent is healed on merge")

    def test_17_hard_delete_recounts_inside_the_lock(self):
        """Audit MEDIUM (TOCTOU): a topic committed between the empty-check and the
        unlink was destroyed on the one non-restorable path. The locked recount
        refuses instead."""
        with server._lock:
            server._use_project("racy")          # minted empty
        db_file = Path(server.project_db_path("racy"))
        orig_close = server._close_project_conn

        def close_then_sneak(key):
            orig_close(key)
            if key == "racy":                    # a write lands in the race window
                c = sqlite3.connect(str(db_file))
                c.execute("INSERT INTO topic (slug, title, created_by, engaged_at) "
                          "VALUES ('sneaky', 'raced in', 't', datetime('now'))")
                c.commit()
                c.close()

        server._close_project_conn = close_then_sneak
        try:
            res = server.project_delete("racy", "hard")
        finally:
            server._close_project_conn = orig_close
        self.assertTrue(res.get("error"), "the locked recount must refuse")
        self.assertTrue(db_file.exists(), "the raced-in topic must survive")

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
