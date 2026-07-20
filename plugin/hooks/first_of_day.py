#!/usr/bin/env python3
"""SessionStart hook: the first-of-day card (owner-ratified serving cadence).
Checks whether a card was already served today; if not, asks the local server for
ONE ranked card - falling back to DIRECT sqlite (same store as the MCP tools) when
no server is running, so the card works out of the box (audit 2026-07-11: it used
to silently require the optional server). Fails silent - the seam must never block
a session."""
import json, os, sys, time, urllib.request
from pathlib import Path

STAMP = Path.home() / ".topic-visualizer-last-served"
NUDGE_STAMP = Path.home() / ".topic-visualizer-last-nudged"


def _serve():
    """Returns (card, staleness_block_or_None). Both legs supply staleness so the 0.42
    reconcile nudge works in the out-of-box serverless configuration too - the field gap
    was precisely that nothing prompted a reconcile (review MED-2)."""
    url = os.environ.get("TOPICS_SERVER_URL", "http://127.0.0.1:8991").rstrip("/")
    try:
        with urllib.request.urlopen(url + "/api/topics/serve", timeout=2) as r:
            card = json.loads(r.read()).get("card")
        stale = None
        try:
            with urllib.request.urlopen(url + "/api/topics/health", timeout=2) as r:
                stale = json.loads(r.read()).get("staleness")
        except Exception:
            pass
        return card, stale
    except Exception:
        pass
    # direct-sqlite fallback: mirror mcp_tools.ServerBackend._fallback
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
        import server as srv
        # read the PER-PROJECT store (topics live in projects/<key>.db since 0.5.0, not the
        # legacy default store); anchor DB_PATH first so project_db_path resolves the home path
        srv.DB_PATH = srv.DEFAULT_DB
        proj = os.environ.get("TOPICS_PROJECT") or srv.project_key_from_cwd()
        db = os.environ.get("TOPICS_DB") or srv.project_db_path(proj)
        if not Path(db).exists():
            return None, None                 # nothing captured yet - stay silent (0.42 tuple contract)
        srv.DB_PATH = db
        srv._conn = srv.open_db(db)
        card = srv.serve_card("").get("card")
        stale = None
        try:
            stale = srv.health().get("staleness")
        except Exception:
            pass
        return card, stale
    except Exception:
        return None, None


def _autostart_installed() -> bool:
    """Is a login autostart actually installed? Mirrors mcp_tools._autostart_installed (read
    ~/.topic-visualizer/tv-autostart.json, check its artifacts, else the launcher file) - kept
    stdlib-only and self-contained here since this hook does not import mcp_tools."""
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
    if os.name == "nt":
        return (Path.home() / ".topic-visualizer" / "tv-autostart.py").exists()
    # posix: install only PRINTS the launchd/systemd unit - trust persistence only if the user
    # actually installed one of them
    return any(p.exists() for p in (
        Path.home() / "Library" / "LaunchAgents" / "com.topicvisualizer.plist",
        Path.home() / ".config" / "systemd" / "user" / "topic-visualizer.service"))


def _store_exists() -> bool:
    """Does the per-project topic store exist? Mirrors _serve()'s fallback db resolution
    (anchor DB_PATH, then project_key_from_cwd/TOPICS_PROJECT, then project_db_path)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
        import server as srv
        srv.DB_PATH = srv.DEFAULT_DB
        proj = os.environ.get("TOPICS_PROJECT") or srv.project_key_from_cwd()
        db = os.environ.get("TOPICS_DB") or srv.project_db_path(proj)
        return Path(db).exists()
    except Exception:
        return False


try:
    today = time.strftime("%Y-%m-%d")
    if STAMP.exists() and STAMP.read_text().strip() == today:
        sys.exit(0)
    card, st = _serve()
    if card:
        STAMP.write_text(today)
        ctx = ("FIRST-OF-DAY TOPIC CARD (skippable with a word; owner-ratified ritual): "
               + card["title"] + " -- " + card["body"][:400])
        # 0.42 proactive reconcile nudge: the field session's highest-value act was a
        # reconcile pass, and nothing prompted it. One line, only when the alarm trips.
        if st and st.get("warning"):
            ratio = st.get("served_to_live")
            ctx += (f" || STALENESS ALARM: {st.get('stale_open_count')} open topics "
                    f"un-engaged >{st.get('stale_threshold_days', 30)}d"
                    + (f", served:live {ratio}" if ratio is not None else "")
                    + " - the highest-value response is a reconcile pass against the "
                      "work tracker (skill: topics-tracker-reconcile). Offer it to the human.")
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": ctx}}))
    if not card:
        # installed-but-not-set-up nudge: capturing works, but the visualizer web UI and
        # semantic ranking are dark until /topics-setup runs. Once per day (own stamp, so
        # it never doubles up with a served card), and never when autostart is installed
        # or nothing has been captured yet.
        # opt-out: fully silent for users who do not want the setup nudge at all (the CARD
        # above is untouched - only this nudge is gated).
        if os.environ.get("TOPICS_NUDGE", "").strip().lower() in ("off", "0", "false"):
            sys.exit(0)
        if not _autostart_installed() and _store_exists():
            if not (NUDGE_STAMP.exists() and NUDGE_STAMP.read_text(encoding="utf-8").strip() == today):
                NUDGE_STAMP.write_text(today, encoding="utf-8")
                print(json.dumps({"hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext":
                        "topic-visualizer is CAPTURING, but the visualizer web UI and semantic "
                        "ranking are not set up yet (they need a persistent local server). Run "
                        "/topics-setup once to finish - it is no-admin and reversible."}}))
except Exception:
    pass
