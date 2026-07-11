#!/usr/bin/env python3
"""End-to-end tests for the MCP face (mcp_tools.py) - real JSON-RPC over stdio.

Covers the three deployment shapes:
  1. server backend, HTTP path      (plugin server running)
  2. server backend, DIRECT path    (no server running -> in-process sqlite fallback)
  3. board backend                  (OPTIONAL: only when a live message board is up;
                                     uses a sandbox project so no real project is touched)

Run:  python test_mcp.py            (board leg auto-skips when the board is down)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORT = 8994
BOARD = os.environ.get("TOPICS_BOARD_URL", "http://127.0.0.1:9772")


class MCP:
    """Minimal stdio MCP client: newline-delimited JSON-RPC 2.0."""

    def __init__(self, env: dict):
        e = os.environ.copy()
        e.update(env)
        self.p = subprocess.Popen(
            [sys.executable, str(HERE / "mcp_tools.py")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=e)
        self._id = 0

    def rpc(self, method: str, params: dict | None = None):
        self._id += 1
        msg = {"jsonrpc": "2.0", "id": self._id, "method": method,
               "params": params or {}}
        self.p.stdin.write((json.dumps(msg) + "\n").encode())
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        return json.loads(line)["result"]

    def tool(self, name: str, args: dict):
        r = self.rpc("tools/call", {"name": name, "arguments": args})
        return json.loads(r["content"][0]["text"]), r.get("isError")

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)


def _board_up() -> bool:
    try:
        urllib.request.urlopen(BOARD + "/api/posts?project=topics-mcp-sandbox", timeout=3)
        return True
    except Exception:
        return False


class TestMCPServerBackendHTTP(unittest.TestCase):
    """Shape 1: MCP -> HTTP -> plugin server."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.srv = subprocess.Popen(
            [sys.executable, str(HERE / "server.py"),
             "--db", str(Path(cls.tmp.name) / "t.db"), "--port", str(PORT)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/topics", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        cls.mcp = MCP({"TOPICS_BACKEND": "server",
                       "TOPICS_SERVER_URL": f"http://127.0.0.1:{PORT}"})

    @classmethod
    def tearDownClass(cls):
        cls.mcp.close()
        cls.srv.terminate()
        cls.srv.wait(timeout=5)
        cls.tmp.cleanup()

    def test_01_handshake_and_list(self):
        init = self.mcp.rpc("initialize", {"protocolVersion": "2024-11-05"})
        self.assertEqual(init["serverInfo"]["name"], "topic-visualizer")
        tools = self.mcp.rpc("tools/list")["tools"]
        self.assertEqual({t["name"] for t in tools},
                         {"topic_add", "topic_serve", "topic_search", "topic_state",
                          "topic_convert", "topic_groom_report"})

    def test_02_lifecycle(self):
        out, err = self.mcp.tool("topic_add", {"items": [
            {"title": "MCP seam test topic", "body": "planted over stdio",
             "priority": "critical"},
            {"title": "MCP seedling", "state": "seedling"}]})
        self.assertFalse(err)
        slugs = [r["slug"] for r in out["results"]]
        self.assertEqual(len(slugs), 2)

        card, _ = self.mcp.tool("topic_serve", {"context": "testing the stdio seam"})
        self.assertEqual(card["card"]["slug"], slugs[0])   # beacon wins

        res, _ = self.mcp.tool("topic_search", {"query": "stdio seam"})
        self.assertTrue(any(r["slug"] == slugs[0] for r in res["results"]))

        st, _ = self.mcp.tool("topic_state",
                              {"slug": slugs[1], "state": "discussed", "note": "done"})
        self.assertTrue(st.get("ok"))

        cv, _ = self.mcp.tool("topic_convert",
                              {"slug": slugs[0], "kind": "decision",
                               "ref": "canon.db:test", "note": "ratified"})
        self.assertTrue(cv.get("ok"))

        g, _ = self.mcp.tool("topic_groom_report", {})
        self.assertIn("health", g)                  # plugin-server groom shape
        self.assertIn("capture_calibration", g)


class TestMCPServerBackendDirect(unittest.TestCase):
    """Shape 2: no HTTP server -> the in-process sqlite fallback must carry it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.mcp = MCP({"TOPICS_BACKEND": "server",
                       "TOPICS_SERVER_URL": "http://127.0.0.1:1",   # nothing there
                       "TOPICS_DB": str(Path(cls.tmp.name) / "direct.db")})

    @classmethod
    def tearDownClass(cls):
        cls.mcp.close()
        cls.tmp.cleanup()

    def test_01_zero_setup_capture(self):
        out, err = self.mcp.tool("topic_add", {"items": [
            {"title": "captured with no server running"}]})
        self.assertFalse(err)
        slug = out["results"][0]["slug"]
        res, _ = self.mcp.tool("topic_search", {"query": "captured no server"})
        self.assertTrue(any(r["slug"] == slug for r in res["results"]))
        card, _ = self.mcp.tool("topic_serve", {"context": ""})
        self.assertEqual(card["card"]["slug"], slug)


@unittest.skipUnless(_board_up(), "message board not running - board leg skipped")
class TestMCPBoardBackend(unittest.TestCase):
    """Shape 3: topics as OPEN THREAD board posts, sandbox project. Exercises the
    full lifecycle including topic_convert minting a REAL board issue."""

    @classmethod
    def setUpClass(cls):
        cls.mcp = MCP({"TOPICS_BACKEND": "board",
                       "TOPICS_BOARD_URL": BOARD,
                       "TOPICS_BOARD_PROJECT": "topics-mcp-sandbox",
                       "TOPICS_BOARD_AUTHOR": "Joule"})

    @classmethod
    def tearDownClass(cls):
        cls.mcp.close()

    def test_01_board_lifecycle(self):
        out, err = self.mcp.tool("topic_add", {"items": [
            {"title": "sandbox seam topic", "body": "mcp e2e - safe to ignore",
             "state": "seedling"}]})
        self.assertFalse(err, out)
        slug = out["results"][0]["slug"]
        self.assertTrue(slug)

        res, _ = self.mcp.tool("topic_search", {"query": "sandbox seam"})
        self.assertTrue(any(r["slug"] == slug for r in res["results"]))

        cv, _ = self.mcp.tool("topic_convert",
                              {"slug": slug, "kind": "work_item",
                               "note": "mcp e2e conversion"})
        self.assertTrue(cv.get("ok"), cv)
        self.assertTrue(cv.get("ref"), cv)          # a real issue slug came back

        # tidy: discard the sandbox thread's remains is not needed (converted =
        # resolved); prune a second throwaway to cover the discard path
        out2, _ = self.mcp.tool("topic_add", {"items": [{"title": "sandbox prune me"}]})
        slug2 = out2["results"][0]["slug"]
        pr, _ = self.mcp.tool("topic_state", {"slug": slug2, "state": "pruned",
                                              "note": "e2e cleanup"})
        self.assertFalse(pr.get("error"), pr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
