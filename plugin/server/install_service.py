#!/usr/bin/env python3
"""Install (or remove) a SELF-HEALING login autostart for the topic-visualizer server (+ optional
bundled embedder), so the visualizer persists across restarts - AND cleans itself up if the plugin is
later uninstalled, since Claude Code runs no uninstall hook.

How it self-heals: instead of pointing the login task straight at the plugin's server.py (which a plugin
uninstall would orphan), we copy a tiny launcher (tv_autostart.py) into ~/.topic-visualizer/ - OUTSIDE
the plugin, so it survives - and point ONE login task at it. Each login the launcher starts the server
if the plugin is still there, or DELETES its own task + itself if the plugin is gone. So even a silent
UI-uninstall leaves no orphaned task.

    python install_service.py                  # install: self-healing login autostart (server only)
    python install_service.py --embedder        # also autostart the bundled CPU embedder
    python install_service.py --uninstall       # stop our processes + remove the task/launcher/config
    python install_service.py --stop            # stop our running processes only (no task change)
    python install_service.py --dry-run         # print everything; change NOTHING

Idempotent + safe to re-run. The user's DATA (~/.topic-visualizer topics) is never touched here - remove
it only via the topics-teardown skill, on explicit ask.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home() / ".topic-visualizer"
LAUNCHER = HOME / "tv-autostart.py"
CFG = HOME / "tv-autostart.json"
TASK = "TopicVisualizer"


def _pythonw() -> str:
    """Windowless python on Windows (no console flash at login); else this python."""
    exe = Path(sys.executable)
    pw = exe.with_name("pythonw.exe")
    return str(pw if pw.exists() else exe)


def _run(cmd, dry) -> int:
    printable = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    if dry:
        print("DRY-RUN:", printable)
        return 0
    print("RUN:", printable)
    return subprocess.run(cmd).returncode


def _tr(argv) -> str:
    """One schtasks /TR command-line string with each token quoted."""
    return " ".join(f'"{a}"' for a in argv)


def _our_script_paths():
    """The scripts our autostart runs. Stopping is matched to THESE full paths (see _stop_processes)."""
    return [str(HERE / "server.py"), str(HERE / "serve_embedder.py")]


def _stop_processes(dry) -> list:
    """Stop ONLY the python server/embedder WE started. SAFETY: match a process ONLY when it is a python
    process (name python*) whose command line runs one of OUR exact script paths - never a command line
    that merely MENTIONS the path (a shell/editor/this teardown would match that), and never by port (a
    shared/BYO embedder on 8082 must survive). Run teardown BEFORE deleting the plugin so paths still
    match the live command lines. Returns the pids acted on."""
    paths = _our_script_paths()
    if platform.system() == "Windows":
        conds = "(" + " -or ".join("$_.CommandLine -like '*" + p + "*'" for p in paths) + ")"
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and "
              "$_.ProcessId -ne " + str(os.getpid()) + " -and $_.CommandLine -and " + conds +
              " } | Select-Object -ExpandProperty ProcessId")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True)
            pids = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
        except Exception:
            pids = []
        for pid in pids:
            if dry:
                print(f"DRY-RUN: taskkill /PID {pid} /F  (python running our script)")
            else:
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return pids
    acted = []
    for p in paths:
        try:
            out = subprocess.run(["pgrep", "-f", p], capture_output=True, text=True)
            cands = [int(x) for x in out.stdout.split() if x.strip().isdigit()]
        except Exception:
            cands = []
        for pid in cands:
            if pid == os.getpid():
                continue
            comm = subprocess.run(["ps", "-p", str(pid), "-o", "comm="],
                                  capture_output=True, text=True).stdout.strip()
            if "python" not in comm.lower():
                continue
            if dry:
                print(f"DRY-RUN: kill {pid}  ({comm} running our script)")
            else:
                subprocess.run(["kill", str(pid)])
            acted.append(pid)
    return acted


def _config(server_port, embedder, embed_port) -> dict:
    return {"server": str(HERE / "server.py"), "server_port": server_port,
            "embedder": str(HERE / "serve_embedder.py") if embedder else None,
            "embed_port": embed_port, "tasks": [TASK]}


def _unix_unit(argv):
    """Print a ready launchd (macOS) / systemd --user (Linux) unit pointing at the launcher - best
    effort; the user's agent drops it in and enables it. The launcher still self-heals on those OSes."""
    prog = " ".join(argv)
    if platform.system() == "Darwin":
        args_xml = "".join(f"\n    <string>{a}</string>" for a in argv)
        print(f"\n# ~/Library/LaunchAgents/com.topicvisualizer.plist  (then: launchctl load -w <plist>)")
        print('<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
              '\n  <key>Label</key><string>com.topicvisualizer</string>'
              f'\n  <key>ProgramArguments</key><array>{args_xml}\n  </array>'
              '\n  <key>RunAtLoad</key><true/>\n</dict></plist>')
    else:
        print(f"\n# ~/.config/systemd/user/topic-visualizer.service  (then: systemctl --user enable --now topic-visualizer)")
        print(f"[Unit]\nDescription=topic-visualizer\n\n[Service]\nExecStart={prog}\n"
              f"Restart=on-failure\n\n[Install]\nWantedBy=default.target")


def install(cfg, dry) -> int:
    if dry:
        print(f"DRY-RUN: copy launcher -> {LAUNCHER}")
        print(f"DRY-RUN: write config  -> {CFG}: {json.dumps(cfg)}")
    else:
        HOME.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(HERE / "tv_autostart.py"), str(LAUNCHER))
        CFG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    launch = [_pythonw(), str(LAUNCHER)]
    if platform.system() == "Windows":
        return _run(["schtasks", "/Create", "/SC", "ONLOGON", "/TN", TASK,
                     "/TR", _tr(launch), "/RL", "LIMITED", "/F"], dry)
    print("Windows Scheduled Task is the automated path. On this OS, install the unit below:")
    _unix_unit(launch)
    return 0


def uninstall(dry) -> list:
    stopped = _stop_processes(dry)              # stop first, so nothing holds the DB lock / port
    if platform.system() == "Windows":
        _run(["schtasks", "/Delete", "/TN", TASK, "/F"], dry)
    else:
        print("On macOS/Linux, disable the unit you installed (launchctl unload / systemctl --user disable).")
    if dry:
        print(f"DRY-RUN: remove {LAUNCHER}")
        print(f"DRY-RUN: remove {CFG}")
    else:
        for p in (LAUNCHER, CFG):
            try:
                p.unlink()
            except Exception:
                pass
    return stopped


def main():
    ap = argparse.ArgumentParser(description="Self-healing autostart for the topic-visualizer server")
    ap.add_argument("--port", type=int, default=8991, help="server port")
    ap.add_argument("--embedder", action="store_true", help="also autostart the bundled CPU embedder")
    ap.add_argument("--embed-port", type=int, default=8082, help="embedder port")
    ap.add_argument("--uninstall", action="store_true",
                    help="STOP our processes AND remove the task + launcher + config (graceful teardown)")
    ap.add_argument("--stop", action="store_true",
                    help="stop the running server/embedder we started, without touching the autostart")
    ap.add_argument("--dry-run", action="store_true", help="print everything, change nothing")
    args = ap.parse_args()

    if args.stop:
        print(json.dumps({"stopped": _stop_processes(args.dry_run), "dry_run": args.dry_run}))
        return
    if args.uninstall:
        stopped = uninstall(args.dry_run)
        print(json.dumps({"removed": TASK, "launcher": str(LAUNCHER), "stopped": stopped,
                          "dry_run": args.dry_run}))
        return
    rc = install(_config(args.port, args.embedder, args.embed_port), args.dry_run)
    print(json.dumps({"installed": TASK, "launcher": str(LAUNCHER), "self_healing": True,
                      "dry_run": args.dry_run, "returncode": rc}))
    sys.exit(rc)


if __name__ == "__main__":
    main()
