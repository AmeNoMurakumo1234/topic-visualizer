#!/usr/bin/env python3
"""Test for install_service.py: dry-run must not start the service and must
report started=False in the JSON output.

    python server/test_install.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
INSTALLER = HERE / "install_service.py"

sys.path.insert(0, str(HERE))


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


class ConfigEmbedPythonTests(unittest.TestCase):
    """Task 8: _config() must carry an embed_python entry so the launcher can find the
    dedicated embedder venv interpreter."""

    def test_config_carries_embed_python_when_embedder(self):
        import install_service
        cfg = install_service._config(8991, embedder=True, embed_port=8082, artifacts=[],
                                       embed_python="/fake/venv/python")
        self.assertEqual(cfg["embed_python"], "/fake/venv/python")


class VenvPythonPathTests(unittest.TestCase):
    """_venv_python() must resolve the platform-correct interpreter path under the
    dedicated ~/.topic-visualizer/venv directory."""

    def test_venv_python_platform_path(self):
        import install_service
        p = install_service._venv_python()
        parts = p.parts[-2:]
        if os.name == "nt":
            self.assertEqual(parts, ("Scripts", "python.exe"))
        else:
            self.assertEqual(parts, ("bin", "python"))
        self.assertEqual(p.parent.parent.name, "venv")


class ProvisionEmbedderDryRunTests(unittest.TestCase):
    """_provision_embedder(dry=True) must report the prospective venv python path and
    create NOTHING on disk. HOME/VENV are patched to a temp dir so the real home is
    never touched."""

    def test_dry_run_creates_nothing(self):
        import install_service
        with tempfile.TemporaryDirectory() as td:
            tmp_home = Path(td) / ".topic-visualizer"
            tmp_venv = tmp_home / "venv"
            with patch.object(install_service, "HOME", tmp_home), \
                 patch.object(install_service, "VENV", tmp_venv):
                result = install_service._provision_embedder(dry=True)
                expected = str(install_service._venv_python())
            self.assertEqual(result, expected)
            self.assertFalse(tmp_venv.exists())
            self.assertFalse(tmp_home.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
