#!/usr/bin/env python3
"""The project dropdown must not be a constructor, and one store must be one entry.

Field report (vm-dev-fyibos-newbot, 2026-08-11): "if someone touches the dropdown and picks
default or the 2nd FyiBOS the board goes dark and is a major pain to get it to reload."

Three verified mechanisms behind that sentence:

1. THE MINT. _use_project opened the store unconditionally and sqlite CREATES a missing file,
   so SELECTING a project that does not exist silently minted an empty store and pinned the
   view to it - a mis-click indistinguishable from a genuinely empty board. The reporting box
   found three bogus stores it never noticed minting (C--Windows-system32 among them); this
   machine's fallback comment names its own ("the empty C--WINDOWS-system32 sky").

2. THE OFFER. list_projects offered every Claude-projects DIR whether or not a store exists,
   plus an unconditional 'default' - an internal fallback nobody means to select. A dropdown
   entry was a loaded gun pointed at mechanism 1.

3. THE CASE TWIN. Keys come from two sources - directory names (W--repos-fyibos) and computed
   git roots (W--Repos-FyiBOS). On NTFS both resolve to ONE file, but they are two STRINGS, so
   the dropdown showed two projects and _conns held two connections to one WAL database.

    python server/test_project_dropdown.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import server  # noqa: E402

PORT = 8997


class DropdownOfferTests(unittest.TestCase):
    """Unit level: list_projects and _use_project against a temp store root."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tmp.name)
        self._orig = (server.DB_PATH, server.DEFAULT_DB, getattr(server, "_conn", None),
                      dict(server._conns), server._default_project,
                      server.CLAUDE_PROJECTS_DIR)
        server.DEFAULT_DB = str(root / "topics.db")
        server.DB_PATH = server.DEFAULT_DB
        server._conns.clear()
        server._default_project = "alpha"
        self.claude_dir = root / "claude-projects"
        self.claude_dir.mkdir()
        server.CLAUDE_PROJECTS_DIR = self.claude_dir
        with server._lock:
            server._use_project("alpha")             # current session store exists

    def tearDown(self):
        for c in server._conns.values():
            try:
                c.close()
            except Exception:
                pass
        server._conns.clear()
        (server.DB_PATH, server.DEFAULT_DB, server._conn, conns,
         server._default_project, server.CLAUDE_PROJECTS_DIR) = self._orig
        server._conns.update(conns)
        self.tmp.cleanup()

    def _keys(self):
        return {p["key"] for p in server.list_projects("alpha")["projects"]}

    def test_a_dir_without_a_store_is_not_offered(self):
        (self.claude_dir / "F--some-repo-nobody-captured-in").mkdir()
        self.assertNotIn("F--some-repo-nobody-captured-in", self._keys(),
                         "a dropdown entry backed by nothing is a constructor, not a choice")

    def test_a_dir_with_a_store_is_offered(self):
        (self.claude_dir / "F--real-project").mkdir()
        with server._lock:
            server._use_project("F--real-project")   # capture created it once upon a time
        self.assertIn("F--real-project", self._keys())

    def test_default_is_not_offered_when_no_legacy_store_exists(self):
        self.assertNotIn("default", self._keys(),
                         "'default' is an internal fallback, not a board anyone means to pick")

    def test_default_is_offered_when_the_legacy_store_really_exists(self):
        with server._lock:
            server._use_project("default")           # a real pre-per-project store
        self.assertIn("default", self._keys())

    def test_the_current_project_is_always_offered_even_storeless(self):
        """A fresh session's project has no store until the first capture - it must still
        appear (and be selected), or the dropdown denies the project you are standing in."""
        for c in server._conns.values():
            c.close()
        server._conns.clear()
        Path(server.project_db_path("alpha")).unlink()
        keys = self._keys()
        self.assertIn("alpha", keys)

    def test_case_twins_collapse_to_one_entry(self):
        """One file on a case-insensitive filesystem must be ONE project, whatever strings
        the two key sources produced. The surviving casing is the store file's own."""
        with server._lock:
            server._use_project("W--Repos-FyiBOS")   # the computed-git-root casing owns the file
        (self.claude_dir / "W--repos-fyibos").mkdir()   # the dir-name casing arrives second
        keys = self._keys()
        self.assertIn("W--Repos-FyiBOS", keys)
        self.assertNotIn("W--repos-fyibos", keys,
                         "two casings of one store showed as two projects")

    def test_use_project_adopts_the_existing_casing(self):
        """The connection cache must converge on one key per file, or two connections open
        against one WAL database and the dropdown twin is born server-side."""
        with server._lock:
            server._use_project("W--Repos-FyiBOS")
            adopted = server._use_project("w--repos-fyibos")
        self.assertEqual(adopted, "W--Repos-FyiBOS")
        self.assertEqual(sum(1 for k in server._conns if k.lower() == "w--repos-fyibos"), 1,
                         "two cache entries for one store file")


class ReadDoesNotMintTests(unittest.TestCase):
    """HTTP level: a READ of a nonexistent project must not create its store."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        cls.db = Path(cls.tmp.name) / "t.db"
        cls.srv = subprocess.Popen(
            [sys.executable, str(HERE / "server.py"),
             "--db", str(cls.db), "--port", str(PORT)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/topics", timeout=1)
                break
            except Exception:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.srv.terminate()
        cls.srv.wait(timeout=5)
        cls.tmp.cleanup()

    def _get(self, path):
        try:
            r = urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=10)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def _post(self, path, body):
        req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}",
                                     data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            r = urllib.request.urlopen(req, timeout=10)
            return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def _store(self, key):
        return Path(self.tmp.name) / "projects" / f"{key}.db"

    def test_board_load_of_a_ghost_project_is_an_honest_empty_not_a_mint(self):
        """The board-load endpoint answers 200 with an explicit store_exists:false (the UI
        renders a message instead of a dark board) - and creates NOTHING on disk."""
        code, body = self._get("/api/topics?project=ghost-project-nobody-made")
        self.assertEqual(code, 200)
        self.assertEqual(body.get("topics"), [])
        self.assertIs(body.get("store_exists"), False)
        self.assertFalse(self._store("ghost-project-nobody-made").exists(),
                         "reading a ghost project minted its store")

    def test_other_reads_of_a_ghost_project_refuse_loudly(self):
        """A groom report about a nonexistent store must ERROR, not report plausible zeros -
        the 0798 lesson: an absent premise fails toward a false PASS."""
        for path in ("/api/topics/groom?project=ghost-2",
                     "/api/topics/search?q=x&project=ghost-2",
                     "/api/topics/duplicates?project=ghost-2"):
            code, body = self._get(path)
            self.assertEqual(code, 404, path)
            self.assertIn("no topic store", body.get("error", ""), path)
        self.assertFalse(self._store("ghost-2").exists())

    def test_a_mutating_post_on_a_ghost_project_refuses_and_does_not_mint(self):
        code, body = self._post("/api/topics/some-slug/state",
                                {"project": "ghost-3", "state": "discussed", "actor": "t"})
        self.assertEqual(code, 404)
        self.assertIn("no topic store", body.get("error", ""))
        self.assertFalse(self._store("ghost-3").exists())

    def test_capture_still_creates_a_new_project_store(self):
        """The one legitimate mint: a CAPTURE into a new project. First capture from a fresh
        repo must keep working, or the plugin cannot onboard a project at all."""
        code, body = self._post("/api/topics?project=brand-new-project",
                                {"actor": "t", "topics": [{"title": "first capture"}]})
        self.assertEqual(code, 200)
        self.assertTrue(body["results"][0].get("slug"))
        self.assertTrue(self._store("brand-new-project").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
