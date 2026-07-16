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


if __name__ == "__main__":
    unittest.main(verbosity=2)
