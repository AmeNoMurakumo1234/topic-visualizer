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


def _serve():
    url = os.environ.get("TOPICS_SERVER_URL", "http://127.0.0.1:8991").rstrip("/")
    try:
        with urllib.request.urlopen(url + "/api/topics/serve", timeout=2) as r:
            return json.loads(r.read()).get("card")
    except Exception:
        pass
    # direct-sqlite fallback: mirror mcp_tools.ServerBackend._fallback
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
        import server as srv
        db = os.environ.get("TOPICS_DB") or str(
            Path(__file__).resolve().parent.parent / "server" / "topics.db")
        if not Path(db).exists():
            return None                       # nothing captured yet - stay silent
        srv._conn = srv.open_db(db)
        return srv.serve_card("").get("card")
    except Exception:
        return None


try:
    today = time.strftime("%Y-%m-%d")
    if STAMP.exists() and STAMP.read_text().strip() == today:
        sys.exit(0)
    card = _serve()
    if card:
        STAMP.write_text(today)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext":
                "FIRST-OF-DAY TOPIC CARD (skippable with a word; owner-ratified ritual): "
                + card["title"] + " -- " + card["body"][:400]}}))
except Exception:
    pass
