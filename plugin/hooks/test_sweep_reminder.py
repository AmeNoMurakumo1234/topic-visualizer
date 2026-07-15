#!/usr/bin/env python3
"""Tests for the session-end sweep Stop hook (plugin/hooks/sweep_reminder.py).

Run directly: python test_sweep_reminder.py
NO pytest - stdlib unittest only, per project convention. Drives the hook as a
subprocess feeding JSON on stdin, exactly as Claude Code invokes a Stop hook.
"""
import json
import os
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "sweep_reminder.py"


def unique_session_id(label):
    # uuid suffix so re-running this test file never collides with a stamp file
    # left behind (in the OS temp dir) by a previous run.
    return f"s-{label}-{uuid.uuid4().hex[:8]}"


def run_hook(payload, env=None):
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )


class TestSweepReminderOptOut(unittest.TestCase):
    def test_opt_out_is_silent(self):
        env = {**os.environ, "TOPICS_SWEEP_HOOK": "off"}
        r = run_hook({"session_id": unique_session_id("optout")}, env=env)
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(r.returncode, 0)

    def test_opt_out_accepts_0(self):
        env = {**os.environ, "TOPICS_SWEEP_HOOK": "0"}
        r = run_hook({"session_id": unique_session_id("optout")}, env=env)
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(r.returncode, 0)

    def test_opt_out_accepts_false(self):
        env = {**os.environ, "TOPICS_SWEEP_HOOK": "false"}
        r = run_hook({"session_id": unique_session_id("optout")}, env=env)
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(r.returncode, 0)


class TestSweepReminderGuards(unittest.TestCase):
    def test_already_stamped_is_silent(self):
        # second call with the same session id must stay silent (one sweep per session)
        env = dict(os.environ)
        env.pop("TOPICS_SWEEP_HOOK", None)
        sid = unique_session_id("dup")
        first = run_hook({"session_id": sid}, env=env)
        self.assertIn('"decision": "block"', first.stdout)
        second = run_hook({"session_id": sid}, env=env)
        self.assertEqual(second.stdout.strip(), "")
        self.assertEqual(second.returncode, 0)

    def test_stop_hook_active_guard_is_silent(self):
        env = dict(os.environ)
        env.pop("TOPICS_SWEEP_HOOK", None)
        r = run_hook({"session_id": unique_session_id("active"), "stop_hook_active": True}, env=env)
        self.assertEqual(r.stdout.strip(), "")
        self.assertEqual(r.returncode, 0)

    def test_fresh_session_blocks_with_checkpoint_reason(self):
        env = dict(os.environ)
        env.pop("TOPICS_SWEEP_HOOK", None)
        r = run_hook({"session_id": unique_session_id("fresh")}, env=env)
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(out["decision"], "block")
        self.assertIn("nothing to plant", out["reason"])
        self.assertIn("not an error", out["reason"].lower())
        self.assertIn("checkpoint", out["reason"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
