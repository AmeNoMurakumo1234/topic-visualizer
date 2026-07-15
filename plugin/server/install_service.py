#!/usr/bin/env python3
"""Install (or remove) a SELF-HEALING, UPGRADE-AWARE, NO-ADMIN login autostart for the topic-visualizer
server (+ optional bundled embedder). Claude Code runs no install/uninstall/update hook, so this handles
persistence, upgrades, and cleanup on its own.

Windows (primary): writes a tiny `.vbs` into the user's own Startup folder - NO elevation needed
(schtasks /Create needs admin for a root task; the Startup VBS does not). It runs a launcher
(tv_autostart.py, copied to ~/.topic-visualizer/ so it survives a plugin delete) windowless at each
login. The launcher resolves the NEWEST installed plugin version at launch, so a plugin update is picked
up with no re-install, and cleans itself up if the plugin is truly gone. macOS/Linux: prints a
user-scope launchd/systemd unit (already admin-free).

    python install_service.py                  # install: no-admin login autostart (server only)
    python install_service.py --embedder        # also autostart the bundled CPU embedder
    python install_service.py --uninstall       # stop our processes + remove autostart/launcher/config
    python install_service.py --stop            # stop our running processes only
    python install_service.py --dry-run         # print everything; change NOTHING

The user's DATA (~/.topic-visualizer topics) is never touched here - removed only via topics-teardown.
"""
from __future__ import annotations

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
VENV = HOME / "venv"


def _pythonw() -> str:
    exe = Path(sys.executable)
    pw = exe.with_name("pythonw.exe")
    return str(pw if pw.exists() else exe)


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


def _startup_vbs() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return (Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            / "topic-visualizer.vbs")


def _vbs_content(pyw, launcher) -> str:
    # WScript.Shell.Run "<cmd>", 0 (hidden window), False (fire-and-forget). Each real quote is doubled
    # for the VBS string literal.
    cmd = f'"{pyw}" "{launcher}"'
    return f'CreateObject("WScript.Shell").Run "{cmd.replace(chr(34), chr(34) * 2)}", 0, False\r\n'


def _quiet(cmd):
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _our_script_paths():
    return [str(HERE / "server.py"), str(HERE / "serve_embedder.py")]


def _stop_processes(dry) -> list:
    """Stop ONLY the python server/embedder WE started - matched by our exact script paths AND process
    name (python*), never by port (a shared/BYO embedder survives) and never by a command line that
    merely MENTIONS the path (a shell/this teardown would match that). Returns the pids acted on."""
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
                _quiet(["taskkill", "/PID", str(pid), "/F"])
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
            print(f"DRY-RUN: kill {pid}" if dry else f"kill {pid}")
            if not dry:
                subprocess.run(["kill", str(pid)])
            acted.append(pid)
    return acted


def _config(server_port, embedder, embed_port, artifacts, embed_python=None) -> dict:
    """Store the plugin BASE dir (not a version-pinned leaf), so the launcher resolves NEWEST at run
    time. pinned_* is a fallback for a non-versioned (source) layout. artifacts = files we own and must
    remove on teardown (the Startup .vbs). embed_python = the dedicated embedder venv interpreter
    (Task 8), or None when provisioning wasn't run/failed - the launcher then falls back to pyw."""
    return {
        "base": str(HERE.parent.parent),
        "server_leaf": HERE.name + "/server.py",
        "embed_leaf": HERE.name + "/serve_embedder.py",
        "pinned_server": str(HERE / "server.py"),
        "pinned_embedder": str(HERE / "serve_embedder.py") if embedder else None,
        "server_port": server_port,
        "embedder": bool(embedder),
        "embed_port": embed_port,
        "embed_python": embed_python,
        "artifacts": artifacts,
        "tasks": [],                      # empty now (VBS default); legacy 0.17.0 installs used a task
    }


def _unix_unit(argv):
    prog = " ".join(argv)
    if platform.system() == "Darwin":
        args_xml = "".join(f"\n    <string>{a}</string>" for a in argv)
        print("\n# ~/Library/LaunchAgents/com.topicvisualizer.plist  (then: launchctl load -w <plist>)")
        print('<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>'
              '\n  <key>Label</key><string>com.topicvisualizer</string>'
              f'\n  <key>ProgramArguments</key><array>{args_xml}\n  </array>'
              '\n  <key>RunAtLoad</key><true/>\n</dict></plist>')
    else:
        print("\n# ~/.config/systemd/user/topic-visualizer.service  (systemctl --user enable --now topic-visualizer)")
        print(f"[Unit]\nDescription=topic-visualizer\n\n[Service]\nExecStart={prog}\n"
              f"Restart=on-failure\n\n[Install]\nWantedBy=default.target")


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


def install(server_port, embedder, embed_port, dry):
    win = platform.system() == "Windows"
    vbs = _startup_vbs() if win else None
    # Best-effort: a provisioning failure (no network, pip error, disk full, ...) must NEVER fail the
    # install. _provision_embedder catches everything internally and returns None on failure; the
    # plugin then simply runs in keyword mode (embed_python absent, launcher falls back to pyw).
    embed_python = _provision_embedder(dry) if embedder else None
    cfg = _config(server_port, embedder, embed_port, [str(vbs)] if vbs else [], embed_python=embed_python)
    if dry:
        print(f"DRY-RUN: copy launcher -> {LAUNCHER}")
        print(f"DRY-RUN: write config  -> {CFG}: {json.dumps(cfg)}")
    else:
        HOME.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(HERE / "tv_autostart.py"), str(LAUNCHER))
        CFG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    launch = [_pythonw(), str(LAUNCHER)]
    if win:
        content = _vbs_content(_pythonw(), str(LAUNCHER))
        if dry:
            print(f"DRY-RUN: write Startup VBS (no admin) -> {vbs}")
            print("         " + content.strip())
            return 0, str(vbs)
        try:
            vbs.parent.mkdir(parents=True, exist_ok=True)
            vbs.write_text(content, encoding="utf-8")
        except Exception as e:                       # C1: fail LOUDLY, never claim installed
            print(json.dumps({"error": f"could not write the login autostart at {vbs}: {e}"}))
            return 1, None
        return 0, str(vbs)
    print("On this OS the login autostart is user-scope (no admin). Install the unit below:")
    _unix_unit(launch)
    return 0, "unit (printed above)"


def uninstall(dry) -> list:
    stopped = _stop_processes(dry)                   # stop first, so nothing holds the DB lock / port
    arts, tasks = [], []
    try:
        c = json.loads(CFG.read_text(encoding="utf-8"))
        arts, tasks = c.get("artifacts", []), c.get("tasks", [])
    except Exception:
        if platform.system() == "Windows":
            arts = [str(_startup_vbs())]
    for a in arts:
        print(f"DRY-RUN: remove {a}" if dry else f"remove {a}")
        if not dry:
            try:
                Path(a).unlink()
            except Exception:
                pass
    if platform.system() == "Windows":               # legacy 0.17.0 installs used a Scheduled Task
        for tn in list(tasks) + ["TopicVisualizer"]:
            if dry:
                print(f"DRY-RUN: schtasks /Delete /TN {tn} /F  (legacy, if present)")
            else:
                _quiet(["schtasks", "/Delete", "/TN", tn, "/F"])
    for p in (LAUNCHER, CFG):
        print(f"DRY-RUN: remove {p}" if dry else f"remove {p}")
        if not dry:
            try:
                p.unlink()
            except Exception:
                pass
    return stopped


def main():
    ap = argparse.ArgumentParser(description="No-admin, self-healing, upgrade-aware autostart")
    ap.add_argument("--port", type=int, default=8991, help="server port")
    ap.add_argument("--embedder", action="store_true", help="also autostart the bundled CPU embedder")
    ap.add_argument("--embed-port", type=int, default=8082, help="embedder port")
    ap.add_argument("--uninstall", action="store_true",
                    help="STOP our processes AND remove the autostart + launcher + config")
    ap.add_argument("--stop", action="store_true", help="stop our running processes only")
    ap.add_argument("--dry-run", action="store_true", help="print everything, change nothing")
    ap.add_argument("--no-start", action="store_true",
                    help="install autostart but do not launch the server now")
    args = ap.parse_args()

    if args.stop:
        print(json.dumps({"stopped": _stop_processes(args.dry_run), "dry_run": args.dry_run}))
        return
    if args.uninstall:
        print(json.dumps({"removed": True, "stopped": uninstall(args.dry_run), "dry_run": args.dry_run}))
        return
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


if __name__ == "__main__":
    main()
