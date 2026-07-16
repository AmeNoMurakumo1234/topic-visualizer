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


class OurScriptPathsTests(unittest.TestCase):
    """_our_script_paths() must be version-dir-blind: it has to match a server started before a
    plugin upgrade, which carries the OLD version dir on its command line - not just the CURRENT
    code's dir. Drives it against a fake deployed config (CFG patched to a temp file) whose base
    contains two version dirs, each with its own server/server.py."""

    def test_includes_all_version_dirs_plus_pinned_plus_here_deduped(self):
        import install_service
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "cache"
            v1 = base / "0.40.0" / "server"
            v2 = base / "0.41.0" / "server"
            v1.mkdir(parents=True)
            v2.mkdir(parents=True)
            (v1 / "server.py").write_text("# old version", encoding="utf-8")
            (v2 / "server.py").write_text("# new version", encoding="utf-8")
            pinned = Path(td) / "pinned" / "server.py"
            cfg_path = Path(td) / "tv-autostart.json"
            cfg_path.write_text(json.dumps({
                "base": str(base),
                "server_leaf": "server/server.py",
                "embed_leaf": "server/serve_embedder.py",
                "pinned_server": str(pinned),
                "pinned_embedder": None,
            }), encoding="utf-8")
            with patch.object(install_service, "CFG", cfg_path):
                paths = install_service._our_script_paths()
            self.assertIn(str(v1 / "server.py"), paths)
            self.assertIn(str(v2 / "server.py"), paths)
            self.assertIn(str(pinned), paths)
            self.assertIn(str(install_service.HERE / "server.py"), paths)
            self.assertIn(str(install_service.HERE / "serve_embedder.py"), paths)
            # deduped: no path appears twice
            self.assertEqual(len(paths), len(set(paths)))

    def test_missing_or_unreadable_cfg_falls_back_to_here_only(self):
        import install_service
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "does-not-exist.json"
            with patch.object(install_service, "CFG", cfg_path):
                paths = install_service._our_script_paths()
            self.assertEqual(paths, [str(install_service.HERE / "server.py"),
                                     str(install_service.HERE / "serve_embedder.py")])


class ServerAnswersTests(unittest.TestCase):
    """_server_answers() is the truthfulness probe behind a truthful `started`: it must be False
    against a port nothing is listening on (a dead port must never read as a takeover)."""

    def test_dead_port_is_false(self):
        import install_service
        self.assertFalse(install_service._server_answers(59999))


class EmbedderInheritReuseTests(unittest.TestCase):
    """A plain reinstall (no --embedder) must never silently tear down a previously-provisioned
    embedder: install() reuses the deployed config's embed_python when it still exists on disk,
    short-circuiting _provision_embedder entirely (no venv rebuild, no re-download)."""

    def test_reuse_short_circuits_provisioning(self):
        import install_service
        with tempfile.TemporaryDirectory() as td:
            prior_python = Path(td) / "prior_venv_python"
            prior_python.write_text("stub interpreter", encoding="utf-8")
            cfg_path = Path(td) / "tv-autostart.json"
            cfg_path.write_text(json.dumps({"embedder": True, "embed_python": str(prior_python)}),
                                encoding="utf-8")
            with patch.object(install_service, "CFG", cfg_path), \
                 patch.object(install_service, "_provision_embedder") as mock_provision:
                install_service.install(8991, True, 8082, dry=True)
            mock_provision.assert_not_called()

    def test_missing_prior_python_still_provisions(self):
        """A prior embed_python entry that no longer exists on disk (venv deleted) must NOT be
        trusted - provisioning still runs."""
        import install_service
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "tv-autostart.json"
            cfg_path.write_text(json.dumps({
                "embedder": True, "embed_python": str(Path(td) / "gone" / "python"),
            }), encoding="utf-8")
            with patch.object(install_service, "CFG", cfg_path), \
                 patch.object(install_service, "_provision_embedder",
                              return_value="/fake/new/venv/python") as mock_provision:
                install_service.install(8991, True, 8082, dry=True)
            mock_provision.assert_called_once()


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
