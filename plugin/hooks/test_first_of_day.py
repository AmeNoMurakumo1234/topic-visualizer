#!/usr/bin/env python3
"""Tests for the SessionStart first-of-day hook (plugin/hooks/first_of_day.py), including the
installed-but-not-set-up nudge (postmortem issue 6).

Run directly: python test_first_of_day.py
NO pytest - stdlib unittest only, per project convention. The nudge-gating tests drive the
hook as a subprocess (exactly as Claude Code invokes a SessionStart hook) with HOME/USERPROFILE
pointed at an isolated temp dir and TOPICS_DB/TOPICS_SERVER_URL pinned, so runs never touch the
real ~/.topic-visualizer store or a real running server on this machine.
"""
import http.server
import importlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
HOOK = HERE / "first_of_day.py"
SERVER_DIR = HERE.parent / "server"

sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SERVER_DIR))


def run_hook(env):
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input="",
        capture_output=True,
        text=True,
        env=env,
    )


def isolated_env(home, extra=None):
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    # never let a test hit a real locally-running topic-visualizer server
    env.setdefault("TOPICS_SERVER_URL", "http://127.0.0.1:1")
    if extra:
        env.update(extra)
    return env


def make_empty_store(db_path):
    """A real, valid, empty topic store (schema applied, zero topics) - store exists, but
    serve_card() will have nothing to rank, so no card is served from it."""
    import server as srv
    conn = srv.open_db(str(db_path))
    conn.close()


class AutostartInstalledTests(unittest.TestCase):
    """Directly exercises _autostart_installed() in-process (per the task brief's snippet,
    translated to unittest). Reloading the module re-runs its top-level SessionStart body,
    but with HOME pointed at an empty temp dir and no reachable server, that body is a no-op
    (no store -> no card -> no nudge), so the reload has no side effects worth guarding."""

    def test_false_when_no_config(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(os.environ, {"HOME": td, "USERPROFILE": td,
                                          "TOPICS_SERVER_URL": "http://127.0.0.1:1"}):
                import first_of_day
                importlib.reload(first_of_day)
                self.assertFalse(first_of_day._autostart_installed())

    def test_true_when_artifact_exists(self):
        with tempfile.TemporaryDirectory() as td:
            tv_dir = Path(td) / ".topic-visualizer"
            tv_dir.mkdir(parents=True)
            artifact = tv_dir / "Startup.vbs"
            artifact.write_text("' stub artifact", encoding="utf-8")
            (tv_dir / "tv-autostart.json").write_text(
                json.dumps({"artifacts": [str(artifact)]}), encoding="utf-8")
            with patch.dict(os.environ, {"HOME": td, "USERPROFILE": td,
                                          "TOPICS_SERVER_URL": "http://127.0.0.1:1"}):
                import first_of_day
                importlib.reload(first_of_day)
                self.assertTrue(first_of_day._autostart_installed())

    def test_false_when_config_present_but_artifact_missing(self):
        with tempfile.TemporaryDirectory() as td:
            tv_dir = Path(td) / ".topic-visualizer"
            tv_dir.mkdir(parents=True)
            (tv_dir / "tv-autostart.json").write_text(
                json.dumps({"artifacts": [str(tv_dir / "gone.vbs")]}), encoding="utf-8")
            with patch.dict(os.environ, {"HOME": td, "USERPROFILE": td,
                                          "TOPICS_SERVER_URL": "http://127.0.0.1:1"}):
                import first_of_day
                importlib.reload(first_of_day)
                self.assertFalse(first_of_day._autostart_installed())


class NudgeSubprocessTests(unittest.TestCase):
    """Drives the real hook end-to-end as a subprocess. Each test gets its own temp HOME so
    the daily stamp files (STAMP / NUDGE_STAMP) and the fake store never leak across tests."""

    def test_nudges_when_store_exists_and_autostart_missing(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            db = home / "topics.db"
            make_empty_store(db)
            env = isolated_env(home, {"TOPICS_DB": str(db)})
            r = run_hook(env)
            self.assertEqual(r.returncode, 0)
            self.assertIn("/topics-setup", r.stdout)
            out = json.loads(r.stdout)
            self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
            self.assertTrue((home / ".topic-visualizer-last-nudged").exists())

    def test_no_nudge_second_run_same_day(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            db = home / "topics.db"
            make_empty_store(db)
            env = isolated_env(home, {"TOPICS_DB": str(db)})
            first = run_hook(env)
            self.assertIn("/topics-setup", first.stdout)
            second = run_hook(env)
            self.assertEqual(second.stdout.strip(), "")
            self.assertEqual(second.returncode, 0)

    def test_no_nudge_when_autostart_installed(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            db = home / "topics.db"
            make_empty_store(db)
            tv_dir = home / ".topic-visualizer"
            tv_dir.mkdir(parents=True)
            artifact = tv_dir / "Startup.vbs"
            artifact.write_text("' stub", encoding="utf-8")
            (tv_dir / "tv-autostart.json").write_text(
                json.dumps({"artifacts": [str(artifact)]}), encoding="utf-8")
            env = isolated_env(home, {"TOPICS_DB": str(db)})
            r = run_hook(env)
            self.assertEqual(r.stdout.strip(), "")
            self.assertEqual(r.returncode, 0)
            self.assertFalse((home / ".topic-visualizer-last-nudged").exists())

    def test_no_nudge_when_no_store(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            # no TOPICS_DB, no store file anywhere under home -> _store_exists() False
            env = isolated_env(home)
            r = run_hook(env)
            self.assertEqual(r.stdout.strip(), "")
            self.assertEqual(r.returncode, 0)
            self.assertFalse((home / ".topic-visualizer-last-nudged").exists())

    def test_card_takes_priority_over_nudge(self):
        """When a card IS served this run, the nudge must not double up - even though the
        store 'exists' (the fake HTTP server stands in for it) and autostart is missing."""
        card = {"title": "A captured topic", "body": "worth revisiting"}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"card": card}).encode())

            def log_message(self, *a):
                pass

        httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        port = httpd.server_port
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                home = Path(td)
                env = isolated_env(home, {"TOPICS_SERVER_URL": f"http://127.0.0.1:{port}"})
                r = run_hook(env)
                self.assertEqual(r.returncode, 0)
                self.assertIn("FIRST-OF-DAY TOPIC CARD", r.stdout)
                self.assertNotIn("/topics-setup", r.stdout)
                # exactly one JSON object was printed (the card, not also the nudge)
                self.assertEqual(len(r.stdout.strip().splitlines()), 1)
                self.assertFalse((home / ".topic-visualizer-last-nudged").exists())
        finally:
            httpd.shutdown()
            t.join(timeout=2)
            httpd.server_close()

    def test_nudge_opt_out_via_env(self):
        """TOPICS_NUDGE=off must fully silence the setup nudge even when otherwise eligible
        (store exists, autostart missing) - the CARD path is untouched by this opt-out."""
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            db = home / "topics.db"
            make_empty_store(db)
            env = isolated_env(home, {"TOPICS_DB": str(db), "TOPICS_NUDGE": "off"})
            r = run_hook(env)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stdout.strip(), "")
            self.assertFalse((home / ".topic-visualizer-last-nudged").exists())

    def test_hook_fails_silent_and_exits_zero_with_no_input(self):
        with tempfile.TemporaryDirectory() as td:
            env = isolated_env(Path(td))
            r = run_hook(env)
            self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
