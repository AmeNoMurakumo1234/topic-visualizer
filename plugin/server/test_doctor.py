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
        with patch.object(mcp_tools, "_autostart_installed", return_value=True), \
             patch.object(mcp_tools, "_http", side_effect=self._fake_http("autostart")):
            d = mcp_tools.ServerBackend().doctor()
        self.assertEqual(d["persistence"], "ok")
        self.assertFalse(any("session-bound" in msg for msg in d["degraded"]))

    def test_manual_launched_by_is_degraded_session_bound(self):
        with patch.object(mcp_tools, "_autostart_installed", return_value=True), \
             patch.object(mcp_tools, "_http", side_effect=self._fake_http("manual")):
            d = mcp_tools.ServerBackend().doctor()
        self.assertEqual(d["persistence"], "degraded")
        self.assertTrue(any("session-bound" in msg for msg in d["degraded"]), d["degraded"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
