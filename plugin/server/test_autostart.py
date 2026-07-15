#!/usr/bin/env python3
"""Tests for autostart process logging (tv_autostart.py) and the doctor log-tail
(mcp_tools.py). Task 3 (postmortem issues 3-secondary, 4): detached processes sent
stdout/stderr to DEVNULL, so a login-time crash (missing package, port conflict, model
download failure) was invisible and the doctor could only say "not reachable", never why.

    python test_autostart.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import tv_autostart  # noqa: E402


class LogfileHelperTests(unittest.TestCase):
    def test_logfile_helper_returns_paths(self):
        p = tv_autostart._logfile("server")
        self.assertEqual(p.name, "server.log")
        self.assertEqual(p.parent.name, "logs")


class DetachedLogRedirectTests(unittest.TestCase):
    """_detached(logname=...) must open a truncate-on-start log file, preserve the Task-2
    TOPICS_LAUNCHED_BY env stamp, and keep the platform split (Windows creationflags vs
    unix start_new_session) - all requirements this task must not regress."""

    def test_detached_without_logname_uses_devnull(self):
        kw = tv_autostart._detached()
        self.assertIs(kw["stdout"], subprocess.DEVNULL)
        self.assertIs(kw["stderr"], subprocess.DEVNULL)

    def test_detached_opens_and_truncates_log(self):
        with TemporaryDirectory() as td:
            logdir = Path(td) / "logs"
            logdir.mkdir(parents=True, exist_ok=True)
            logpath = logdir / "server.log"
            logpath.write_text("stale previous run\n", encoding="utf-8")
            with patch.object(tv_autostart, "LOGDIR", logdir):
                kw = tv_autostart._detached("server")
            fh = kw["stdout"]
            try:
                self.assertIs(kw["stderr"], fh)   # both streams share one handle
                fh.write("fresh output\n")
                fh.flush()
            finally:
                fh.close()
            self.assertEqual(logpath.read_text(encoding="utf-8"), "fresh output\n")

    def test_detached_creates_missing_logdir(self):
        with TemporaryDirectory() as td:
            logdir = Path(td) / "not-yet-created" / "logs"
            with patch.object(tv_autostart, "LOGDIR", logdir):
                kw = tv_autostart._detached("embedder")
            fh = kw["stdout"]
            try:
                self.assertTrue(logdir.is_dir())
                self.assertTrue((logdir / "embedder.log").exists())
            finally:
                fh.close()

    def test_detached_falls_back_to_devnull_on_open_failure(self):
        with TemporaryDirectory() as td:
            logdir = Path(td) / "logs"
            with patch.object(tv_autostart, "LOGDIR", logdir), \
                 patch("builtins.open", side_effect=OSError("boom, unwritable")):
                kw = tv_autostart._detached("server")
        self.assertIs(kw["stdout"], subprocess.DEVNULL)
        self.assertIs(kw["stderr"], subprocess.DEVNULL)

    def test_detached_preserves_task2_env_and_platform_split(self):
        with TemporaryDirectory() as td:
            logdir = Path(td) / "logs"
            with patch.object(tv_autostart, "LOGDIR", logdir):
                kw = tv_autostart._detached("server")
            fh = kw["stdout"]
            try:
                self.assertEqual(kw["env"].get("TOPICS_LAUNCHED_BY"), "autostart")
                if os.name == "nt":
                    self.assertEqual(kw.get("creationflags"), 0x00000008 | 0x00000200)
                    self.assertNotIn("start_new_session", kw)
                else:
                    self.assertTrue(kw.get("start_new_session"))
                    self.assertNotIn("creationflags", kw)
            finally:
                if hasattr(fh, "close"):
                    fh.close()


import mcp_tools  # noqa: E402


class DoctorLogTailTests(unittest.TestCase):
    """doctor() tails the last lines of server.log / embedder.log when that component is
    down, so a login-time crash reads as WHY, not just 'not reachable'."""

    def test_doctor_attaches_server_log_tail_when_not_running(self):
        with TemporaryDirectory() as td:
            logdir = Path(td) / "logs"
            logdir.mkdir(parents=True, exist_ok=True)
            lines = [f"line {i}" for i in range(1, 12)]
            (logdir / "server.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

            def _fake_http(method, url, body=None, headers=None):
                raise mcp_tools.Unreachable("connection refused")

            # server unreachable -> ServerBackend.doctor() falls back to the direct-sqlite
            # probe; stub it out so this test never touches a real db.
            with patch.object(mcp_tools, "LOGDIR", logdir), \
                 patch.object(mcp_tools, "_http", side_effect=_fake_http), \
                 patch.object(mcp_tools, "_autostart_installed", return_value=False), \
                 patch.object(mcp_tools.ServerBackend, "_fallback",
                               side_effect=Exception("no direct fallback in this test")):
                out = mcp_tools.ServerBackend().doctor()

        self.assertFalse(out["server"]["running"])
        self.assertIn("logs", out)
        self.assertEqual(out["logs"]["server"], lines[-8:])   # last 8 non-empty lines
        self.assertNotIn("embedder", out["logs"])

    def test_doctor_attaches_embedder_log_tail_when_semantic_off(self):
        with TemporaryDirectory() as td:
            logdir = Path(td) / "logs"
            logdir.mkdir(parents=True, exist_ok=True)
            (logdir / "embedder.log").write_text(
                "Traceback (most recent call last):\nModuleNotFoundError: no numpy\n",
                encoding="utf-8")

            def _fake_http(method, url, body=None, headers=None):
                if "/api/doctor" in url:
                    return {"launched_by": "autostart", "version": mcp_tools.VERSION,
                             "degraded": ["Semantic ranking is OFF - keyword mode only."]}
                raise mcp_tools.Unreachable("no board here")

            with patch.object(mcp_tools, "LOGDIR", logdir), \
                 patch.object(mcp_tools, "_http", side_effect=_fake_http), \
                 patch.object(mcp_tools, "_autostart_installed", return_value=True):
                out = mcp_tools.ServerBackend().doctor()

        self.assertTrue(out["server"]["running"])
        self.assertIn("logs", out)
        self.assertEqual(out["logs"]["embedder"],
                         ["Traceback (most recent call last):", "ModuleNotFoundError: no numpy"])
        self.assertNotIn("server", out["logs"])

    def test_doctor_omits_logs_key_when_nothing_to_show(self):
        with TemporaryDirectory() as td:
            logdir = Path(td) / "logs"   # never created -> no log files exist

            def _fake_http(method, url, body=None, headers=None):
                if "/api/doctor" in url:
                    return {"launched_by": "autostart", "version": mcp_tools.VERSION}
                raise mcp_tools.Unreachable("no board here")

            with patch.object(mcp_tools, "LOGDIR", logdir), \
                 patch.object(mcp_tools, "_http", side_effect=_fake_http), \
                 patch.object(mcp_tools, "_autostart_installed", return_value=True):
                out = mcp_tools.ServerBackend().doctor()

        self.assertTrue(out["server"]["running"])
        self.assertNotIn("logs", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
