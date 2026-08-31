#!/usr/bin/env python3
"""0.55.5: the release version lives in FOUR places and they must move together.

WHY THIS FILE EXISTS. 0.55.5 shipped half-stamped on 2026-08-23: plugin.json moved to
0.55.5 while server.py VERSION and marketplace.json stayed at 0.55.4, and no changelog
entry was written. Nothing failed - the code was correct - but the project's ONE signal
that a fix has reached the machine is `topic_doctor`, which prints `version` from
server.py beside `installed_version` from plugin.json. A split stamp makes that pair lie
in both directions: a real delivery failure reads as a version skew, and a genuine skew
reads as delivery. The check that watches the delivery chain must not itself be the thing
that drifts.

DERIVED, deliberately. Nothing here hardcodes a version number - the test READS all four
files and asserts they agree, so it keeps working across every future release without
anyone remembering to update it. A hand-kept expected value would be one more stamp to
forget.

UNREADABLE IS ITS OWN LOUD FAILURE. Each reader raises with the path it could not read
rather than returning a default. A version check that silently compares two Nones passes
vacuously, which is the failure mode this repo has already recorded once
(the spawn scanner that returned [] for every site it watched).

    python server/test_version_stamps.py
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

# server/ -> plugin/ -> repo root
_SERVER_DIR = Path(__file__).resolve().parent
_PLUGIN_DIR = _SERVER_DIR.parent
_REPO_ROOT = _PLUGIN_DIR.parent

SERVER_PY = _SERVER_DIR / "server.py"
PLUGIN_JSON = _PLUGIN_DIR / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = _REPO_ROOT / ".claude-plugin" / "marketplace.json"
CHANGELOG = _PLUGIN_DIR / "CHANGELOG.md"

_SEMVER = re.compile(r"^\d+\.\d+\.\d+")


def _read(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"version stamp source is MISSING: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - loud on purpose
        raise AssertionError(f"version stamp source is UNREADABLE: {path} ({exc})") from exc


def server_py_version() -> str:
    text = _read(SERVER_PY)
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M)
    if not m:
        raise AssertionError(f"no top-level VERSION = \"...\" found in {SERVER_PY}")
    return m.group(1)


def plugin_json_version() -> str:
    data = json.loads(_read(PLUGIN_JSON))
    v = data.get("version")
    if not v:
        raise AssertionError(f"no 'version' key in {PLUGIN_JSON}")
    return v


def marketplace_json_version() -> str:
    data = json.loads(_read(MARKETPLACE_JSON))
    plugins = data.get("plugins") or []
    hits = [p.get("version") for p in plugins if p.get("name") == "topic-visualizer"]
    if not hits:
        # the marketplace may list the plugin without a name match; fall back to a sole entry
        hits = [p.get("version") for p in plugins]
    hits = [h for h in hits if h]
    if len(hits) != 1:
        raise AssertionError(
            f"expected exactly one topic-visualizer version in {MARKETPLACE_JSON}, got {hits!r}"
        )
    return hits[0]


def changelog_top_version() -> str:
    for line in _read(CHANGELOG).splitlines():
        if line.startswith("## "):
            head = line[3:].strip()
            m = _SEMVER.match(head)
            if not m:
                raise AssertionError(f"first CHANGELOG heading is not a version: {line!r}")
            return m.group(0)
    raise AssertionError(f"no '## <version>' heading found in {CHANGELOG}")


class VersionStamps(unittest.TestCase):
    def test_all_four_stamps_agree(self):
        stamps = {
            "server.py VERSION": server_py_version(),
            "plugin.json version": plugin_json_version(),
            "marketplace.json version": marketplace_json_version(),
            "CHANGELOG top entry": changelog_top_version(),
        }
        distinct = set(stamps.values())
        self.assertEqual(
            len(distinct),
            1,
            "release version stamps have DRIFTED - they must move together:\n  "
            + "\n  ".join(f"{k}: {v}" for k, v in stamps.items()),
        )

    def test_stamps_are_semver_shaped(self):
        # guards against a reader that "succeeds" by matching an empty or prose value,
        # which would make the agreement test above pass vacuously.
        for name, value in (
            ("server.py", server_py_version()),
            ("plugin.json", plugin_json_version()),
            ("marketplace.json", marketplace_json_version()),
            ("CHANGELOG", changelog_top_version()),
        ):
            with self.subTest(source=name):
                self.assertRegex(value, r"^\d+\.\d+\.\d+", f"{name} version is not semver: {value!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
