#!/usr/bin/env python3
"""Self-healing login launcher for topic-visualizer.

install_service.py copies THIS file into ~/.topic-visualizer/ (outside the plugin, so it survives a
plugin uninstall) and points a single login task at it. At each login it reads its config and either:

  - plugin STILL PRESENT -> start the server (+ embedder), idempotent: skip anything already listening,
    so the visualizer persists across restarts without stacking processes; or
  - plugin GONE (uninstalled -> its server.py no longer exists) -> DELETE its own login task, its config,
    and itself, so a silent UI-uninstall leaves NO orphaned task. Claude Code runs no uninstall hook, so
    this is how the footprint cleans up after an uninstall nobody's agent witnessed.

The user's DATA (~/.topic-visualizer topics) is never touched here - that is removed only via the
topics-teardown skill, on explicit ask.
"""
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

CFG = Path.home() / ".topic-visualizer" / "tv-autostart.json"


def _pythonw():
    exe = Path(sys.executable)
    pw = exe.with_name("pythonw.exe")
    return str(pw if pw.exists() else exe)


def _port_open(port):
    """Something already listening? Then don't start a second one (idempotent re-run at every login)."""
    try:
        with socket.socket() as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", int(port))) == 0
    except Exception:
        return False


def _detached():
    if os.name == "nt":
        return {"creationflags": 0x00000008 | 0x00000200,   # DETACHED_PROCESS | NEW_PROCESS_GROUP
                "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    return {"start_new_session": True, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}


def _self_clean(cfg):
    """The plugin is gone: remove the login task(s) we own, then this launcher + its config."""
    if os.name == "nt":
        for tn in cfg.get("tasks", []):
            subprocess.run(["schtasks", "/Delete", "/TN", tn, "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # launchd/systemd self-removal is best-effort; topics-teardown covers those OSes explicitly.
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
    server = cfg.get("server")
    if not server or not os.path.exists(server):        # plugin uninstalled -> its script is gone
        _self_clean(cfg)
        return
    pyw = _pythonw()
    sport = cfg.get("server_port", 8991)
    if not _port_open(sport):
        subprocess.Popen([pyw, server, "--port", str(sport)], **_detached())
    emb = cfg.get("embedder")
    eport = cfg.get("embed_port", 8082)
    if emb and os.path.exists(emb) and not _port_open(eport):
        subprocess.Popen([pyw, emb, "--port", str(eport)], **_detached())


if __name__ == "__main__":
    main()
