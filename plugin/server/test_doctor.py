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
        self.assertIn(d.get("launched_by"), (None, "manual"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
