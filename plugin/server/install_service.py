#!/usr/bin/env python3
"""Install (or remove) a LOGIN autostart for the topic-visualizer server (+ optional bundled embedder),
so the visualizer PERSISTS across restarts instead of dying with the terminal - the persistence gap the
onboarding report named. Windows-first (a Scheduled Task); for macOS/Linux it prints a ready-to-use
launchd/systemd unit that you (or your agent) drop in - the "best-effort, your AI finishes it" path.

    python install_service.py                  # install: the server at logon (idempotent)
    python install_service.py --embedder        # also autostart the bundled CPU embedder
    python install_service.py --uninstall       # remove the task(s)/unit(s) this installed
    python install_service.py --dry-run         # print the exact commands; change NOTHING

Idempotent + safe to re-run every login: re-installing replaces the task, and the server itself
no-ops if its port is already served.
"""
import argparse
import json
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK_SERVER = "TopicVisualizerServer"
TASK_EMBED = "TopicVisualizerEmbedder"


def _pythonw() -> str:
    """Windowless python on Windows, so there is no console flash at every login; else this python."""
    exe = Path(sys.executable)
    pw = exe.with_name("pythonw.exe")
    return str(pw if pw.exists() else exe)


def _run(cmd, dry):
    printable = " ".join(f'"{c}"' if " " in c else c for c in cmd)
    if dry:
        print("DRY-RUN:", printable)
        return 0
    print("RUN:", printable)
    return subprocess.run(cmd).returncode


def _tr(argv) -> str:
    """One schtasks /TR command-line string with each token quoted."""
    return " ".join(f'"{a}"' for a in argv)


def windows(pieces, uninstall, dry) -> int:
    rc = 0
    for name, argv in pieces:
        if uninstall:
            rc |= _run(["schtasks", "/Delete", "/TN", name, "/F"], dry)
        else:
            rc |= _run(["schtasks", "/Create", "/SC", "ONLOGON", "/TN", name,
                        "/TR", _tr(argv), "/RL", "LIMITED", "/F"], dry)
    return rc


def unix_units(pieces):
    """Print a ready launchd (macOS) / systemd --user (Linux) unit per piece - best effort; the user's
    agent drops it in the right place and enables it. We do not write system files from here."""
    mac = platform.system() == "Darwin"
    for name, argv in pieces:
        prog = " ".join(argv)
        if mac:
            print(f"\n# ~/Library/LaunchAgents/com.topicvisualizer.{name}.plist  (then: launchctl load -w <plist>)")
            args_xml = "".join(f"\n    <string>{a}</string>" for a in argv)
            print('<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
                  f'\n  <key>Label</key><string>com.topicvisualizer.{name}</string>'
                  f'\n  <key>ProgramArguments</key><array>{args_xml}\n  </array>'
                  '\n  <key>RunAtLoad</key><true/>\n  <key>KeepAlive</key><true/>\n</dict></plist>')
        else:
            print(f"\n# ~/.config/systemd/user/{name}.service  (then: systemctl --user enable --now {name})")
            print(f"[Unit]\nDescription=topic-visualizer {name}\n\n[Service]\nExecStart={prog}\n"
                  f"Restart=on-failure\n\n[Install]\nWantedBy=default.target")


def main():
    ap = argparse.ArgumentParser(description="Autostart the topic-visualizer server (+ embedder)")
    ap.add_argument("--port", type=int, default=8991, help="server port")
    ap.add_argument("--embedder", action="store_true", help="also autostart the bundled CPU embedder")
    ap.add_argument("--embed-port", type=int, default=8082, help="embedder port")
    ap.add_argument("--uninstall", action="store_true", help="remove what this installed")
    ap.add_argument("--dry-run", action="store_true", help="print commands, change nothing")
    args = ap.parse_args()

    pyw = _pythonw()
    pieces = [(TASK_SERVER, [pyw, str(HERE / "server.py"), "--port", str(args.port)])]
    if args.embedder:
        pieces.append((TASK_EMBED, [pyw, str(HERE / "serve_embedder.py"), "--port", str(args.embed_port)]))

    if platform.system() == "Windows":
        rc = windows(pieces, args.uninstall, args.dry_run)
        print(json.dumps({"installed" if not args.uninstall else "removed":
                          [n for n, _ in pieces], "dry_run": args.dry_run, "returncode": rc}))
        sys.exit(rc)
    # macOS / Linux: best-effort - emit the unit(s) for the agent/user to place and enable
    if args.uninstall:
        print("On macOS/Linux, remove the unit(s) you installed (launchctl unload / systemctl --user disable).")
    else:
        print("Windows Scheduled Task is the automated path. On this OS, install the unit(s) below:")
        unix_units(pieces)


if __name__ == "__main__":
    main()
