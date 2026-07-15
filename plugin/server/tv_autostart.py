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
import urllib.request
from pathlib import Path

CFG = Path.home() / ".topic-visualizer" / "tv-autostart.json"
LOGDIR = Path.home() / ".topic-visualizer" / "logs"
_VER = re.compile(r"^\d+(?:\.\d+)*")


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
            return "version" in json.loads(r.read())
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
        base["creationflags"] = 0x00000008 | 0x00000200
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
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
    pyw = _pythonw()
    sport = cfg.get("server_port", 8991)
    if not _ours(sport):
        if _port_open(sport):
            # Someone is listening but didn't answer our /api/version signature -> a
            # foreign process squats the port. Do NOT start our server (the port is
            # taken); leave a note the doctor's log-tail (Task 3) will surface.
            try:
                LOGDIR.mkdir(parents=True, exist_ok=True)
                _logfile("server").write_text(
                    f"port {sport} is occupied by a NON-topic-visualizer process; not starting our "
                    "server (free the port, then re-run the launcher)\n", encoding="utf-8")
            except Exception:
                pass
        else:
            subprocess.Popen([pyw, server, "--port", str(sport)], **_detached("server"))
    if cfg.get("embedder"):
        emb = _resolve(base, cfg.get("embed_leaf", "server/serve_embedder.py"), cfg.get("pinned_embedder"))
        eport = cfg.get("embed_port", 8082)
        # The embedder is an OpenAI-style server with no plugin /api/version signature,
        # so it stays on the plain _port_open check (no way to tell "ours" from foreign).
        if emb and not _port_open(eport):
            subprocess.Popen([pyw, emb, "--port", str(eport)], **_detached("embedder"))


if __name__ == "__main__":
    main()
