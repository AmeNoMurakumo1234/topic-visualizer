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
    # `0x08000000 if os.name == "nt" else 0` - the cross-platform idiom the skill prescribes and
    # the form the test files adopted on 2026-08-14. Resolve it to its WINDOWS branch, because
    # that is the only branch this guard has an opinion about: off Windows creationflags must be
    # 0, and demanding CREATE_NO_WINDOW there would convict correct code. The condition is
    # matched EXPLICITLY rather than assuming the body is the Windows arm - `if os.name != "nt"`
    # inverts it, and silently taking the wrong branch would make the guard confidently wrong,
    # which is worse than the blindness this class exists to prevent.
    if isinstance(node, ast.IfExp):
        win = _windows_branch(node)
        if win is None:
            raise Unresolvable("ternary whose condition is not an os/platform test: "
                               + ast.unparse(node.test)[:60])
        return _eval_int(win, consts)
    raise Unresolvable(ast.dump(node)[:80])


def _windows_branch(node):
    """For `A if <os test> else B`, the arm that runs ON WINDOWS - or None if the condition is
    not a recognised os/platform test. Never guesses: an unrecognised condition returns None so
    the caller raises Unresolvable."""
    test = node.test
    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1):
        return None
    left, op, right = test.left, test.ops[0], test.comparators[0]
    if not (isinstance(right, ast.Constant) and isinstance(right.value, str)):
        return None
    subject = ast.unparse(left)
    windows_values = {"os.name": "nt", "sys.platform": "win32", "platform.system": "Windows"}
    if subject not in windows_values:
        return None
    is_windows_value = right.value == windows_values[subject]
    if isinstance(op, ast.Eq):
        return node.body if is_windows_value else node.orelse
    if isinstance(op, ast.NotEq):
        return node.orelse if is_windows_value else node.body
    return None


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


def _creationflags_carriers(tree):
    """Names in one file that demonstrably carry a creationflags key.

    Two kinds, because both idioms are in this tree and both are correct code:
      FUNCTIONS - `def _no_window(): ... return {"creationflags": X}`, splatted as **_no_window()
      VARIABLES - `flags = {"creationflags": X}` or `kwargs["creationflags"] = X`, as **flags

    This exists so the coverage leg can stop treating every **splat as innocent. It is
    deliberately NAME-based and shallow: it proves the splatted thing mentions creationflags
    somewhere, not that it does so on every path. The VALUE legs above are what check the flag
    is the right one, and they read every creationflags in the file regardless of how it is
    delivered - so shallow here is honest, not lazy.
    """
    funcs, vars_ = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and sub.value == "creationflags":
                    funcs.add(node.name)
                    break
                if isinstance(sub, ast.keyword) and sub.arg == "creationflags":
                    funcs.add(node.name)
                    break
        # kwargs["creationflags"] = X
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name)
                        and isinstance(t.slice, ast.Constant) and t.slice.value == "creationflags"):
                    vars_.add(t.value.id)
            # flags = {"creationflags": X}  (also through a ternary, which is how this repo
            # writes the os.name == "nt" fork)
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                for sub in ast.walk(node.value):
                    if isinstance(sub, ast.Constant) and sub.value == "creationflags":
                        vars_.add(node.targets[0].id)
                        break
    return {"funcs": funcs, "vars": vars_}


def _splat_carries_flags(node, carriers):
    """Does `**node` deliver creationflags? Unknown shapes return False on purpose - the caller
    reports them LOUDLY rather than passing them, because 'I could not tell' and 'it is fine'
    are the two readings a guard must never merge."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id in carriers["funcs"]
    if isinstance(node, ast.Name):
        return node.id in carriers["vars"]
    return False


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
        the site somebody flagged wrongly.

        TEST FILES ARE IN SCOPE (changed 2026-08-14, and the exemption is the reason this leg
        had five real offenders it could not see). The old version skipped `test_*.py` on the
        reasoning that a test is something a human types into a terminal. That is true right up
        until a suite is wired into a nightly scheduled task, which runs it under pythonw with
        NO console - and test_mcp/test_server Popen a SERVER, which goes on to spawn more. The
        sibling repo already hit exactly that shape (a scheduled pythonw job running a test
        tree). The skill's own rule settles it: you cannot decide this per-call, and "not sure"
        means yes. Five lines of flag is cheaper than one more machine flickering.
        """
        # Match the callee EXACTLY. An earlier version used re.match on the unparsed func, which
        # matched the prefix of a chained expression - `subprocess.run(...).stdout.strip` read as
        # a spawn, so a correctly-flagged call was reported as an offender. A guard that cries
        # wolf gets switched off, which is how the bug it guards comes back. (The external
        # scan_spawns.py has the untightened form of this bug the other way round: it matches a
        # spawn by BARE NAME, so a local helper called `call(...)` reads as subprocess.call.)
        SPAWNS = {"subprocess.run", "subprocess.Popen", "subprocess.call",
                  "subprocess.check_output", "subprocess.check_call"}
        offenders, unresolved, sites = [], [], 0
        for path in _py_files():
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
            carriers = _creationflags_carriers(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
                if fn not in SPAWNS:
                    continue
                sites += 1
                if any(kw.arg == "creationflags" for kw in node.keywords):
                    continue
                # A **splat is NOT taken on faith any more. It counts only when the thing being
                # splatted demonstrably carries creationflags - a helper like _no_window() or a
                # dict built next to the call. An unrecognised splat is LOUD, never assumed
                # innocent, which is the same anti-blindness rule the Unresolvable class states.
                splats = [kw.value for kw in node.keywords if kw.arg is None]
                if not splats:
                    offenders.append(f"{path.relative_to(REPO)}:{node.lineno} {fn}(...)")
                    continue
                if not any(_splat_carries_flags(s, carriers) for s in splats):
                    shown = ", ".join(ast.unparse(s) for s in splats)
                    unresolved.append(f"{path.relative_to(REPO)}:{node.lineno} {fn}(**{shown})")
        self.assertEqual(offenders, [], "these spawn a process with no console flags, so on a "
                                        "windowless parent Windows allocates a visible "
                                        "console:\n  " + "\n  ".join(offenders))
        self.assertEqual(unresolved, [], "these forward a **splat this scanner cannot tie to any "
                                         "creationflags carrier, so it cannot tell a guarded "
                                         "spawn from a bare one - name the helper or pass the "
                                         "flag directly:\n  " + "\n  ".join(unresolved))
        self.assertGreaterEqual(sites, 14, "the spawn walk has stopped finding the calls it "
                                           "guards - a refactor of the AST match would leave "
                                           "this leg permanently, silently green")


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
