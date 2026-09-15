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

# CREATE_NO_WINDOW. This suite is ordinarily run by a human from a terminal, where the
# child inherits a console and nothing flashes - which is exactly why the bug is invisible
# to whoever writes it. Wire the suite into a nightly scheduled task (pythonw, no console)
# and every unflagged spawn below allocates a VISIBLE window. Windows-only flag; 0 elsewhere.
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

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
            stderr=subprocess.DEVNULL, env=e, creationflags=_NO_WINDOW)
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
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=_NO_WINDOW)
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

    def test_02b_confirm_placement_is_reachable_over_the_seam(self):
        """A verb only the server module can call is not a verb - 0798 was exactly this shape (the
        HTTP layer could already scope a store and MCP could not reach it), so the confirm ruling
        gets an end-to-end leg rather than a unit test proving the function exists in python."""
        out, err = self.mcp.tool("topic_add", {"items": [{"title": "a placement to rule on"}]})
        self.assertFalse(err)
        slug = out["results"][0]["slug"]

        res, err = self.mcp.tool("topic_confirm", {"slug": slug, "note": "checked, it belongs here"})
        self.assertFalse(err)
        self.assertTrue(res.get("ok"), res)

        got, _ = self.mcp.tool("topic_get", {"slug": slug})
        self.assertIn("placement_confirmed",
                      [h.get("event") for h in (got["topic"].get("history") or [])],
                      "the ruling has to be visible in the record it was written to")

    def test_02c_confirming_a_missing_topic_reports_failure_over_the_seam(self):
        """The failure has to survive the transport too - a verb that swallows a bad slug into a
        cheerful ok is how a typo becomes a fabricated ruling. It surfaces BOTH ways, matching the
        rest of the surface: ok=False in the payload and isError on the envelope."""
        res, err = self.mcp.tool("topic_confirm", {"slug": "definitely-not-a-real-slug-0000"})
        self.assertTrue(err, "a bad slug must raise, not return quietly")
        self.assertFalse(res.get("ok"))

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

    def test_06b_batch_preview_writes_nothing(self):
        """A top-level preview must reach every ITEM of a batch prune.

        PROVEN RED before the fix: `preview` was read only off the per-item dict, so
        {items:[...], preview:true} dropped the flag and pruned for real. Found in the
        field 2026-08-07 - six topics previewed, six written. They were childless, so
        nothing was lost; against a HUB the same call cascades the whole live subtree
        away under the one flag whose entire job is to stop that.
        """
        out, _ = self.mcp.tool("topic_add", {"items": [
            {"title": "preview parent hub", "state": "open"},
            {"title": "preview victim one", "state": "open"},
            {"title": "preview victim two", "state": "open"}]})
        hub, v1, v2 = [r["slug"] for r in out["results"]]
        # give the hub a real child, so a wrongly-executed preview would cascade
        self.mcp.tool("topic_reparent", {"slug": v1, "parent_slug": hub})

        # EXACTLY the field call shape: each item carries its own state, preview is
        # top-level. Anything else goes red for an unrelated reason (a missing state)
        # and proves nothing about the flag.
        pv, _ = self.mcp.tool("topic_state", {
            "items": [{"slug": hub, "state": "pruned"},
                      {"slug": v2, "state": "pruned"}],
            "preview": True})
        self.assertEqual(len(pv["results"]), 2, pv)
        for r in pv["results"]:
            self.assertTrue(r.get("preview"), f"item lost the preview flag: {r}")
            self.assertIn("cascade", r)

        # THE ASSERTION THAT MATTERS: nothing changed state.
        for slug in (hub, v1, v2):
            got, _ = self.mcp.tool("topic_get", {"slug": slug})
            self.assertEqual(got["topic"]["state"], "open",
                             f"{slug} was WRITTEN by a preview")

        # and the real prune still works when preview is absent
        rp, _ = self.mcp.tool("topic_state", {"items": [{"slug": v2, "state": "pruned"}]})
        self.assertTrue(rp["results"][0].get("ok"), rp)
        self.assertEqual(
            self.mcp.tool("topic_get", {"slug": v2})[0]["topic"]["state"], "pruned")

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

    def test_08_add_refuses_degenerate_batches_loudly(self):
        """0653: a topic_add whose items never arrived (missing/empty/stringly) used to
        answer an ok-shaped {"results": []} - the capturing agent believed the seedling
        was safe and let it die. Every degenerate shape must be a LOUD error, storing
        nothing."""
        before = self.mcp.tool("topic_list", {})[0]["total"]
        for args in ({},                                            # items missing entirely
                     {"items": []},                                 # empty batch
                     {"items": '[{"title": "stringly"}]'}):         # JSON-encoded string slip
            out, err = self.mcp.tool("topic_add", args)
            self.assertIn("error", out, f"args={args!r} must refuse, got {out!r}")
            self.assertTrue(err, f"args={args!r} must set isError")
            self.assertIn("NOTHING", out["error"],
                          "the refusal must say the capture did not land")
        after = self.mcp.tool("topic_list", {})[0]["total"]
        self.assertEqual(before, after, "a refused add must store nothing")

    def test_09_add_accepts_single_form_title(self):
        """The server has always accepted a single {title,...} body; the MCP face used to
        DROP that shape silently (it only read `items`). Now it wraps it - the capture
        lands instead of dying on a shape technicality."""
        out, err = self.mcp.tool("topic_add", {
            "title": "single form rescue", "body": "no items wrapper", "state": "open"})
        self.assertFalse(err, out)
        self.assertTrue(out["results"][0].get("slug"), out)
        g, _ = self.mcp.tool("topic_get", {"slug": out["results"][0]["slug"]})
        self.assertEqual(g["topic"]["title"], "single form rescue")

    def test_10_capture_reaches_another_projects_store_and_creates_it(self):
        """1424, end to end rather than at the wire: a capture aimed at a project key that
        has NO store yet must create that store and land the topic there, while the session
        store is left completely alone. Capture is one of the two verbs server.py allows to
        create a store ("they are how a project comes to exist"), so store-creation is the
        intended behaviour and is asserted, not guarded against.

        The ISOLATION half is the load-bearing assertion. The defect being fixed is topics
        landing in the wrong tree, so a test that only proved the topic appears in the target
        would pass just as happily if the capture were written to both. It seeds the session
        store first, deliberately, so the isolation check reads a real populated list rather
        than a 404 that would also 'pass' for the wrong reason."""
        local, err = self.mcp.tool("topic_add", {
            "items": [{"title": "stays in the session store", "state": "open"}]})
        self.assertFalse(err, local)

        out, err = self.mcp.tool("topic_add", {
            "items": [{"title": "filed where its subject lives", "state": "open",
                       "body": "aimed at a store that does not exist yet"}],
            "project": "zz-elsewhere-store"})
        self.assertFalse(err, out)
        slug = out["results"][0].get("slug")
        self.assertTrue(slug, out)

        # it is READABLE in the target store, which the capture had to create
        got = json.load(urllib.request.urlopen(
            f"http://127.0.0.1:{PORT}/api/topics/{slug}?project=zz-elsewhere-store"))
        self.assertEqual(got["topic"]["title"], "filed where its subject lives")

        # ...and ABSENT from the session store, which is the actual defect
        listed, _ = self.mcp.tool("topic_list", {"limit": 500})
        titles = [t["title"] for t in listed.get("topics", [])]
        self.assertIn("stays in the session store", titles,
                      "session store did not receive the ordinary capture - the isolation "
                      "assertion below would be vacuous")
        self.assertNotIn("filed where its subject lives", titles,
                         "the capture also landed in the session store - an override that "
                         "writes to both is not an override")


class McpOpenVisualizerScoping(unittest.TestCase):
    """0653: open_visualizer handed back a BARE url, so the web UI opened on the SERVER's
    default store - which a login-autostarted server keys off its meaningless launcher cwd
    (the empty C--WINDOWS-system32 sky). The URL must scope to the session's project."""

    def test_url_carries_the_session_project(self):
        import importlib
        from unittest.mock import patch
        import mcp_tools
        importlib.reload(mcp_tools)

        def fake_http(method, url, body=None, headers=None):
            if "/api/version" in url:
                return {"version": mcp_tools.VERSION}
            raise mcp_tools.Unreachable("nothing else")

        with patch.object(mcp_tools, "_http", side_effect=fake_http):
            b = mcp_tools.ServerBackend()
            r = b.open_visualizer()
        self.assertTrue(r["running"])
        self.assertIn("project=", r["url"])
        self.assertIn(b.project, r["url"])


class McpGroomReportProjectOverride(unittest.TestCase):
    """0798: a verifier working from a second clone ran topic_groom_report as a verify
    handle and got a DIFFERENT project's tree, satisfying two PASS criteria off the wrong
    store. The store block names the tree now; this is the other half - the tool must let
    a caller POINT the report at the store the issue names, instead of silently taking
    whatever cwd hands it. The HTTP layer already scopes on ?project=; it was simply
    unreachable from MCP."""

    def _url_for(self, args):
        import importlib
        from unittest.mock import patch
        import mcp_tools
        importlib.reload(mcp_tools)
        seen = {}

        def fake_http(method, url, body=None, headers=None):
            seen["url"] = url
            return {"health": {}}

        with patch.object(mcp_tools, "_http", side_effect=fake_http):
            mcp_tools._call("topic_groom_report", args)
        return seen["url"]

    def test_tool_declares_a_project_argument(self):
        import mcp_tools
        tool = next(t for t in mcp_tools.TOOLS if t["name"] == "topic_groom_report")
        self.assertIn("project", tool["inputSchema"]["properties"],
                      "no way to aim the report at the store under review")

    def test_explicit_project_reaches_the_query_string(self):
        self.assertIn("project=some-other-store", self._url_for({"project": "some-other-store"}))

    def test_omitting_it_keeps_the_session_project(self):
        import mcp_tools
        self.assertIn("project=" + mcp_tools.ServerBackend().project, self._url_for({}))



class McpAddProjectOverride(unittest.TestCase):
    """1424: topic_add binds the store from the session cwd ONCE and offers no override, so
    an agent working in another repo cannot file a topic where it belongs even knowing
    exactly where that is. Measured 2026-08-30 on the quantum-concepts tree: 22 of 31 live
    topics were other projects' work - 9 qc-game, 11 messageboard, 2 book-by-codex - and
    the two repos the house was actually committing to had no store at all, because every
    capture reflex drained into the store the session happened to key.

    Two consequences beyond the misfiling, both measured. A topic in the wrong store is
    invisible to duplicate detection, which is PER-STORE - so the one mechanism that would
    have said "already asked" cannot see it. And re-homing afterwards is a copy-verify-prune
    dance, because there is still no per-topic move.

    The HTTP layer has always scoped on ?project= and server.py explicitly allows capture to
    CREATE a store ("only CAPTURE and IMPORT may create a store - they are how a project
    comes to exist"). It was simply unreachable from MCP. topic_groom_report took exactly
    this override at 0.51 (issue 0798); this is the same treatment for the capture verb.
    """

    def _sent(self, args):
        """Return the (url, body) topic_add actually put on the wire."""
        import importlib
        from unittest.mock import patch
        import mcp_tools
        importlib.reload(mcp_tools)
        seen = {}

        def fake_http(method, url, body=None, headers=None):
            seen["url"], seen["body"] = url, body
            return {"results": []}

        with patch.object(mcp_tools, "_http", side_effect=fake_http):
            mcp_tools._call("topic_add", args)
        return seen

    def test_tool_declares_a_project_argument(self):
        import mcp_tools
        tool = next(t for t in mcp_tools.TOOLS if t["name"] == "topic_add")
        self.assertIn("project", tool["inputSchema"]["properties"],
                      "no way to file a capture into the store it is ABOUT")

    def test_explicit_project_reaches_the_wire(self):
        sent = self._sent({"items": [{"title": "filed across a repo boundary"}],
                           "project": "F--writing-qc-game"})
        self.assertEqual(sent["body"].get("project"), "F--writing-qc-game",
                         "the override never reached the POST body - the capture would "
                         "land in the session store, which is the whole defect")

    def test_omitting_it_keeps_the_session_project(self):
        import mcp_tools
        sent = self._sent({"items": [{"title": "an ordinary local capture"}]})
        self.assertEqual(sent["body"].get("project"), mcp_tools.ServerBackend().project,
                         "an omitted project must be byte-identical to today's behaviour")

    def test_the_override_does_not_leak_into_later_calls(self):
        """The per-CALL actor bug's shape, one field over: a capture aimed at another store
        must not rebind the backend's project and silently redirect every later op in the
        session. This is the assertion the actor fix wishes it had had."""
        import importlib
        from unittest.mock import patch
        import mcp_tools
        importlib.reload(mcp_tools)
        session_project = mcp_tools.ServerBackend().project
        seen = []

        def fake_http(method, url, body=None, headers=None):
            seen.append(body)
            return {"results": []}

        with patch.object(mcp_tools, "_http", side_effect=fake_http):
            b = mcp_tools._backend()
            b.add([{"title": "aimed elsewhere"}], project="F--writing-somewhere-else")
            b.add([{"title": "back to normal"}])
        self.assertEqual(seen[0].get("project"), "F--writing-somewhere-else")
        self.assertEqual(seen[1].get("project"), session_project,
                         "the override leaked - every later capture in this session would "
                         "have been redirected to another project's store")

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


class McpConfirmCarriesTheActor(unittest.TestCase):
    """0.52.1 field catch, minutes after arming: the FIRST live confirm recorded actor 'unknown'.
    confirm() wrapped its payload in _p(), which stamps project but not actor - every other verb
    passes actor explicitly, and the server defaults an absent one to 'unknown'. In the one verb
    whose entire purpose is per-actor attribution, that silently pools every MCP-side ruling
    under 'unknown' - the same attribution-vanishes-in-transport class as the per-item actor bug
    fixed in the same release, one seam over."""

    def _payload(self):
        import importlib
        from unittest.mock import patch
        import mcp_tools
        importlib.reload(mcp_tools)
        seen = {}

        def fake_http(method, url, body=None, headers=None):
            seen["body"] = body
            return {"ok": True}

        with patch.object(mcp_tools, "_http", side_effect=fake_http):
            mcp_tools._call("topic_confirm", {"slug": "some-topic", "note": "checked"})
        return seen["body"], mcp_tools.ACTOR

    def test_confirm_sends_the_session_actor(self):
        body, actor = self._payload()
        self.assertEqual(body.get("actor"), actor,
                         "the ruling arrives at the server with no actor and records as "
                         "'unknown' - the attribution the verb exists for")


class RunnerBlockIsLast(unittest.TestCase):
    """1465, Iris: `unittest.main()` sat at line 624 with a TestCase class defined at 627, so the
    DOCUMENTED command collected 25 of 26 tests and stayed green through a planted regression -
    the orphaned class was the guard for topic_confirm's actor, unarmed and invisible in the OK.
    unittest.main() collects the module namespace as it stands and then sys.exit()s, so anything
    below it never executes. Appending a class to the end of a file is the natural thing to do and
    was silently wrong, which is why this is a structural guard and not a note in the file."""

    def test_no_definition_follows_the_runner_block(self):
        import ast
        source = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        runner_line = None
        for node in tree.body:
            if isinstance(node, ast.If) and ast.unparse(node.test) == "__name__ == '__main__'":
                runner_line = node.lineno
        self.assertIsNotNone(runner_line, "no `if __name__ == \"__main__\"` block found")
        stragglers = [
            n.name for n in tree.body
            if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and n.lineno > runner_line
        ]
        self.assertEqual(
            stragglers, [],
            "these are defined AFTER unittest.main() and can never be collected by "
            "`python test_mcp.py`: " + ", ".join(stragglers))


class McpSearchRefusesABlankQuery(unittest.TestCase):
    """Captured topics run 28, fixed run 33 (Tare). `topic_search` coerced a missing or blank
    query to "" and ran it, and the call returned `{"results": []}` - no error, no complaint.

    An empty result from a MALFORMED call is byte-identical to an empty result meaning nothing
    matched, and there is nothing in the payload to tell them apart. The failure direction is the
    expensive one, because this verb's whole stated job is to be run BEFORE capture ("the dup you
    merge into is better than the twin you plant"): a caller whose query never arrived reads []
    as "no duplicate exists" and plants the twin. Refuse by name instead, the way topic_reparent
    already refuses a missing parent_slug."""

    def _search(self, args):
        import importlib
        from unittest.mock import patch
        import mcp_tools
        importlib.reload(mcp_tools)
        calls = []

        def fake_http(method, url, body=None, headers=None):
            calls.append((method, url))
            return {"results": []}

        with patch.object(mcp_tools, "_http", side_effect=fake_http):
            out = mcp_tools._call("topic_search", args)
        return out, calls

    def test_blank_query_is_refused_and_never_reaches_the_server(self):
        for args in ({"query": ""}, {"query": "   "}, {}):
            with self.subTest(args=args):
                out, calls = self._search(args)
                self.assertIn("error", out,
                              "a blank query returned a result set instead of refusing - [] here "
                              "is indistinguishable from 'nothing matched'")
                self.assertIn("query", out.get("error", ""),
                              "the refusal must name the argument at fault, not just fail")
                self.assertEqual(calls, [], "a refused call must not reach the server")

    def test_a_real_query_still_reaches_the_server(self):
        """The control. A refusal that also swallowed valid queries would pass the test above
        while destroying the verb, so this pins the other side of the discrimination."""
        out, calls = self._search({"query": "stdio seam"})
        self.assertNotIn("error", out, "a real query must not be refused")
        self.assertEqual(len(calls), 1, "a real query must still reach the server exactly once")


if __name__ == "__main__":
    unittest.main(verbosity=2)
