#!/usr/bin/env python3
"""Self-healing, upgrade-aware login launcher for topic-visualizer.

install_service.py copies THIS file into ~/.topic-visualizer/ (outside the plugin, so it survives a
plugin uninstall) and points ONE user-space login autostart at it. Each login it reads its config and:

  - RESOLVES THE NEWEST installed version at launch (not a pinned path): it globs the plugin BASE dir
    for the highest version dir that still contains server.py, and runs THAT. So a plugin UPGRADE is
    adopted on the next login with no re-install - and, crucially, "the plugin is gone" means NO version
    dir exists under the base at all (a true uninstall), never "this one pinned path vanished" (which an
    upgrade would trigger, mistaking an upgrade for an uninstall and deleting persistence).
  - plugin PRESENT  -> start the newest server (+ embedder), idempotent (skip a port already listening);
  - plugin GONE     -> DELETE the autostart artifact(s) it owns (a Startup .vbs and/or a Scheduled Task),
                       its config, and itself. Claude Code runs no uninstall hook, so this is how the
                       footprint cleans up after a silent uninstall.

The user's DATA (~/.topic-visualizer topics) is never touched here - removed only via topics-teardown.
"""
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CFG = Path.home() / ".topic-visualizer" / "tv-autostart.json"
LOGDIR = Path.home() / ".topic-visualizer" / "logs"
_VER = re.compile(r"^\d+(?:\.\d+)*")

# --- Windows console flags. Get these wrong and the user gets random flickering windows. ---
# CREATE_NO_WINDOW gives a CONSOLE-subsystem child its own hidden console, which its children
# then inherit. DETACHED_PROCESS (0x8) reads like the same intent and is the opposite: it
# leaves the child with NO console, so the first thing it spawns makes Windows ALLOCATE a
# visible one - a console that appears, takes keyboard focus, and vanishes. On a login-launched
# server that is a random flicker which eats keystrokes and drops fullscreen games.
# FIELD-MEASURED LIMIT (vm-dev-fyibos-newbot, 2026-08-11): a GUI-subsystem child (pythonw)
# IGNORES the flag - it has no console either way, and ITS console-subsystem children still
# allocate. So flagging the LAUNCH of a pythonw daemon protects nothing; what protects is every
# spawn site INSIDE the daemon carrying the flag itself, which is exactly what this repo does.
# This file is COPIED to ~/.topic-visualizer/ and must not import from the plugin, so the
# constants are repeated per module and test_no_console_flash.py scans the tree to keep them
# honest. Do not "simplify" this back to DETACHED_PROCESS.
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def _no_window():
    """Popen/run kwargs so an INCIDENTAL spawn never creates a console window.

    Console-aware on purpose: if this process HAS a console we pass nothing, so the child
    inherits it and an interactive run still shows its output. If we have none - the login
    launcher, an MCP host - we pass CREATE_NO_WINDOW so Windows does not allocate one.
    Empty off Windows, so it is safe to splat at every call site including POSIX-only ones,
    which is what stops the next spawn from being the one somebody forgot.
    """
    if os.name != "nt":
        return {}
    try:
        import ctypes
        if ctypes.windll.kernel32.GetConsoleWindow():
            return {}
    except Exception:
        pass
    return {"creationflags": CREATE_NO_WINDOW}


def _logfile(name):
    return LOGDIR / f"{name}.log"


def _ver_key(name):
    m = _VER.match(name or "")
    return tuple(int(x) for x in m.group(0).split(".")) if m else None


def _resolve(base, leaf, pinned):
    """Newest version dir under `base` that contains `leaf` (cache layout <base>/<version>/<leaf>); else
    the pinned absolute path if it still exists (non-versioned / source layout); else None = truly gone."""
    best = None
    try:
        for d in Path(base).iterdir():
            k = _ver_key(d.name)
            if k is not None and d.is_dir() and (d / leaf).exists():
                if best is None or k > best[0]:
                    best = (k, str(d / leaf))
    except Exception:
        pass
    if best:
        return best[1]
    if pinned and os.path.exists(pinned):
        return pinned
    return None


def _pythonw():
    exe = Path(sys.executable)
    pw = exe.with_name("pythonw.exe")
    return str(pw if pw.exists() else exe)


def _port_open(port):
    try:
        with socket.socket() as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:
        return False


def _ours(port) -> bool:
    """True only if the listener on `port` answers our health signature (JSON with a
    'version' key at /api/version). A foreign squatter fails this, so we never mistake
    it for our server. No exception ever escapes: a dead or non-conforming port is
    simply "not ours"."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/api/version", timeout=1) as r:
            body = json.loads(r.read())
            return isinstance(body, dict) and "version" in body
    except Exception:
        return False


def _detached(logname=None):
    """Kwargs for a detached Popen: DETACHED_PROCESS on Windows / new session on unix, the
    Task-2 TOPICS_LAUNCHED_BY stamp, and - when `logname` is given - stdout/stderr redirected
    to a truncate-on-start log under LOGDIR so a login-time crash is diagnosable instead of
    silently swallowed by DEVNULL. Opening the log is best-effort: an unwritable log dir falls
    back to DEVNULL rather than crashing the launcher."""
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
        # CREATE_NO_WINDOW, never DETACHED_PROCESS - see the constants at the top of this file.
        # The server and embedder we launch here BOTH spawn further processes, so a console-less
        # parent turns every one of those into a visible flicker. NEW_PROCESS_GROUP is kept so a
        # Ctrl+C in whatever started us does not travel down into the daemon.
        base["creationflags"] = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    else:
        base["start_new_session"] = True
    return base


def _self_clean(cfg):
    """The plugin is gone: remove the autostart artifact(s) we own, then this launcher + its config."""
    for art in cfg.get("artifacts", []):            # Startup .vbs files (and any other owned files)
        try:
            Path(art).unlink()
        except Exception:
            pass
    if os.name == "nt":
        for tn in cfg.get("tasks", []):             # legacy Scheduled Tasks (pre-VBS installs)
            subprocess.run(["schtasks", "/Delete", "/TN", tn, "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           **_no_window())   # runs at LOGIN from a console-less launcher
    for p in (CFG, Path(__file__).resolve()):
        try:
            p.unlink()
        except Exception:
            pass


def main():
    if not CFG.exists():
        return
    try:
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
    except Exception:
        return
    base = cfg.get("base")
    server = _resolve(base, cfg.get("server_leaf", "server/server.py"), cfg.get("pinned_server"))
    if not server:                                   # no version dir under base + no pinned path -> gone
        _self_clean(cfg)
        return

    # Adopt the newest launcher CODE too (not just the newest server) - without this the launcher
    # stays frozen on its install-time code and starts new servers unstamped. Best-effort; affects the
    # NEXT login (this process already loaded its own code).
    try:
        newest_launcher = _resolve(base, "server/tv_autostart.py", None)
        me = Path(__file__).resolve()
        if newest_launcher and Path(newest_launcher).resolve() != me:
            new_src = Path(newest_launcher).read_text(encoding="utf-8")
            if new_src != me.read_text(encoding="utf-8"):
                tmp = me.with_suffix(".py.new")
                tmp.write_text(new_src, encoding="utf-8")
                os.replace(str(tmp), str(me))   # atomic on same filesystem - never a torn launcher
    except Exception:
        pass

    pyw = _pythonw()
    sport = cfg.get("server_port", 8991)
    server_up = _ours(sport)
    if not server_up:
        time.sleep(0.3)                 # our own server can miss the 1s probe on a loaded machine at login
        server_up = _ours(sport)
    if not server_up:
        if _port_open(sport):
            # something is listening but did not answer our /api/version health check within the timeout;
            # do NOT start a second server on an occupied port. Note it for the doctor's log-tail.
            try:
                LOGDIR.mkdir(parents=True, exist_ok=True)
                _logfile("server").write_text(
                    f"port {sport} is in use but did not answer the topic-visualizer health check "
                    "(a foreign process may be squatting it, or our server was slow to respond); not "
                    "starting a second server\n", encoding="utf-8")
            except Exception:
                pass
        else:
            subprocess.Popen([pyw, server, "--port", str(sport)], **_detached("server"))
    if cfg.get("embedder"):
        emb = _resolve(base, cfg.get("embed_leaf", "server/serve_embedder.py"), cfg.get("pinned_embedder"))
        eport = cfg.get("embed_port", 8082)
        # Task 8: run the embedder from its OWN dedicated venv (sentence-transformers + torch
        # pre-installed, model pre-downloaded at install time) when install_service provisioned one;
        # else fall back to the same interpreter that runs this launcher (keyword mode only).
        embpy = cfg.get("embed_python") or pyw
        # The embedder is an OpenAI-style server with no plugin /api/version signature,
        # so it stays on the plain _port_open check (no way to tell "ours" from foreign).
        if emb and not _port_open(eport):
            subprocess.Popen([embpy, emb, "--port", str(eport)], **_detached("embedder"))


if __name__ == "__main__":
    main()
