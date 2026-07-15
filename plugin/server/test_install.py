#!/usr/bin/env python3
"""Test for install_service.py: dry-run must not start the service and must
report started=False in the JSON output.

    python server/test_install.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
INSTALLER = HERE / "install_service.py"


class InstallTests(unittest.TestCase):
    def test_dry_run_reports_started_key_and_starts_nothing(self):
        """Dry-run must never launch the service; JSON output must have
        started=False."""
        out = subprocess.run(
            [sys.executable, str(INSTALLER), "--dry-run"],
            capture_output=True, text=True
        )
        # Parse the last line that starts with { as JSON
        # (there are DRY-RUN: prefix lines before it)
        lines = [l for l in out.stdout.splitlines() if l.strip().startswith("{")]
        self.assertTrue(lines, "No JSON output found in installer stdout")
        data = json.loads(lines[-1])
        # The JSON contract now carries the started key
        self.assertIn("started", data)
        # Dry-run must never launch a process
        self.assertFalse(data["started"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
