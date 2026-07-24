#!/usr/bin/env python3
"""Doctor distinguishes a detached (autostart) server from a session-bound (manual) one.

Reloads server.py with TOPICS_LAUNCHED_BY set/unset and checks the doctor() dict carries
the stamp through. See docs/2026-07-postmortem (issue 2): persistence == (running AND
autostart_installed) cannot tell a detached login service from an ephemeral session child;
both make those two booleans true. launched_by is the third leg that closes the gap.

    python test_doctor.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import server  # noqa: E402


class DoctorLaunchedByTests(unittest.TestCase):
    def tearDown(self):
        # always leave the module in a clean (env-unset) state for later tests/imports
        os.environ.pop("TOPICS_LAUNCHED_BY", None)
        importlib.reload(server)

    def test_server_doctor_reports_launched_by(self):
        with patch.dict(os.environ, {"TOPICS_LAUNCHED_BY": "autostart"}):
            importlib.reload(server)
            d = server.doctor()
        self.assertEqual(d.get("launched_by"), "autostart")

    def test_server_doctor_launched_by_defaults_none(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TOPICS_LAUNCHED_BY", None)
            importlib.reload(server)
            d = server.doctor()
        self.assertEqual(d.get("launched_by"), "manual")


import mcp_tools  # noqa: E402


class McpPersistenceVerdict(unittest.TestCase):
    """Drives mcp_tools.ServerBackend.doctor()'s three-way persistence verdict with the
    HTTP + autostart layers stubbed - no live server needed. Pins the branch this release
    exists for: persistence == 'ok' ONLY for a running, autostart-installed server whose
    OWN launched_by says 'autostart'; anything else running+autostart is 'degraded' with a
    session-bound message."""

    @staticmethod
    def _fake_http(launched_by):
        def _http(method, url, body=None, headers=None):
            if "/api/doctor" in url:
                return {"launched_by": launched_by, "version": mcp_tools.VERSION}
            # any other probe (e.g. the board /api/whoami routing hint) - no board present
            raise mcp_tools.Unreachable("no board here")
        return _http

    def test_autostart_launched_by_is_ok(self):
        # launched_by="autostart" is ok regardless of whether the deployed launcher is stamp-capable -
        # make this robust to either state of the machine running the suite.
        for stamp_capable in (True, False):
            with self.subTest(stamp_capable=stamp_capable), \
                 patch.object(mcp_tools, "_autostart_installed", return_value=True), \
                 patch.object(mcp_tools, "_launcher_stamps", return_value=stamp_capable), \
                 patch.object(mcp_tools, "_http", side_effect=self._fake_http("autostart")):
                d = mcp_tools.ServerBackend().doctor()
            self.assertEqual(d["persistence"], "ok")
            self.assertFalse(any("session-bound" in msg for msg in d["degraded"]))

    def test_manual_launched_by_is_degraded_session_bound(self):
        # a STAMP-CAPABLE (0.41.0+) launcher with a manual/session-bound server must still degrade -
        # this is the false-GREEN fix; must not be weakened by the frozen-launcher honesty fix.
        with patch.object(mcp_tools, "_autostart_installed", return_value=True), \
             patch.object(mcp_tools, "_launcher_stamps", return_value=True), \
             patch.object(mcp_tools, "_http", side_effect=self._fake_http("manual")):
            d = mcp_tools.ServerBackend().doctor()
        self.assertEqual(d["persistence"], "degraded")
        self.assertTrue(any("session-bound" in msg for msg in d["degraded"]), d["degraded"])

    def test_manual_launched_by_with_incapable_launcher_is_ok_with_note(self):
        # a FROZEN pre-0.41.0 launcher cannot stamp what it starts, so launched_by="manual" here does
        # NOT mean session-bound - it means the old launcher started it (still detached). The doctor
        # must not false-RED this: persistence stays "ok", with an honest note instead of a
        # "session-bound" scare that has no actionable recovery for an old launcher.
        with patch.object(mcp_tools, "_autostart_installed", return_value=True), \
             patch.object(mcp_tools, "_launcher_stamps", return_value=False), \
             patch.object(mcp_tools, "_http", side_effect=self._fake_http("manual")):
            d = mcp_tools.ServerBackend().doctor()
        self.assertEqual(d["persistence"], "ok")
        self.assertIn("persistence_note", d)
        self.assertFalse(any("session-bound" in msg for msg in d["degraded"]), d["degraded"])


class McpStoreMismatchTests(unittest.TestCase):
    """0653: a login-autostarted server inherits the Startup launcher's cwd
    (C:/Windows/System32) and mints a phantom default store (C--WINDOWS-system32.db, 0
    topics) - and the doctor reported project=<session> beside store.project=<phantom>
    with verdict ok, calling the split healthy. The doctor must CLASSIFY the mismatch:
    an EMPTY/absent mismatched default is the phantom signature (degraded, RED); a
    mismatched default with real content is a legitimate other project (note, not RED)."""

    @staticmethod
    def _fake_http(store):
        def fake(method, url, body=None, headers=None):
            if "/api/doctor" in url:
                return {"launched_by": "autostart", "version": mcp_tools.VERSION,
                        "store": store}
            raise mcp_tools.Unreachable("no board here")
        return fake

    def _doctor_with_store(self, store):
        with patch.object(mcp_tools, "_autostart_installed", return_value=True), \
             patch.object(mcp_tools, "_launcher_stamps", return_value=True), \
             patch.object(mcp_tools, "_http", side_effect=self._fake_http(store)):
            return mcp_tools.ServerBackend().doctor()

    def test_phantom_empty_mismatched_default_is_degraded(self):
        with TemporaryDirectory() as td:
            db = Path(td) / "C--WINDOWS-system32.db"
            server.open_db(str(db)).close()                      # a real, EMPTY store
            d = self._doctor_with_store(
                {"project": "C--WINDOWS-system32", "db_path": str(db), "exists": True})
        self.assertEqual(d["verdict"], "degraded")
        self.assertTrue(any("default store" in m.lower() for m in d["degraded"]),
                        d["degraded"])

    def test_mismatched_default_with_content_is_a_note_not_red(self):
        with TemporaryDirectory() as td:
            db = Path(td) / "X--some-other-repo.db"
            c = server.open_db(str(db))
            c.execute("INSERT INTO topic (slug, title, body, state, priority, tags, "
                      "created_by, provenance, role) VALUES "
                      "('t1','a real topic','','open','normal','','x','','topic')")
            c.commit()
            c.close()
            d = self._doctor_with_store(
                {"project": "X--some-other-repo", "db_path": str(db), "exists": True})
        self.assertEqual(d["verdict"], "ok", d.get("degraded"))
        self.assertIn("store_note", d)
        self.assertIn("X--some-other-repo", d["store_note"])

    def test_matching_default_is_silent(self):
        b = mcp_tools.ServerBackend()
        with TemporaryDirectory() as td:
            db = Path(td) / "match.db"
            server.open_db(str(db)).close()
            d = self._doctor_with_store(
                {"project": b.project, "db_path": str(db), "exists": True})
        self.assertEqual(d["verdict"], "ok", d.get("degraded"))
        self.assertNotIn("store_note", d)


class VersionSkewDirectionTests(unittest.TestCase):
    """0.45.x: the skew message names the STALE SIDE instead of assuming the server is it.
    Live repro (2026-07-24): a session whose MCP face was 0.44.3 read a freshly-cycled
    0.45.0 server and told the operator 'restart the server to pick up the update' - a
    wrong bucket carrying a useless remedy (must-know: classify on cause, not state)."""

    @staticmethod
    def _fake_http(server_version):
        def fake(method, url, body=None, headers=None):
            if "/api/doctor" in url:
                return {"launched_by": "autostart", "version": server_version}
            raise mcp_tools.Unreachable("no board here")
        return fake

    def _doctor_against(self, server_version):
        with patch.object(mcp_tools, "_autostart_installed", return_value=True), \
             patch.object(mcp_tools, "_launcher_stamps", return_value=True), \
             patch.object(mcp_tools, "_http", side_effect=self._fake_http(server_version)):
            return mcp_tools.ServerBackend().doctor()

    def test_newer_server_blames_the_session_not_the_server(self):
        d = self._doctor_against("999.0.0")
        msgs = [m for m in d["degraded"] if "999.0.0" in m]
        self.assertTrue(msgs, d["degraded"])
        self.assertIn("SESSION is the stale side", msgs[0])
        self.assertNotIn("Restart the topics server", msgs[0],
                         "a newest server must never be told to restart")

    def test_older_server_still_says_restart_the_server(self):
        d = self._doctor_against("0.0.1")
        msgs = [m for m in d["degraded"] if "0.0.1" in m]
        self.assertTrue(msgs, d["degraded"])
        self.assertIn("Restart the topics server", msgs[0])

    def test_matching_versions_raise_no_skew_message(self):
        d = self._doctor_against(mcp_tools.VERSION)
        self.assertFalse(any("upgrade clock" in m or "stale side" in m
                             for m in d["degraded"]), d["degraded"])


class LauncherStampsTests(unittest.TestCase):
    """_launcher_stamps() reads the DEPLOYED login launcher (~/.topic-visualizer/tv-autostart.py) and
    reports whether ITS source is new enough to carry the TOPICS_LAUNCHED_BY stamp - the doctor uses
    this to know whether a missing stamp means "frozen old launcher" (honest ok) vs "hand-started"
    (real degradation)."""

    def test_true_when_deployed_launcher_contains_stamp_marker(self):
        with TemporaryDirectory() as td:
            home = Path(td)
            tvdir = home / ".topic-visualizer"
            tvdir.mkdir(parents=True, exist_ok=True)
            (tvdir / "tv-autostart.py").write_text(
                "TOPICS_LAUNCHED_BY = 'autostart'\n", encoding="utf-8")
            with patch("mcp_tools.Path.home", return_value=home):
                self.assertTrue(mcp_tools._launcher_stamps())

    def test_false_when_deployed_launcher_lacks_stamp_marker(self):
        with TemporaryDirectory() as td:
            home = Path(td)
            tvdir = home / ".topic-visualizer"
            tvdir.mkdir(parents=True, exist_ok=True)
            (tvdir / "tv-autostart.py").write_text(
                "# an old pre-0.41.0 launcher with no stamp concept\n", encoding="utf-8")
            with patch("mcp_tools.Path.home", return_value=home):
                self.assertFalse(mcp_tools._launcher_stamps())

    def test_false_when_deployed_launcher_missing(self):
        with TemporaryDirectory() as td:
            home = Path(td)     # no ~/.topic-visualizer/tv-autostart.py at all
            with patch("mcp_tools.Path.home", return_value=home):
                self.assertFalse(mcp_tools._launcher_stamps())


class LauncherPortTests(unittest.TestCase):
    """_launcher_port() reads the port the DEPLOYED login launcher will start the server on
    (its own config's server_port) - so open_visualizer() can tell whether routing through the
    launcher would actually serve the port this session is polling."""

    def test_returns_configured_server_port(self):
        with TemporaryDirectory() as td:
            home = Path(td)
            tvdir = home / ".topic-visualizer"
            tvdir.mkdir(parents=True, exist_ok=True)
            (tvdir / "tv-autostart.json").write_text(
                '{"server_port": 9123}', encoding="utf-8")
            with patch("mcp_tools.Path.home", return_value=home):
                self.assertEqual(mcp_tools._launcher_port(), 9123)

    def test_defaults_to_8991_when_config_missing_or_unreadable(self):
        with TemporaryDirectory() as td:
            home = Path(td)     # no ~/.topic-visualizer/tv-autostart.json at all
            with patch("mcp_tools.Path.home", return_value=home):
                self.assertEqual(mcp_tools._launcher_port(), 8991)
            tvdir = home / ".topic-visualizer"
            tvdir.mkdir(parents=True, exist_ok=True)
            (tvdir / "tv-autostart.json").write_text("not json", encoding="utf-8")
            with patch("mcp_tools.Path.home", return_value=home):
                self.assertEqual(mcp_tools._launcher_port(), 8991)


class AutostartInstalledPosixTests(unittest.TestCase):
    """_autostart_installed()'s empty-artifacts fallback is only valid on Windows (install always
    records the Startup VBS artifact there). On posix, install only PRINTS a launchd/systemd unit
    and records artifacts:[] - the old 'launcher file exists' fallback then manufactured a false
    'persistence ok'. On posix, trust persistence only if a real unit file exists."""

    def test_false_when_artifacts_empty_and_no_unit_installed(self):
        with TemporaryDirectory() as td:
            home = Path(td)
            tvdir = home / ".topic-visualizer"
            tvdir.mkdir(parents=True, exist_ok=True)
            (tvdir / "tv-autostart.json").write_text(
                json.dumps({"artifacts": []}), encoding="utf-8")
            (tvdir / "tv-autostart.py").write_text("# launcher present", encoding="utf-8")
            with patch("mcp_tools.Path.home", return_value=home), \
                 patch.object(mcp_tools.os, "name", "posix"):
                self.assertFalse(mcp_tools._autostart_installed())

    def test_true_when_systemd_unit_installed(self):
        with TemporaryDirectory() as td:
            home = Path(td)
            tvdir = home / ".topic-visualizer"
            tvdir.mkdir(parents=True, exist_ok=True)
            (tvdir / "tv-autostart.json").write_text(
                json.dumps({"artifacts": []}), encoding="utf-8")
            unit_dir = home / ".config" / "systemd" / "user"
            unit_dir.mkdir(parents=True, exist_ok=True)
            (unit_dir / "topic-visualizer.service").write_text("[Unit]\n", encoding="utf-8")
            with patch("mcp_tools.Path.home", return_value=home), \
                 patch.object(mcp_tools.os, "name", "posix"):
                self.assertTrue(mcp_tools._autostart_installed())

    def test_true_when_launchd_plist_installed(self):
        with TemporaryDirectory() as td:
            home = Path(td)
            tvdir = home / ".topic-visualizer"
            tvdir.mkdir(parents=True, exist_ok=True)
            (tvdir / "tv-autostart.json").write_text(
                json.dumps({"artifacts": []}), encoding="utf-8")
            agents_dir = home / "Library" / "LaunchAgents"
            agents_dir.mkdir(parents=True, exist_ok=True)
            (agents_dir / "com.topicvisualizer.plist").write_text("<plist/>", encoding="utf-8")
            with patch("mcp_tools.Path.home", return_value=home), \
                 patch.object(mcp_tools.os, "name", "posix"):
                self.assertTrue(mcp_tools._autostart_installed())

    def test_windows_fallback_still_uses_launcher_file(self):
        """Windows legacy behavior must be unchanged: empty artifacts + launcher file present -> ok."""
        with TemporaryDirectory() as td:
            home = Path(td)
            tvdir = home / ".topic-visualizer"
            tvdir.mkdir(parents=True, exist_ok=True)
            (tvdir / "tv-autostart.json").write_text(
                json.dumps({"artifacts": []}), encoding="utf-8")
            (tvdir / "tv-autostart.py").write_text("# launcher present", encoding="utf-8")
            with patch("mcp_tools.Path.home", return_value=home), \
                 patch.object(mcp_tools.os, "name", "nt"):
                self.assertTrue(mcp_tools._autostart_installed())


if __name__ == "__main__":
    unittest.main(verbosity=2)
