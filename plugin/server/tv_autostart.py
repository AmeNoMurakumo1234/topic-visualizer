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
from pathlib import Path

CFG = Path.home() / ".topic-visualizer" / "tv-autostart.json"
_VER = re.compile(r"^\d+(?:\.\d+)*")


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


def _detached():
    if os.name == "nt":
        return {"creationflags": 0x00000008 | 0x00000200,
                "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    return {"start_new_session": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


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
    if not _port_open(sport):
        subprocess.Popen([pyw, server, "--port", str(sport)], **_detached())
    if cfg.get("embedder"):
        emb = _resolve(base, cfg.get("embed_leaf", "server/serve_embedder.py"), cfg.get("pinned_embedder"))
        eport = cfg.get("embed_port", 8082)
        if emb and not _port_open(eport):
            subprocess.Popen([pyw, emb, "--port", str(eport)], **_detached())


if __name__ == "__main__":
    main()
