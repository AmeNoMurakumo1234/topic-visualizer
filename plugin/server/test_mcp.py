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
        urllib.request.urlopen(BOARD + "/api/posts?project=topics-test", timeout=3)
        return True
    except Exception:
        return False


# The board leg is an INTEGRATION test against a real message board whose author must be a
# registered agent - both are site-specific, so it runs ONLY when explicitly configured
# (a board reachable at TOPICS_BOARD_URL + a valid TOPICS_TEST_AUTHOR). Nothing about any
# particular board, project, or agent is baked in; a downloaded copy just skips it.
_BOARD_CONFIGURED = _board_up() and bool(os.environ.get("TOPICS_TEST_AUTHOR"))


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

    def test_00_hostile_lines_do_not_kill_the_process(self):
        # audit HIGH-2: a valid-JSON non-object line (e.g. a JSON-RPC batch array)
        # used to AttributeError out of main() and kill the server for the session
        self.mcp.p.stdin.write(b'[{"jsonrpc":"2.0","id":99,"method":"ping"}]\n')
        self.mcp.p.stdin.write(b'"just a string"\n')
        self.mcp.p.stdin.flush()
        r = self.mcp.rpc("ping")          # still alive and answering
        self.assertEqual(r, {})

    def test_01_handshake_and_list(self):
        init = self.mcp.rpc("initialize", {"protocolVersion": "2024-11-05"})
        self.assertEqual(init["serverInfo"]["name"], "topic-visualizer")
        tools = self.mcp.rpc("tools/list")["tools"]
        # assert against the LIVE tool registry (not a hardcoded set) so this can't rot as tools are
        # added - the stdio server must expose exactly what mcp_tools.TOOLS declares
        import mcp_tools
        self.assertEqual({t["name"] for t in tools},
                         {t["name"] for t in mcp_tools.TOOLS})

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

    def test_03_attach_multi_parent(self):
        out, _ = self.mcp.tool("topic_add", {"items": [
            {"title": "avenue A"}, {"title": "avenue B"},
            {"title": "the shared child", "parent_slug": None}]})
        a, bslug, child = [r["slug"] for r in out["results"]]
        # child's primary parent = A; then B discovers the same topic
        ed, _ = self.mcp.tool("topic_state", {"slug": child, "state": "open"})
        at, err = self.mcp.tool("topic_attach",
                                {"slug": child, "parent_slug": bslug,
                                 "note": "reached again while exploring B"})
        self.assertTrue(at.get("ok"), at)
        # duplicate attach is IDEMPOTENT (ok+already), not an error (0.6.0); self-cycle rejected
        dup, _ = self.mcp.tool("topic_attach", {"slug": child, "parent_slug": bslug})
        self.assertTrue(dup.get("ok") and dup.get("already"), dup)
        cyc, _ = self.mcp.tool("topic_attach", {"slug": bslug, "parent_slug": bslug})
        self.assertIn("error", cyc)

    def test_04_get_list_priority(self):
        out, _ = self.mcp.tool("topic_add", {"actor": "stable-actor-x", "items": [
            {"title": "0.6.0 groomer read the body before deciding (~1 hour)",
             "body": "THE QUESTION: can a groomer read what they did not author?"}]})
        slug = out["results"][0]["slug"]
        # topic_get: full body (search never returned it)
        g, _ = self.mcp.tool("topic_get", {"slug": slug})
        self.assertEqual(g["topic"]["slug"], slug)
        self.assertIn("THE QUESTION", g["topic"]["body"])
        # topic_list: enumeration
        lst, _ = self.mcp.tool("topic_list", {})
        self.assertIn(slug, [t["slug"] for t in lst["topics"]])
        self.assertIn("total", lst)
        # topic_state can now set priority in place (beacon audit executes)
        pr, _ = self.mcp.tool("topic_state", {"slug": slug, "priority": "critical"})
        self.assertTrue(pr.get("ok"), pr)
        g2, _ = self.mcp.tool("topic_get", {"slug": slug})
        self.assertEqual(g2["topic"]["priority"], "critical")
        # combined state+priority must SURFACE a sub-error, not mask it as ok (audit 6.1 #3)
        bad, err = self.mcp.tool(
            "topic_state", {"slug": "no-such-slug-xyz", "state": "discussed", "priority": "critical"})
        self.assertIn("error", bad)

    def test_06_batch_mutations(self):
        out, _ = self.mcp.tool("topic_add", {"items": [
            {"title": "batch alpha", "state": "open"}, {"title": "batch beta", "state": "open"},
            {"title": "batch gamma", "state": "open"}]})
        a, b2, c = [r["slug"] for r in out["results"]]
        # ONE call: discuss alpha + promote beta
        st, _ = self.mcp.tool("topic_state", {"items": [
            {"slug": a, "state": "discussed"}, {"slug": b2, "priority": "critical"}]})
        self.assertEqual(len(st["results"]), 2)
        self.assertTrue(all(not r.get("error") for r in st["results"]), st)
        # ONE call: gamma gets two extra avenues
        at, _ = self.mcp.tool("topic_attach", {"items": [
            {"slug": c, "parent_slug": a}, {"slug": c, "parent_slug": b2}]})
        self.assertEqual(len(at["results"]), 2)
        self.assertTrue(all(r.get("ok") for r in at["results"]), at)
        # ONE call: convert two
        cv, _ = self.mcp.tool("topic_convert", {"items": [
            {"slug": a, "kind": "decision", "ref": "d:1"},
            {"slug": b2, "kind": "document", "ref": "doc:2"}]})
        self.assertEqual(len(cv["results"]), 2)
        self.assertTrue(all(r.get("ok") for r in cv["results"]), cv)
        # single form still works
        self.assertTrue(self.mcp.tool("topic_state", {"slug": c, "state": "discussed"})[0].get("ok"))

    def test_07_export_import_merge_duplicates(self):
        import tempfile as _tf
        out, _ = self.mcp.tool("topic_add", {"items": [
            {"title": "queue: retry backoff strategy", "body": "THE QUESTION: exp or jitter?",
             "state": "open"},
            {"title": "queue: retry backoff approach", "body": "THE QUESTION: exponential with jitter?",
             "state": "open"}]})
        a, b = [r["slug"] for r in out["results"]]
        # duplicates surfaces the near-identical pair
        dups, _ = self.mcp.tool("topic_duplicates", {})
        self.assertGreaterEqual(dups["count"], 1, dups)
        # export writes files to a temp dir (never the repo)
        with _tf.TemporaryDirectory() as d:
            ex, _ = self.mcp.tool("topic_export", {"dir": d, "mode": "mirror"})
            self.assertGreaterEqual(ex["count"], 2)
            im, _ = self.mcp.tool("topic_import", {"dir": d})
            self.assertIn("worklist", im)             # re-import of same store = idempotent
            self.assertEqual(im["added"], 0)
        # merge folds b into a
        mg, err = self.mcp.tool("topic_merge", {"into": a, "from": b})
        self.assertFalse(err, mg)
        self.assertTrue(mg.get("ok"), mg)
        g, _ = self.mcp.tool("topic_get", {"slug": b})
        self.assertEqual(g["topic"]["state"], "pruned", "the folded topic is no longer live")


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


@unittest.skipUnless(
    _BOARD_CONFIGURED,
    "board leg skipped: set TOPICS_TEST_AUTHOR (a valid agent) + a reachable TOPICS_BOARD_URL to run it")
class TestMCPBoardBackend(unittest.TestCase):
    """Shape 3: topics as OPEN THREAD board posts. Exercises the full lifecycle including
    topic_convert minting a REAL board issue. Site-specific -> configured via env only."""

    @classmethod
    def setUpClass(cls):
        cls.mcp = MCP({"TOPICS_BACKEND": "board",
                       "TOPICS_BOARD_URL": BOARD,
                       "TOPICS_BOARD_PROJECT": os.environ.get("TOPICS_TEST_PROJECT", "topics-test"),
                       "TOPICS_BOARD_AUTHOR": os.environ["TOPICS_TEST_AUTHOR"]})

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

    def test_02_board_attach_reply(self):
        out, _ = self.mcp.tool("topic_add", {"items": [
            {"title": "sandbox avenue"}, {"title": "sandbox destination"}]})
        av, dest = [r["slug"] for r in out["results"]]
        at, _ = self.mcp.tool("topic_attach",
                              {"slug": dest, "parent_slug": av,
                               "note": "board rediscovery via reply"})
        self.assertTrue(at.get("ok"), at)
        res, _ = self.mcp.tool("topic_search", {"query": "sandbox destination"})
        # reload and confirm the extra avenue is parsed back out of the reply
        found = None
        for _ in range(3):
            g, _2 = self.mcp.tool("topic_serve", {"context": ""})
            break
        import urllib.request, json as _json, os as _os
        base = _os.environ.get("TOPICS_BOARD_URL", "http://127.0.0.1:9772")
        with urllib.request.urlopen(
                f"{base}/api/post?slug={dest}", timeout=5) as r2:
            full = _json.loads(r2.read())
        bodies = [m.get("body", "") for th in full.get("threads", [])
                  for m in th.get("messages", [])]
        self.assertTrue(any("also-parent:" in b for b in bodies),
                        "the rediscovery reply landed in the thread")
        # cleanup
        for s in (av, dest):
            self.mcp.tool("topic_state", {"slug": s, "state": "pruned", "note": "e2e cleanup"})

    def test_03_board_export_and_merge_unsupported(self):
        import tempfile as _tf
        with _tf.TemporaryDirectory() as d:
            ex, err = self.mcp.tool("topic_export", {"dir": d, "mode": "snapshot"})
            self.assertFalse(err, ex)
            self.assertEqual(ex.get("backend"), "board")
        mg, err = self.mcp.tool("topic_merge", {"into": "x", "from": "y"})
        self.assertTrue(err, "board merge must report not-supported")
        self.assertIn("cannot merge", mg.get("error", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
