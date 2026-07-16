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
import time
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
    keyword mode and reports it - never a silent half-install).
    Note: a FAILED provision may still leave a partial venv on disk at VENV; the next --embedder
    run reuses/overwrites it rather than requiring a manual cleanup."""
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
        # human/log diagnostic only - no code reads "embedder_provisioned" back; only
        # embed_python (None here) is consulted downstream by the launcher.
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
    """Every path our server/embedder could be running from - the CURRENT code's dir, the deployed
    config's pinned paths, and EVERY version dir under the config's base (a server started before a
    plugin upgrade carries the OLD version dir on its command line; stop must match it too)."""
    paths = [str(HERE / "server.py"), str(HERE / "serve_embedder.py")]
    try:
        cfg = json.loads(CFG.read_text(encoding="utf-8"))
        for leaf_key, pin_key in (("server_leaf", "pinned_server"), ("embed_leaf", "pinned_embedder")):
            pin = cfg.get(pin_key)
            if pin:
                paths.append(str(pin))
            base, leaf = cfg.get("base"), cfg.get(leaf_key)
            if base and leaf:
                for d in Path(base).iterdir():
                    cand = d / leaf
                    if cand.exists():
                        paths.append(str(cand))
    except Exception:
        pass
    return list(dict.fromkeys(paths))     # dedupe, keep order


def _stop_processes(dry) -> list:
    """Stop ONLY the python server/embedder WE started - matched by our exact script paths AND process
    name (python*), never by port (a shared/BYO embedder survives) and never by a command line that
    merely MENTIONS the path (a shell/this teardown would match that). Returns the pids acted on."""
    paths = _our_script_paths()
    if platform.system() == "Windows":
        conds = "(" + " -or ".join(
            "$_.CommandLine.IndexOf('" + p.replace("'", "''") + "', [StringComparison]::OrdinalIgnoreCase) -ge 0"
            for p in paths) + ")"
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


def _server_answers(port) -> bool:
    """True when OUR server answers its health signature on `port` (JSON object with a version key)."""
    try:
        import urllib.request
        with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/api/version", timeout=1) as r:
            body = json.loads(r.read())
            return isinstance(body, dict) and "version" in body
    except Exception:
        return False


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
    embed_python = None
    if embedder:
        try:
            prev = json.loads(CFG.read_text(encoding="utf-8"))
            prior = prev.get("embed_python")
            if prior and Path(prior).exists():
                embed_python = prior          # venv already provisioned - reuse, don't re-download
        except Exception:
            pass
        if embed_python is None:
            embed_python = _provision_embedder(dry)
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


def _inherit_deployed(args):
    """Inherit settings from a previously deployed config when the corresponding CLI arg was left
    at its default: a plain re-run (no --embedder, default --port/--embed-port) must never silently
    tear down an embedder a previous install provisioned, nor reset custom ports back to defaults.
    An explicitly-passed non-default CLI value always wins; missing/corrupt config leaves the
    (default) args untouched."""
    if not args.embedder or args.port == 8991 or args.embed_port == 8082:
        try:
            prev = json.loads(CFG.read_text(encoding="utf-8"))
            if not args.embedder and prev.get("embedder"):
                args.embedder = True
            if args.port == 8991:
                args.port = int(prev.get("server_port", 8991))
            if args.embed_port == 8082:
                args.embed_port = int(prev.get("embed_port", 8082))
        except Exception:
            pass
    return args


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
    # Inherit deployed embedder flag + custom ports for any arg left at its default (see
    # _inherit_deployed docstring).
    args = _inherit_deployed(args)
    rc, autostart = install(args.port, args.embedder, args.embed_port, args.dry_run)
    if rc == 0:
        started = False
        if not args.dry_run and not args.no_start:
            _stop_processes(False)      # replace any old/unstamped running server so the refreshed,
            _start_via_launcher()       # stamped launcher's server takes over in one step
            # "started" must mean an actual takeover, not merely that we spawned the launcher -
            # poll for the server's health signature so a launch that silently failed (missing
            # launcher, crash on start, port fight) is reported honestly.
            for _ in range(10):
                time.sleep(0.5)
                if _server_answers(args.port):
                    break
            started = _server_answers(args.port)
        print(json.dumps({"installed": True, "autostart": autostart, "launcher": str(LAUNCHER),
                          "started": started, "no_admin": True, "self_healing": True,
                          "upgrade_aware": True, "dry_run": args.dry_run}))
    else:
        print(json.dumps({"installed": False, "started": False, "dry_run": args.dry_run}))
        sys.exit(rc)


if __name__ == "__main__":
    main()
