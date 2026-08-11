#!/usr/bin/env python3
"""No launch path may use DETACHED_PROCESS - the console-flash guard.

THE BUG THIS EXISTS TO END. On Windows, a process created with DETACHED_PROCESS (0x8) has NO
console at all. That looks like what you want for a background server, and it is wrong: the
moment that process spawns ANYTHING itself, Windows has no console for the child to inherit,
so it ALLOCATES A NEW ONE - a real console window that appears, steals keyboard focus, and
vanishes. On a machine running the login launcher that is a random flicker that eats
keystrokes and kicks fullscreen games to the desktop, with no error anywhere to trace it to.

CREATE_NO_WINDOW (0x08000000) is the correct flag: the process gets its own console and that
console is never shown, so its children inherit a real-but-invisible console and nothing is
ever allocated on screen.

WHY A SCANNER AND NOT A UNIT TEST PER SITE. This was diagnosed once before and fixed in ONE
place - server.py's git call carries the right flag and a correct comment - while three other
launch paths kept DETACHED_PROCESS. Worse, test_autostart.py ASSERTED the wrong value, so
anyone who fixed a launch path correctly would have gone red and reverted. A per-site test
cannot catch the site nobody thought of, and the launcher is COPIED to ~/.topic-visualizer/ so
it cannot import a shared constant from this package. A scan over the tree is the only guard
that reaches all four, and the next one somebody adds.

    python server/test_no_console_flash.py
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

# Files that legitimately name DETACHED_PROCESS while never PASSING it: this test and the
# changelog prose. Everything else in the tree is fair game for the scan.
_ALLOWED = {"test_no_console_flash.py"}


def _py_files():
    for p in sorted(REPO.rglob("*.py")):
        if "__pycache__" in p.parts or p.name in _ALLOWED:
            continue
        yield p


def _eval_int(node, consts):
    """Evaluate a flag expression to ONE int, or raise. Handles an int literal, a module-level
    named constant, and `a | b` over either. Anything else raises rather than returning a
    default - a default here is how the scanner went blind once already."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in consts:
            return consts[node.id]
        raise Unresolvable(f"unknown name {node.id!r}")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _eval_int(node.left, consts) | _eval_int(node.right, consts)
    # getattr(subprocess, "CREATE_NO_WINDOW", 0) - the messageboard port of this guard taught
    # its scanner this idiom first, and the first file here to use it went loud-UNREADABLE,
    # which is the anti-blindness leg doing its job: teach the shape, never default it.
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "getattr" and len(node.args) == 3
            and isinstance(node.args[0], ast.Name) and node.args[0].id == "subprocess"
            and isinstance(node.args[1], ast.Constant)):
        v = getattr(subprocess, node.args[1].value, None)
        if isinstance(v, int):
            return v
        return _eval_int(node.args[2], consts)
    raise Unresolvable(ast.dump(node)[:80])


class Unresolvable(Exception):
    """A creationflags expression this scanner cannot evaluate.

    Raised rather than skipped ON PURPOSE. The first version of this file collected only
    INTEGER LITERALS and returned [] for anything else. Then the fix replaced the magic
    numbers with named constants - better code - and both load-bearing legs went vacuously
    green: `any(v & DETACHED for v in [])` is False, and the other leg skipped empty lists.
    The guard reported CLEAN on files it could no longer read, which is the exact defect it
    exists to catch, committed by the guard itself. An expression we cannot evaluate must be
    LOUD, never silently empty.
    """


def _creationflags_values(path):
    """Every value assigned to a `creationflags` key/kwarg in one file, as (lineno, ints).

    Reads the AST rather than the text so a comment mentioning the flag cannot trip it and a
    split-across-lines expression cannot hide from it - the exact two ways a source-text
    assertion in this repo has been fooled before. Module-level int constants are resolved,
    because naming the flags is what a correct fix looks like and the scanner has to survive it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []

    # module-level `NAME = <int expr>` so `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP` resolves
    consts: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                consts[node.targets[0].id] = _eval_int(node.value, consts)
            except Unresolvable:
                pass

    def literal_ints(node):
        """None means UNREADABLE - never an empty list, which every caller would read as
        'nothing bad here'. The callers treat None as an offender."""
        try:
            return [_eval_int(node, consts)]
        except Unresolvable:
            return None

    for node in ast.walk(tree):
        # kwargs: subprocess.Popen(..., creationflags=X)
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "creationflags":
                    found.append((kw.value.lineno, literal_ints(kw.value)))
        # dict literals: {"creationflags": X}
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value == "creationflags":
                    found.append((v.lineno, literal_ints(v)))
        # subscript assignment: kw["creationflags"] = X
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                        and t.slice.value == "creationflags"):
                    found.append((node.value.lineno, literal_ints(node.value)))
    return found


class NoDetachedProcessAnywhere(unittest.TestCase):
    def test_no_file_passes_detached_process(self):
        """The load-bearing leg. DETACHED_PROCESS must not reach creationflags anywhere."""
        offenders = []
        for path in _py_files():
            for lineno, ints in _creationflags_values(path):
                if ints is None or any(v & DETACHED_PROCESS for v in ints):
                    shown = "UNREADABLE" if ints is None else [hex(v) for v in ints]
                    offenders.append(f"{path.relative_to(REPO)}:{lineno} -> {shown}")
        self.assertEqual(offenders, [], "DETACHED_PROCESS leaves a process with NO console, so "
                                        "its first child ALLOCATES a visible one. Use "
                                        "CREATE_NO_WINDOW (0x08000000) instead:\n  "
                                        + "\n  ".join(offenders))

    def test_every_creationflags_requests_no_window(self):
        """A creationflags that forgets CREATE_NO_WINDOW is the same bug wearing a 0."""
        offenders = []
        for path in _py_files():
            for lineno, ints in _creationflags_values(path):
                if ints is None or not any(v & CREATE_NO_WINDOW for v in ints):
                    shown = "UNREADABLE" if ints is None else [hex(v) for v in ints]
                    offenders.append(f"{path.relative_to(REPO)}:{lineno} -> {shown}")
        self.assertEqual(offenders, [], "every Windows spawn must carry CREATE_NO_WINDOW:\n  "
                                        + "\n  ".join(offenders))

    def test_every_creationflags_expression_is_readable(self):
        """The anti-blindness leg, and the reason this file has a version 2.

        v1 collected integer literals only. The fix then NAMED the constants, which is what a
        correct fix looks like, and the scanner silently returned [] for every site it had been
        built to watch - so the two legs above passed vacuously on exactly the four files that
        carried the bug. A guard that cannot read its subject must FAIL, never report clean.
        """
        unreadable, sites = [], 0
        for path in _py_files():
            for lineno, ints in _creationflags_values(path):
                sites += 1
                if ints is None:
                    unreadable.append(f"{path.relative_to(REPO)}:{lineno}")
        self.assertEqual(unreadable, [], "the scanner cannot evaluate these, so it is BLIND to "
                                         "them - teach _eval_int the shape or simplify the "
                                         "expression:\n  " + "\n  ".join(unreadable))
        self.assertGreaterEqual(sites, 4, "the scanner found almost no creationflags at all - it "
                                          "has stopped seeing the thing it guards")

    def test_the_scanner_can_actually_see_a_violation(self):
        """A scanner that cannot fail is not a guard. Feed it the defect and watch it bite -
        otherwise a refactor that breaks the AST walk leaves two permanently-green legs."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.py"
            bad.write_text(
                "import subprocess\n"
                "subprocess.Popen(['x'], creationflags=0x00000008 | 0x00000200)\n",
                encoding="utf-8")
            vals = _creationflags_values(bad)
        self.assertEqual(len(vals), 1, "the AST walk stopped seeing kwarg creationflags")
        self.assertTrue(any(v & DETACHED_PROCESS for v in vals[0][1]))
        self.assertFalse(any(v & CREATE_NO_WINDOW for v in vals[0][1]))

    def test_scanner_reads_all_four_launch_paths(self):
        """Scope check: the guard is only worth its green if it actually opened the files that
        carried the bug. A negative result is only as good as its reach."""
        scanned = {p.name for p in _py_files()}
        for required in ("server.py", "mcp_tools.py", "install_service.py", "tv_autostart.py"):
            self.assertIn(required, scanned, f"the scan never reached {required}")

    def test_every_windows_spawn_site_carries_flags(self):
        """A spawn with NO creationflags at all is the same flash: on a console-less parent
        Windows allocates a console for the child. Catches the site nobody flagged rather than
        the site somebody flagged wrongly."""
        # Match the callee EXACTLY. An earlier version used re.match on the unparsed func, which
        # matched the prefix of a chained expression - `subprocess.run(...).stdout.strip` read as
        # a spawn, so a correctly-flagged call was reported as an offender. A guard that cries
        # wolf gets switched off, which is how the bug it guards comes back.
        SPAWNS = {"subprocess.run", "subprocess.Popen", "subprocess.call",
                  "subprocess.check_output", "subprocess.check_call"}
        offenders = []
        for path in _py_files():
            if path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                if fn not in SPAWNS:
                    continue
                has = any(kw.arg == "creationflags" for kw in node.keywords)
                # **kwargs / **flags forwarding counts: the dict is built next to the call and
                # is covered by the two literal legs above.
                splat = any(kw.arg is None for kw in node.keywords)
                if not (has or splat):
                    offenders.append(f"{path.relative_to(REPO)}:{node.lineno} {fn}(...)")
        self.assertEqual(offenders, [], "these spawn a process with no console flags, so on a "
                                        "windowless parent Windows allocates a visible "
                                        "console:\n  " + "\n  ".join(offenders))


class LauncherBehaviour(unittest.TestCase):
    """The scan proves the constants; this proves the code path actually hands them over."""

    def test_detached_helper_requests_no_window_not_detachment(self):
        import tv_autostart
        kw = tv_autostart._detached()
        if os.name != "nt":
            self.assertTrue(kw.get("start_new_session"))
            self.assertNotIn("creationflags", kw)
            return
        flags = kw.get("creationflags")
        self.assertTrue(flags & CREATE_NO_WINDOW, "launcher spawns without CREATE_NO_WINDOW")
        self.assertFalse(flags & DETACHED_PROCESS, "launcher still passes DETACHED_PROCESS")
        self.assertTrue(flags & CREATE_NEW_PROCESS_GROUP, "lost Ctrl+C isolation")


if __name__ == "__main__":
    unittest.main(verbosity=2)
