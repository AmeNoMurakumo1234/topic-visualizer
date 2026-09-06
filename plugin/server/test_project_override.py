#!/usr/bin/env python3
"""Every store-scoped MCP verb must accept the same `project` override topic_add already takes.

THE DEFECT (four independent arrivals in four days, all measured by the agent who hit it):
  2026-09-01 Codex  - topic_add(project=...) succeeded, then topic_merge/topic_get on the
                      returned slug both answered "not found".
  2026-09-02 Polaris- captured cross-store correctly, then topic_edit could not reach it.
  2026-09-04 Codex  - the tool DETECTED the duplicate, TOLD him to fold rather than plant a
                      twin, and then offered no verb able to do it.
  2026-09-04 Lemma  - topic_get could not READ the kin it was told to judge; topic_attach
                      could not record the see_also.
  2026-09-06 Tare   - could not checkpoint or dedup-scan the plugin's own store from a
                      quantum-concepts session; hand-wrote an HTTP client to groom it.

WHY IT IS ONE DEFECT AND NOT FIVE COMPLAINTS: 1424 made routing-by-SUBJECT the documented,
canon-endorsed path, and 0798 aimed the report at a named store. So capture can now leave the
session store - but every verb that MAINTAINS what was captured stayed session-scoped. The
result is a one-way door: the tool routes a topic somewhere it cannot then read, edit, link,
merge or prune. Worse, topic_add's own result instructs the caller to fold the near-duplicate
it just found, which is advice no available verb can take.

The HTTP layer has scoped on project all along (every route resolves
`parse_qs(u.query).get("project") or body.get("project") or _default_project`, then pins with
_use_project). Only the MCP tool layer never threaded the parameter through, and it already has
exactly two seams to thread it into: _q() for GET and _p() for POST.

INVARIANT THIS PINS, and it is the one that matters for existing callers: omitting `project`
must keep the session store, unchanged, for every verb.

    python server/test_project_override.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mcp_tools  # noqa: E402

OTHER = "F--writing-some-other-store"

# Every verb that operates ON A STORE, with arguments sufficient to reach the transport.
# doctor() is deliberately absent: it reports THIS session's resolved config and liveness,
# so a project override would be a category error rather than a missing feature.
# open_visualizer() is deliberately absent: it builds a browser URL and never calls _http,
# so it needs a different harness and no capture has asked for it.
CALLS = {
    "get":         dict(slug="a-topic"),
    "list_":       dict(),
    "priority":    dict(slug="a-topic", critical=True),
    "serve":       dict(context="ctx"),
    "search":      dict(query="q"),
    "state":       dict(slug="a-topic", state="discussed", note="n"),
    "convert":     dict(slug="a-topic", kind="work_item", ref="R-1", note="n"),
    "attach":      dict(slug="a-topic", parent_slug="a-hub", note="n"),
    "reparent":    dict(slug="a-topic", parent_slug="a-hub"),
    "edit":        dict(slug="a-topic", title="t"),
    "reconcile":   dict(items=[{"slug": "a-topic", "state": "discussed"}]),
    "buckets":     dict(),
    "checkpoint":  dict(label="pre-groom"),
    "checkpoints": dict(),
    "restore":     dict(),
    "export":      dict(),
    "import_":     dict(),
    "merge":       dict(into="survivor", from_="absorbed"),
    "confirm":     dict(slug="a-topic"),
    "duplicates":  dict(),
}


class ProjectOverrideReachesTheWire(unittest.TestCase):
    """The override must arrive at the server, by whichever seam the verb uses."""

    def _sent(self, verb, kwargs):
        """Call one verb with _http stubbed; return what it tried to put on the wire."""
        seen = {}

        def fake_http(method, url, body=None, headers=None):
            seen["method"], seen["url"], seen["body"] = method, url, body or {}
            return {"ok": True}

        with patch.object(mcp_tools, "_http", side_effect=fake_http):
            getattr(mcp_tools.ServerBackend(), verb)(**kwargs)
        return seen

    def _project_on_the_wire(self, seen):
        """The project a call actually carried - query string for GET, body for POST."""
        if seen.get("body"):
            return seen["body"].get("project")
        url = seen.get("url", "")
        if "project=" not in url:
            return None
        return url.split("project=")[1].split("&")[0]

    def test_every_store_scoped_verb_accepts_an_explicit_project(self):
        """The defect itself: a verb that cannot be aimed cannot maintain what add() routed."""
        missing = []
        for verb, kwargs in CALLS.items():
            try:
                seen = self._sent(verb, dict(kwargs, project=OTHER))
            except TypeError as e:
                missing.append(f"{verb}: does not accept project ({e})")
                continue
            got = self._project_on_the_wire(seen)
            if got != OTHER:
                missing.append(f"{verb}: accepted project but sent {got!r}")
        self.assertEqual(missing, [], "verbs that cannot be aimed at another store:\n  "
                                      + "\n  ".join(missing))

    def test_omitting_the_override_keeps_the_session_project(self):
        """The compatibility invariant - every existing caller passes nothing and must not move."""
        session = mcp_tools.ServerBackend().project
        wrong = []
        for verb, kwargs in CALLS.items():
            got = self._project_on_the_wire(self._sent(verb, dict(kwargs)))
            if got != session:
                wrong.append(f"{verb}: sent {got!r}, expected the session store {session!r}")
        self.assertEqual(wrong, [], "verbs that lost the session store:\n  " + "\n  ".join(wrong))

    def test_an_override_does_not_leak_into_later_calls(self):
        """One aimed call must not silently redirect the rest of the process (the _p contract)."""
        session = mcp_tools.ServerBackend().project
        backend = mcp_tools.ServerBackend()
        seen = []

        def fake_http(method, url, body=None, headers=None):
            seen.append((url, body or {}))
            return {"ok": True}

        with patch.object(mcp_tools, "_http", side_effect=fake_http):
            backend.get(slug="a-topic", project=OTHER)
            backend.get(slug="a-topic")

        self.assertIn(OTHER, seen[0][0], "the aimed call did not carry the override")
        self.assertIn(f"project={session}", seen[1][0],
                      "the override leaked into the next call on the same backend")


class ToolSchemaDeclaresProject(unittest.TestCase):
    """An override the schema does not declare is unreachable by an MCP client."""

    def test_every_store_scoped_tool_declares_a_project_argument(self):
        tools = {t["name"]: t for t in mcp_tools.TOOLS}
        # method name -> MCP tool name, for the few that differ
        renamed = {"list_": "topic_list", "import_": "topic_import",
                   "priority": "topic_state", "groom": "topic_groom_report"}
        undeclared = []
        for verb in CALLS:
            name = renamed.get(verb, "topic_" + verb)
            t = tools.get(name)
            if t is None:
                continue  # not exposed as its own tool; covered via its sibling
            props = t.get("inputSchema", {}).get("properties", {})
            if "project" not in props:
                undeclared.append(name)
        self.assertEqual(sorted(set(undeclared)), [],
                         "tools whose schema hides the override: " + str(sorted(set(undeclared))))


class FallbackRefusesAnOverrideLoudly(unittest.TestCase):
    """With the server down, the sqlite fallback can only reach THIS session's store.

    Silently writing locally is the exact defect 1424/0798 refuse to commit, so an aimed call
    must fail loudly rather than land in the wrong tree. This mirrors add()'s and groom()'s
    established refusal, and it is the leg that keeps a fix from creating a worse bug than the
    one it closes.
    """

    def test_an_aimed_call_refuses_rather_than_writing_the_session_store(self):
        backend = mcp_tools.ServerBackend()
        with patch.object(mcp_tools, "_http", side_effect=mcp_tools.Unreachable("down")):
            with patch.object(backend, "_fallback") as fb:
                out = backend.state(slug="a-topic", state="pruned", note="n", project=OTHER)
        self.assertIn("error", out, f"an aimed call fell through to the local store: {out!r}")
        self.assertFalse(fb.called, "the fallback was used for a call aimed at another store")


if __name__ == "__main__":
    unittest.main(verbosity=2)
