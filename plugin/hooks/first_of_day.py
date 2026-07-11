#!/usr/bin/env python3
"""SessionStart hook: the first-of-day card (owner-ratified serving cadence).
Checks whether a card was already served today; if not, asks the local server for
ONE ranked card and emits it as session context. Fails silent - the seam must never
block a session."""
import json, sys, time, urllib.request
from pathlib import Path

STAMP = Path.home() / ".topic-visualizer-last-served"
try:
    today = time.strftime("%Y-%m-%d")
    if STAMP.exists() and STAMP.read_text().strip() == today:
        sys.exit(0)
    with urllib.request.urlopen("http://127.0.0.1:8991/api/topics/serve", timeout=2) as r:
        card = json.loads(r.read()).get("card")
    if card:
        STAMP.write_text(today)
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext":
                "FIRST-OF-DAY TOPIC CARD (skippable with a word; owner-ratified ritual): "
                + card["title"] + " -- " + card["body"][:400]}}))
except Exception:
    pass
