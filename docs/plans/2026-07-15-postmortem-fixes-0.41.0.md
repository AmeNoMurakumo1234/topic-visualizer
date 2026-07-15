# topic-visualizer 0.41.0 - Rob postmortem fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the eight defects Rob's 0.40.1 install postmortem surfaced so the next stranger gets a working install without becoming the QA, then ship 0.41.0.

**Architecture:** The root cause across all eight is "hardened against the author's machine, and the doctor inherited the same blind spot." Fixes fall in three layers: (1) make the install self-complete and the doctor tell the truth about persistence; (2) make login-time failure visible (logs) and robust (health-checked idempotency, clean-machine embedder venv); (3) reduce onboarding/environment friction (non-blocking sweep hook, installed-but-unset nudge, Asana disambiguation). No new core dependencies - the core stays stdlib-only; `sentence-transformers` remains optional and now lives in its own venv.

**Tech Stack:** Python 3.13 stdlib (http.server, sqlite3, subprocess, argparse), Windows Startup-folder VBS autostart (primary) + user-scope launchd/systemd (unix), Claude Code plugin hooks (SessionStart/Stop), MCP tools.

## Global Constraints

- ASCII-only, no em-dashes, in every file touched (the seven prose-punctuation chars stay out of code and docs).
- Core plugin stays stdlib-only. `sentence-transformers`/torch remain OPTIONAL and must never be imported by server.py, mcp_tools.py, or any hook.
- No elevation, ever. No `schtasks /Create`, no admin prompt. Windows persistence stays a user Startup-folder VBS.
- Cross-platform: Windows is primary; every change keeps the macOS/Linux path working (or is Windows-guarded).
- Version lives in THREE lockstep fields - bump all three to `0.41.0`: `.claude-plugin/marketplace.json` (`version`), `plugin/.claude-plugin/plugin.json` (`version`), `plugin/server/server.py` (`VERSION`).
- Commits: single-line subject, authored under the owner's git identity, NO `Co-Authored-By` trailer (topic-visualizer delegation convention).
- The doctor's degraded messages are the diagnostic spine - keep their shape: symptom, consequence, exact fix command.
- Never touch the user's data (`~/.topic-visualizer` topic stores). Only teardown removes data.
- TEST CONVENTION (overrides the per-task snippets' FORM): this plugin has NO pytest and no pytest config. Its tests are self-contained `unittest.TestCase` scripts under `plugin/server/` (e.g. `test_server.py`, `test_mcp.py`), each runnable via plain `python test_x.py` with an `if __name__ == "__main__": unittest.main(verbosity=2)` footer. Do NOT add pytest or a `tests/` dir. The test CODE BLOCKS shown inside each task specify the ASSERTIONS to make and the RED/GREEN behaviour to prove - translate them into `unittest.TestCase` methods in a new `plugin/server/test_<area>.py` (or add to an existing server/test file), using `self.assertEqual`/`self.assertIn`/`self.assertFalse` etc. and `unittest`-style setUp/env handling instead of pytest fixtures/`monkeypatch`. The assertion logic is what matters, not the framework. Run tests with `cd plugin/server && python test_<area>.py`.

---

### Task 1: Installer self-starts via its own launcher (Issue 1)

Kills the defect that shipped a false "done": the skill told the agent to run `server.py` directly, spawning a session child that dies with the terminal. Make `install_service.py` start the visualizer through the SAME detached launcher that login uses, and rewrite the skill so no agent ever runs `server.py` by hand.

**Files:**
- Modify: `plugin/server/install_service.py` (`install()` ~139-166, `main()` ~218-225)
- Modify: `plugin/skills/topics-setup/SKILL.md` (Step 1, lines ~42-43)
- Test: `plugin/tests/test_install_start.py` (create)

**Interfaces:**
- Consumes: `LAUNCHER` (`~/.topic-visualizer/tv-autostart.py`), `_pythonw()`, `_detached`-style flags (mirror `tv_autostart._detached()`).
- Produces: `install(..., start=True)` and `main()` emit `"started": <bool>` in the installed JSON; a `--no-start` flag to opt out (dry-run never starts).

- [ ] **Step 1: Write the failing test**

```python
# plugin/tests/test_install_start.py
import json, subprocess, sys
from pathlib import Path

INSTALLER = Path(__file__).resolve().parent.parent / "server" / "install_service.py"

def test_dry_run_reports_started_key_and_starts_nothing():
    out = subprocess.run([sys.executable, str(INSTALLER), "--dry-run"],
                         capture_output=True, text=True)
    line = [l for l in out.stdout.splitlines() if l.strip().startswith("{")][-1]
    data = json.loads(line)
    assert "started" in data            # the JSON contract now carries it
    assert data["started"] is False     # dry-run must never launch a process
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugin && python -m pytest tests/test_install_start.py -v`
Expected: FAIL with `KeyError: 'started'` (the key does not exist yet).

- [ ] **Step 3: Implement - start via the launcher after a successful install**

In `install_service.py`, add a helper and wire it into `install()` + `main()`:

```python
def _start_via_launcher() -> bool:
    """Start the visualizer the SAME detached way login does - via the launcher, never server.py
    directly (a directly-spawned server is a child of THIS process and dies with it). Idempotent:
    the launcher skips a port already serving. Best-effort; returns whether we launched it."""
    if not LAUNCHER.exists():
        return False
    flags = ({"creationflags": 0x00000008 | 0x00000200} if os.name == "nt"
             else {"start_new_session": True})
    try:
        subprocess.Popen([_pythonw(), str(LAUNCHER)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
        return True
    except Exception:
        return False
```

Change `install()` to accept `start` and return whether it started (thread it through the Windows and unix return points). Simplest: keep `install()`'s signature returning `(rc, autostart)` and do the start in `main()` after `rc == 0`:

```python
    rc, autostart = install(args.port, args.embedder, args.embed_port, args.dry_run)
    if rc == 0:
        started = False
        if not args.dry_run and not args.no_start:
            started = _start_via_launcher()
        print(json.dumps({"installed": True, "autostart": autostart, "launcher": str(LAUNCHER),
                          "started": started, "no_admin": True, "self_healing": True,
                          "upgrade_aware": True, "dry_run": args.dry_run}))
    else:
        print(json.dumps({"installed": False, "started": False, "dry_run": args.dry_run}))
        sys.exit(rc)
```

Add the flag in `main()`'s argparse:

```python
    ap.add_argument("--no-start", action="store_true",
                    help="install autostart but do not launch the server now")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugin && python -m pytest tests/test_install_start.py -v`
Expected: PASS.

- [ ] **Step 5: Rewrite the skill's Step 1 so no agent runs server.py directly**

In `skills/topics-setup/SKILL.md`, replace the "START the server now (`python ... server.py ...`)" instruction (lines ~42-43) with:

```markdown
The installer now STARTS the visualizer for you, detached, the same way login does - its JSON
output includes `"started": true`. Do NOT run `server.py` directly: a hand-started server is a
child of your session and dies when the terminal closes (it will look fine to `topic_doctor` for
this session, then vanish). If for any reason you must start it yourself, use the launcher, never
the server: `pythonw ~/.topic-visualizer/tv-autostart.py` (Windows: or `wscript` the Startup VBS).
Then confirm persistence with `topic_doctor` - it now tells detached from session-bound (Step 1a).
```

- [ ] **Step 6: Manual verification (Windows)**

Run: `python plugin/server/install_service.py --dry-run` and confirm the JSON has `"started": false`.
Run the real installer in a scratch shell, confirm JSON `"started": true`, then CLOSE that shell and from a NEW shell confirm the server still answers (`curl http://127.0.0.1:8991/api/version`).

- [ ] **Step 7: Commit**

```bash
git add plugin/server/install_service.py plugin/skills/topics-setup/SKILL.md plugin/tests/test_install_start.py
git commit -m "fix(install): installer self-starts via the detached launcher; skill never runs server.py directly (postmortem issue 1)"
```

---

### Task 2: Doctor distinguishes detached from session-bound "running" (Issue 2)

The load-bearing fix: `persistence == (server.running AND autostart_installed)` cannot tell a detached service from an ephemeral session child, so it green-lit a broken install. Have the launcher stamp the process it starts, the server report that stamp, and the doctor demand it.

**Files:**
- Modify: `plugin/server/tv_autostart.py` (`_detached()` / the two `Popen` calls, ~70-115)
- Modify: `plugin/server/server.py` (`main()` ~1860, `doctor()` ~1660-1691)
- Modify: `plugin/server/mcp_tools.py` (`doctor()` persistence branch, ~138-153)
- Test: `plugin/tests/test_doctor_persistence.py` (create)

**Interfaces:**
- Produces: env var `TOPICS_LAUNCHED_BY` (values `"autostart"` when started by the launcher, else unset/`"manual"`); server `doctor()` dict gains `"launched_by": <str|None>`; mcp doctor persistence branch keys off it.
- Consumes: server's `/api/doctor` already flows into mcp `http_doctor` (mcp_tools.py ~129-132), so the new field arrives for free.

- [ ] **Step 1: Write the failing test**

```python
# plugin/tests/test_doctor_persistence.py
import os, importlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

def test_server_doctor_reports_launched_by(monkeypatch):
    monkeypatch.setenv("TOPICS_LAUNCHED_BY", "autostart")
    import server
    importlib.reload(server)
    d = server.doctor()
    assert d.get("launched_by") == "autostart"

def test_server_doctor_launched_by_defaults_none(monkeypatch):
    monkeypatch.delenv("TOPICS_LAUNCHED_BY", raising=False)
    import server
    importlib.reload(server)
    d = server.doctor()
    assert d.get("launched_by") in (None, "manual")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugin && python -m pytest tests/test_doctor_persistence.py -v`
Expected: FAIL (`launched_by` not in the doctor dict).

- [ ] **Step 3: Server reads and reports how it was launched**

In `server.py`, near the other module globals (by `VERSION`, ~29), add:

```python
LAUNCHED_BY = os.environ.get("TOPICS_LAUNCHED_BY") or "manual"  # "autostart" iff started by tv-autostart
```

In `doctor()` (~1675) add the field to the returned dict:

```python
        "version": VERSION,
        "launched_by": LAUNCHED_BY,   # "autostart" = detached login service; "manual" = a hand start
        "verdict": "ok" if not degraded else "degraded",
```

- [ ] **Step 4: Launcher stamps the processes it starts**

In `tv_autostart.py`, make `_detached()` carry an env that marks the child as autostarted, and pass it on both `Popen` calls:

```python
def _detached():
    env = {**os.environ, "TOPICS_LAUNCHED_BY": "autostart"}
    if os.name == "nt":
        return {"creationflags": 0x00000008 | 0x00000200,
                "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "env": env}
    return {"start_new_session": True,
            "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "env": env}
```

(The two `subprocess.Popen(...)` calls already spread `**_detached()`, so they inherit the env. `install_service._start_via_launcher()` from Task 1 goes THROUGH the launcher, so it too gets the stamp.)

- [ ] **Step 5: Doctor demands the stamp for a green persistence verdict**

In `mcp_tools.py` `doctor()`, replace the `if running and autostart:` branch (~138-146) with a three-way check that reads `launched_by` off the running server's HTTP doctor (`http_doctor`, already fetched at ~129-132):

```python
        launched_by = (http_doctor or {}).get("launched_by")
        if running and autostart and launched_by == "autostart":
            out["backend"] = "server (HTTP)"
            out["persistence"] = "ok"
        elif running and autostart and launched_by != "autostart":
            out["backend"] = "server (HTTP)"
            out["persistence"] = "degraded"
            degraded.append(
                "The server is RUNNING but as a hand-started/session-bound process (launched_by="
                f"{launched_by!r}) - it will NOT survive the shell that started it, even though a login "
                "autostart is installed. Restart it via the launcher so the DETACHED one takes over: "
                "pythonw ~/.topic-visualizer/tv-autostart.py (Windows: or wscript the Startup VBS).")
        elif running and not autostart:
            out["backend"] = "server (HTTP)"
            out["persistence"] = "degraded"
            degraded.append(
                "The server is running but NO login autostart is installed - it was started by hand and "
                "will NOT survive a restart. Run /topics-setup (or install_service.py) to persist it.")
        else:
            out["backend"] = "direct-sqlite fallback"
            out["persistence"] = "degraded"
            degraded.append(
                "The topics SERVER is not running: capture works via the sqlite fallback, but the "
                "visualizer (web UI) needs the server up, and nothing persists it across restarts. "
                "Start it - run the /topics-setup skill (it installs a no-admin login autostart for you).")
```

Note: an OLDER running server (pre-0.41.0) returns no `launched_by`; that reads as `!= "autostart"` and flags "restart it" - which is exactly right, because the version-coherence check (mcp_tools ~166) already tells them to restart a stale server. No false negative for a correctly-upgraded detached server.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd plugin && python -m pytest tests/test_doctor_persistence.py -v`
Expected: PASS.

- [ ] **Step 7: Integration proof (the exact postmortem scenario)**

Manually reproduce Rob's defect and confirm the doctor now catches it:
1. Install autostart (Task 1) so the detached server is up and `launched_by=autostart` -> `topic_doctor` persistence `ok`.
2. Hand-start a second server on a scratch port with NO stamp; point `TOPICS_SERVER_URL` at it; confirm `topic_doctor` now returns persistence `degraded` with the "session-bound" message.

- [ ] **Step 8: Commit**

```bash
git add plugin/server/tv_autostart.py plugin/server/server.py plugin/server/mcp_tools.py plugin/tests/test_doctor_persistence.py
git commit -m "fix(doctor): distinguish detached from session-bound 'running' via launched_by stamp; persistence no longer false-greens (postmortem issue 2)"
```

---

### Task 3: Autostarted processes get logs; doctor surfaces the last error (Issues 3-secondary, 4)

Every login-time failure is currently invisible (`stdout/stderr -> DEVNULL`). Redirect each detached process to a small rotating log, and have the doctor tail the log when a component is unreachable.

**Files:**
- Modify: `plugin/server/tv_autostart.py` (`_detached()` from Task 2, `main()`)
- Modify: `plugin/server/mcp_tools.py` (`doctor()` - add a log-tail when a component is down)
- Test: `plugin/tests/test_autostart_logs.py` (create)

**Interfaces:**
- Produces: `~/.topic-visualizer/logs/server.log` and `embedder.log` (truncate-on-start); doctor adds `out["logs"]` = last error lines when `running` is False or semantic is off.

- [ ] **Step 1: Write the failing test**

```python
# plugin/tests/test_autostart_logs.py
import importlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

def test_logfile_helper_returns_paths(tmp_path, monkeypatch):
    import tv_autostart
    importlib.reload(tv_autostart)
    p = tv_autostart._logfile("server")
    assert p.name == "server.log"
    assert p.parent.name == "logs"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugin && python -m pytest tests/test_autostart_logs.py -v`
Expected: FAIL (`_logfile` not defined).

- [ ] **Step 3: Implement log redirection in the launcher**

In `tv_autostart.py`:

```python
LOGDIR = Path.home() / ".topic-visualizer" / "logs"

def _logfile(name):
    return LOGDIR / f"{name}.log"

def _detached(logname=None):
    env = {**os.environ, "TOPICS_LAUNCHED_BY": "autostart"}
    out = err = subprocess.DEVNULL
    if logname:
        try:
            LOGDIR.mkdir(parents=True, exist_ok=True)
            fh = open(_logfile(logname), "w", encoding="utf-8")  # truncate-on-start
            out = err = fh
        except Exception:
            out = err = subprocess.DEVNULL
    base = {"stdout": out, "stderr": err, "env": env}
    if os.name == "nt":
        base["creationflags"] = 0x00000008 | 0x00000200
    else:
        base["start_new_session"] = True
    return base
```

Update the two `Popen` calls in `main()` to name their logs: `**_detached("server")` and `**_detached("embedder")`.

- [ ] **Step 4: Doctor tails the log when a component is down**

In `mcp_tools.py` `doctor()`, before `out["degraded"] = degraded` (~187), add:

```python
        logdir = Path.home() / ".topic-visualizer" / "logs"
        def _tail(name, n=8):
            p = logdir / name
            try:
                return [l for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()][-n:]
            except Exception:
                return []
        logs = {}
        if not running:
            t = _tail("server.log")
            if t: logs["server"] = t
        if "Semantic ranking is OFF" in " ".join(degraded):
            t = _tail("embedder.log")
            if t: logs["embedder"] = t
        if logs:
            out["logs"] = logs
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd plugin && python -m pytest tests/test_autostart_logs.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugin/server/tv_autostart.py plugin/server/mcp_tools.py plugin/tests/test_autostart_logs.py
git commit -m "fix(autostart): log detached processes to ~/.topic-visualizer/logs; doctor tails them when a component is down (postmortem issues 3,4)"
```

---

### Task 4: Sweep hook is advisory, not a blocking "error" (Issue 5)

The Stop hook emits `{"decision": "block"}` unconditionally, which surfaces as a "Stop hook blocking error" and reads as a hang ("are you hung or finishing"). It fires this way even when nothing is capturable. Make "nothing to plant" produce silence; keep the one-per-session, no-loop guards.

**Files:**
- Modify: `plugin/hooks/sweep_reminder.py`
- Test: `plugin/tests/test_sweep_reminder.py` (create)

**Interfaces:**
- Produces: the hook still blocks ONCE per session to run the sweep contract (that is the only model-visible channel for Stop), but when a capture already happened this session it exits 0 silently (existing behavior), and it never re-fires (existing stamp + `stop_hook_active` guards). The change: the reason text stops reading as an error, and a new env opt-out (`TOPICS_SWEEP_HOOK=off`) makes it fully silent for users who do not want it.

- [ ] **Step 1: Write the failing test**

```python
# plugin/tests/test_sweep_reminder.py
import json, subprocess, sys
from pathlib import Path
HOOK = Path(__file__).resolve().parent.parent / "hooks" / "sweep_reminder.py"

def _run(payload, env=None):
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env)

def test_opt_out_is_silent(tmp_path, monkeypatch):
    import os
    env = {**os.environ, "TOPICS_SWEEP_HOOK": "off"}
    r = _run({"session_id": "s-optout"}, env=env)
    assert r.stdout.strip() == ""       # no block, no output
    assert r.returncode == 0

def test_already_stamped_is_silent():
    # second call with the same session id must stay silent (one sweep per session)
    _run({"session_id": "s-dup-xyz"})
    r = _run({"session_id": "s-dup-xyz"})
    assert r.stdout.strip() == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugin && python -m pytest tests/test_sweep_reminder.py -v`
Expected: FAIL on `test_opt_out_is_silent` (no opt-out exists yet).

- [ ] **Step 3: Implement the opt-out and soften the reason**

At the top of `sweep_reminder.py` after the payload parse, add the opt-out:

```python
import os
if os.environ.get("TOPICS_SWEEP_HOOK", "").lower() in ("off", "0", "false"):
    sys.exit(0)
```

Change the final `print` reason so it reads as a routine checkpoint, not an error:

```python
print(json.dumps({
    "decision": "block",
    "reason": ("Topic sweep checkpoint (routine, once per session - not an error): if any "
               "topic-worthy thread surfaced this session and was not captured, plant it now with "
               "topic_add (batch; enters as a seedling) and note it in one soft line. If nothing "
               "surfaced, just finish - a one-line 'nothing to plant' is the expected, correct ending."),
}))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugin && python -m pytest tests/test_sweep_reminder.py -v`
Expected: PASS.

- [ ] **Step 5: Document the opt-out** in `skills/topics-setup/SKILL.md` final-notes section: one line - "The session-end sweep is a routine checkpoint; set `TOPICS_SWEEP_HOOK=off` to silence it entirely."

- [ ] **Step 6: Commit**

```bash
git add plugin/hooks/sweep_reminder.py plugin/tests/test_sweep_reminder.py plugin/skills/topics-setup/SKILL.md
git commit -m "fix(hooks): sweep reminder reads as a routine checkpoint, not a blocking error; add TOPICS_SWEEP_HOOK=off opt-out (postmortem issue 5)"
```

---

### Task 5: Installed-but-not-set-up nudge (Issue 6)

Out of the box, capture works but the visualizer + semantic ranking are dead until someone runs `/topics-setup`, and nothing prompts it. Add a once-per-day SessionStart line when a store exists but autostart is not installed. Fold this into the existing `first_of_day.py` (it is already a SessionStart hook and already fails silent).

**Files:**
- Modify: `plugin/hooks/first_of_day.py`
- Test: `plugin/tests/test_first_of_day_nudge.py` (create)

**Interfaces:**
- Consumes: `_autostart_installed`-equivalent check (read `~/.topic-visualizer/tv-autostart.json` artifacts, mirror mcp_tools `_autostart_installed`); store-exists check (already computed in `_serve`).
- Produces: when a store exists AND autostart is NOT installed AND not already nudged today, emit one `additionalContext` line pointing at `/topics-setup`. The first-of-day CARD still takes priority when both apply (card first; nudge only if no card served).

- [ ] **Step 1: Write the failing test**

```python
# plugin/tests/test_first_of_day_nudge.py
import importlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

def test_autostart_check_false_when_no_config(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    import first_of_day
    importlib.reload(first_of_day)
    assert first_of_day._autostart_installed() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugin && python -m pytest tests/test_first_of_day_nudge.py -v`
Expected: FAIL (`_autostart_installed` not defined in first_of_day).

- [ ] **Step 3: Implement the check + nudge**

In `first_of_day.py` add (mirroring mcp_tools, kept stdlib-only):

```python
NUDGE_STAMP = Path.home() / ".topic-visualizer-last-nudged"

def _autostart_installed() -> bool:
    cfgp = Path.home() / ".topic-visualizer" / "tv-autostart.json"
    if not cfgp.exists():
        return False
    try:
        c = json.loads(cfgp.read_text(encoding="utf-8"))
    except Exception:
        return False
    arts = c.get("artifacts", [])
    if arts:
        return any(Path(a).exists() for a in arts)
    return (Path.home() / ".topic-visualizer" / "tv-autostart.py").exists()

def _store_exists() -> bool:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
        import server as srv
        srv.DB_PATH = srv.DEFAULT_DB
        proj = os.environ.get("TOPICS_PROJECT") or srv.project_key_from_cwd()
        db = os.environ.get("TOPICS_DB") or srv.project_db_path(proj)
        return Path(db).exists()
    except Exception:
        return False
```

In the main try-block, after the card logic, add the nudge as a fallback (only if no card was served this call):

```python
    # installed-but-not-set-up nudge: capturing works, but visualizer + semantic ranking are dark
    # until /topics-setup runs. Once per day, and never when autostart is already installed.
    if not _autostart_installed() and _store_exists():
        if not (NUDGE_STAMP.exists() and NUDGE_STAMP.read_text().strip() == today):
            NUDGE_STAMP.write_text(today)
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext":
                    "topic-visualizer is CAPTURING, but the visualizer web UI and semantic ranking "
                    "are not set up yet (they need a persistent local server). Run /topics-setup once "
                    "to finish - it is no-admin and reversible."}}))
```

Ensure this runs only when `card` was falsy (guard: put it in an `if not card:` block so a served card is not doubled up).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugin && python -m pytest tests/test_first_of_day_nudge.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugin/hooks/first_of_day.py plugin/tests/test_first_of_day_nudge.py
git commit -m "fix(onboarding): once-a-day SessionStart nudge when captured-but-not-set-up (postmortem issue 6)"
```

---

### Task 6: Disambiguate topics from Asana / task trackers (Issue 7)

In a multi-plugin environment an agent conflates "capture this" / "convert to work" with Asana's "create a task" (opaque UUID MCP namespace, task-flavored vocabulary, underspecified conversion exit). Fix in the plugin's own skill text - cheap, no code.

**Files:**
- Modify: `plugin/skills/topics/SKILL.md`, `topics-capture/SKILL.md`, `topics-serve/SKILL.md`, `topics-setup/SKILL.md` (frontmatter `description` + body where noted)

**Interfaces:** none (documentation only).

- [ ] **Step 1: Add a disambiguation line to each skill description**

Append to the `description:` of `topics`, `topics-capture`, and `topics-serve` (keep ASCII, one clause):

```
 Topics are conversation seeds in the LOCAL topic tree (the topic_* MCP tools from the topic-visualizer server) - NOT project-management tasks; never route topic capture/list/serve to Asana, Jira, or any task tracker.
```

- [ ] **Step 2: Name the tool namespace in the skill bodies**

In `topics-capture` and `topics-serve`, where they instruct the agent to add/serve, name the tools explicitly: "use the `topic_add` / `topic_list` / `topic_serve` tools from the topic-visualizer MCP server (namespace `mcp__plugin_topic-visualizer_topics__*`), not a similarly-worded tool from another server."

- [ ] **Step 3: Specify the "converted to work" exit door in topics-serve**

In `topics-serve` where the lifecycle ends in "converted to work," add:

```markdown
"Converted to work" means the HUMAN takes it into their own work tracker. The skill records the
conversion with `topic_convert` (a local state change) - it does NOT create an external task in
Asana/Jira/Linear/etc. unless the human explicitly asks, and if they do, confirm WHICH tracker first.
```

- [ ] **Step 4: Defensive check in topics-setup Step 0**

In `topics-setup/SKILL.md` Step 0, add: "If the doctor call fails or the `topic_*` tools appear missing, verify you are calling `mcp__plugin_topic-visualizer_topics__*` - not a similarly-named tool from another server (e.g. an Asana connector under a UUID namespace) - before diagnosing anything."

- [ ] **Step 5: Commit**

```bash
git add plugin/skills/topics/SKILL.md plugin/skills/topics-capture/SKILL.md plugin/skills/topics-serve/SKILL.md plugin/skills/topics-setup/SKILL.md
git commit -m "fix(skills): disambiguate topics from Asana/task trackers; name the topic_* namespace; specify the convert-to-work exit (postmortem issue 7)"
```

---

### Task 7: Health-signature check before port-based idempotency skip (Issue 8)

`tv_autostart._port_open()` skips startup if ANYTHING listens on the port, so a foreign squatter silently suppresses the real server and the doctor may probe the impostor. Verify the listener is actually ours via a health signature before deciding "already running."

**Files:**
- Modify: `plugin/server/tv_autostart.py` (`_port_open` callers in `main()`)
- Modify: `plugin/server/server.py` (`/api/version` or `/api/doctor` already returns `version`; confirm a stable signature field)
- Test: `plugin/tests/test_launcher_health.py` (create)

**Interfaces:**
- Produces: `tv_autostart._ours(port)` -> bool (GET `http://127.0.0.1:<port>/api/version` returns JSON with a `version` key). `main()` starts the server when the port is free OR occupied-by-not-ours (and logs the squat).

- [ ] **Step 1: Write the failing test**

```python
# plugin/tests/test_launcher_health.py
import importlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

def test_ours_false_on_dead_port():
    import tv_autostart
    importlib.reload(tv_autostart)
    assert tv_autostart._ours(59999) is False   # nothing listening -> not ours
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugin && python -m pytest tests/test_launcher_health.py -v`
Expected: FAIL (`_ours` not defined).

- [ ] **Step 3: Implement the health-signature check**

In `tv_autostart.py`:

```python
import urllib.request

def _ours(port) -> bool:
    """True only if the listener on `port` answers our health signature (JSON with a version).
    A foreign squatter fails this, so we do NOT mistake it for our server."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/api/version", timeout=1) as r:
            return "version" in json.loads(r.read())
    except Exception:
        return False
```

In `main()`, change the guards from `if not _port_open(sport)` to:

```python
    if not _ours(sport):
        if _port_open(sport):
            try:
                LOGDIR.mkdir(parents=True, exist_ok=True)
                (_logfile("server")).write_text(
                    f"port {sport} is occupied by a NON-topic-visualizer process; not starting our "
                    "server (free the port, then re-run the launcher)\n", encoding="utf-8")
            except Exception:
                pass
        else:
            subprocess.Popen([pyw, server, "--port", str(sport)], **_detached("server"))
```

Apply the same `_ours(eport)` pattern to the embedder guard (the embedder answers `/v1/models` or a health path; use `_port_open` fallback there since it is an OpenAI-style server without `/api/version` - keep the embedder on `_port_open` but log a squat the same way). Keep it simple: only the SERVER gets the signature check; the embedder keeps `_port_open` (documented in a comment - the embedder has no plugin signature endpoint).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugin && python -m pytest tests/test_launcher_health.py -v`
Expected: PASS.

- [ ] **Step 5: Doctor surfaces the squat** - the log-tail from Task 3 already shows the squat line when `running` is False, so no extra doctor change is needed. Confirm by manual read.

- [ ] **Step 6: Commit**

```bash
git add plugin/server/tv_autostart.py plugin/tests/test_launcher_health.py
git commit -m "fix(autostart): health-signature check before the port idempotency skip; log a foreign squat (postmortem issue 8)"
```

---

### Task 8: Embedder gets its own venv + model pre-download (Issue 3) [SCOPE DECISION - see header]

The "bundled" embedder isn't bundled: `serve_embedder.py` imports `sentence-transformers` (pulls torch) from whatever Python runs it, and the model downloads ~80MB windowless at first login where failures are invisible. Create a dedicated venv at install time, install the embedder deps there, pre-download the model while the user is watching, and record that interpreter for the launcher.

**Files:**
- Modify: `plugin/server/install_service.py` (`install()` when `--embedder`; `_config()` to record `embed_python`)
- Modify: `plugin/server/tv_autostart.py` (`main()` embedder branch - use `cfg["embed_python"]` if present)
- Modify: `plugin/skills/topics-setup/SKILL.md` (Step 2 - the embedder now self-provisions)
- Test: `plugin/tests/test_embedder_venv.py` (create)

**Interfaces:**
- Produces: `~/.topic-visualizer/venv/` (created only with `--embedder`); config gains `"embed_python": <venv python path>`; launcher runs the embedder with `embed_python` when set, else falls back to `_pythonw()`.

- [ ] **Step 1: Write the failing test**

```python
# plugin/tests/test_embedder_venv.py
import importlib, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

def test_config_carries_embed_python_when_embedder(monkeypatch):
    import install_service
    importlib.reload(install_service)
    cfg = install_service._config(8991, embedder=True, embed_port=8082, artifacts=[],
                                  embed_python="/fake/venv/python")
    assert cfg["embed_python"] == "/fake/venv/python"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugin && python -m pytest tests/test_embedder_venv.py -v`
Expected: FAIL (`_config` takes no `embed_python`).

- [ ] **Step 3: Provision the venv at install time**

Add to `install_service.py`:

```python
VENV = HOME / "venv"

def _venv_python() -> Path:
    return VENV / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")

def _provision_embedder(dry) -> str | None:
    """Create a dedicated venv, install sentence-transformers, pre-download the model NOW (visible
    errors), and return the venv python. Returns None on failure (caller keeps the plugin working in
    keyword mode and reports it - never a silent half-install)."""
    if dry:
        print(f"DRY-RUN: create venv {VENV}; pip install sentence-transformers; pre-download all-MiniLM-L6-v2")
        return str(_venv_python())
    try:
        import venv as _v
        _v.EnvBuilder(with_pip=True).create(str(VENV))
        py = str(_venv_python())
        subprocess.run([py, "-m", "pip", "install", "-q", "sentence-transformers"], check=True)
        subprocess.run([py, "-c",
                        "from sentence_transformers import SentenceTransformer; "
                        "SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"], check=True)
        return py
    except Exception as e:
        print(json.dumps({"embedder_provisioned": False, "error": str(e)}))
        return None
```

Thread `embed_python` through `_config()` (new kw arg, add key `"embed_python": embed_python`) and call `_provision_embedder` inside `install()` when `embedder` is true, storing the result in the config.

- [ ] **Step 4: Launcher uses the venv python for the embedder**

In `tv_autostart.py` `main()` embedder branch:

```python
        embpy = cfg.get("embed_python") or pyw
        if emb and not _port_open(eport):
            subprocess.Popen([embpy, emb, "--port", str(eport)], **_detached("embedder"))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd plugin && python -m pytest tests/test_embedder_venv.py -v`
Expected: PASS.

- [ ] **Step 6: Update the setup skill Step 2** - the embedder now self-provisions a venv and pre-downloads the model during setup (errors visible), instead of pip-ing into the user's global interpreter at first login.

- [ ] **Step 7: Manual clean-machine-ish verification** - remove `~/.topic-visualizer/venv`, run `install_service.py --embedder --dry-run` then real; confirm the venv is created, the model pre-downloads with visible output, and `topic_doctor` shows semantic ranking on after the launcher starts the embedder.

- [ ] **Step 8: Commit**

```bash
git add plugin/server/install_service.py plugin/server/tv_autostart.py plugin/skills/topics-setup/SKILL.md plugin/tests/test_embedder_venv.py
git commit -m "fix(embedder): dedicated venv + model pre-download at install; launcher runs the embedder from it (postmortem issue 3)"
```

---

### Task 9: Version bump to 0.41.0 + changelog + release

**Files:**
- Modify: `.claude-plugin/marketplace.json` (`version`), `plugin/.claude-plugin/plugin.json` (`version`), `plugin/server/server.py` (`VERSION`)
- Modify: `CHANGELOG.md` or `ROADMAP.md` (whichever holds release notes; add a 0.41.0 section)

- [ ] **Step 1: Run the full test suite green**

Run: `cd plugin && python -m pytest tests/ -v`
Expected: all pass.

- [ ] **Step 2: Bump all three version fields to `0.41.0`** (exact strings, lockstep).

- [ ] **Step 3: Add the 0.41.0 changelog entry** - one line per postmortem issue fixed (1-8), crediting the field postmortem.

- [ ] **Step 4: Commit the release**

```bash
git add .claude-plugin/marketplace.json plugin/.claude-plugin/plugin.json plugin/server/server.py CHANGELOG.md
git commit -m "release: topic-visualizer 0.41.0 - eight postmortem fixes (install self-start, honest persistence doctor, autostart logs, clean-machine embedder venv, non-blocking sweep, setup nudge, Asana disambiguation, health-checked idempotency)"
```

- [ ] **Step 5: Push + remind the owner to `/plugin marketplace update topic-visualizer`** (a same-version content change does NOT re-pull; the bump is what ships it to consumers/caches).

---

### Task 10: Fable 5 regression audit of 0.41.0

Per the owner directive, once the fixes are in place, use Fable 5 to audit the new version for regressions BEFORE the owner treats it as shipped.

- [ ] **Step 1: Dispatch a Fable-5 review agent** over the full `0.40.1..HEAD` diff with a regression-hunting brief:

Dispatch (Agent tool, `model: fable`): "You are auditing topic-visualizer's 0.41.0 changes (diff `0.40.1..HEAD` in F:/writing/plugins/topic-visualizer) for REGRESSIONS, not style. For each of the eight fixes, ask: did it break a path that worked in 0.40.1? Specifically check: (a) the new `launched_by` persistence gate does not false-RED a correctly-installed detached server, and handles a pre-0.41.0 running server sanely; (b) `_detached()` now passing `env=` did not drop the Windows creationflags or break the unix path; (c) log file handles do not leak or crash the launcher when `~/.topic-visualizer/logs` is unwritable; (d) the sweep hook still fires its one-per-session sweep and never loops (`stop_hook_active` guard intact); (e) the first-of-day nudge cannot double with a served card and respects its daily stamp; (f) the embedder venv path degrades gracefully (returns None, keyword mode) when venv/pip/network fails, never a hard install failure; (g) `_ours()` health check cannot hang the launcher (timeouts set) and the embedder squat path still starts when free. Report each finding as file:line + the exact regression scenario + severity. Empty report = no regressions found."

- [ ] **Step 2: Triage Fable's findings.** Confirmed regressions -> fix + re-commit + re-run the suite. Verify each against the real code (an audit claim is not a confirmed bug until reproduced) before acting.

- [ ] **Step 3: Report to the owner** - the audit verdict (clean or the confirmed regressions and their fixes), so he can decide the release is truly shippable.

---

## Self-Review

**Spec coverage:** all 8 postmortem issues map to a task - Issue 1 -> Task 1; Issue 2 -> Task 2; Issues 3(secondary)+4 -> Task 3; Issue 5 -> Task 4; Issue 6 -> Task 5; Issue 7 -> Task 6; Issue 8 -> Task 7; Issue 3(embedder) -> Task 8. Release + audit -> Tasks 9-10. The postmortem's "what worked well" (doctor message shape, no-admin install, self-cleaning launcher, data separation) is preserved by the Global Constraints and by keeping every doctor `degraded` message in symptom/consequence/fix shape.

**Type consistency:** `TOPICS_LAUNCHED_BY` / `launched_by` used consistently across tv_autostart (sets it), server.doctor (reports it), mcp_tools.doctor (reads it). `_detached(logname=None)` gains its arg in Task 3 and every caller is updated there. `embed_python` config key defined in Task 8's `_config` and read in Task 8's launcher branch. `_ours(port)` defined and used in Task 7.

**Placeholder scan:** no TBDs; every code step carries real code; every test step has an exact command and expected result.

**Ordering note:** Tasks 1-2 are the load-bearing pair (kill the false "done"). 3-4 are cheap high-value. 5-7 are friction. 8 is the heavier clean-machine fix (see the open decision). 9-10 close the release. Tasks are independent enough to review individually; the only ordering constraint is Task 3's `_detached(logname=...)` builds on Task 2's `_detached()` env change - keep 2 before 3.
