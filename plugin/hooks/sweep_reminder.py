#!/usr/bin/env python3
"""Stop hook: the session-end capture sweep (the structural net for the CHOSEN way a
session ends). Contract note (audit 2026-07-11): Stop hooks do NOT support
additionalContext - the only model-visible channel is {"decision": "block",
"reason": ...}, which asks the model to continue once with the reason in context.
So: fire ONCE per session (stamp file keyed by session_id), guard on
stop_hook_active so we can never loop, and keep the reason gentle - sweep if
needed, then finish.

(The PreCompact mortality sweep has NO model-visible hook channel at all; that
duty lives in the topics-capture skill's MORTALITY-AWARE THRESHOLD rule.)"""
import json
import sys
import tempfile
from pathlib import Path

try:
    payload = json.loads(sys.stdin.read() or "{}")
except Exception:
    payload = {}

# never loop: if this stop was already caused by a hook block, let it through
if payload.get("stop_hook_active"):
    sys.exit(0)

session = str(payload.get("session_id") or "unknown")
stamp = Path(tempfile.gettempdir()) / f"topic-visualizer-sweep-{session}"
if stamp.exists():
    sys.exit(0)                      # one sweep per session, not one per turn
try:
    stamp.write_text("swept")
except Exception:
    sys.exit(0)

# skip the reminder when a capture ALREADY happened this session - the nudge would be
# redundant (field feedback 0.6.0). Best-effort scan of the transcript tail; if it is
# unreadable, fall through to the reminder (a redundant nudge is net-positive vs a miss).
tpath = payload.get("transcript_path")
if tpath:
    try:
        if b'"topic_add"' in Path(tpath).read_bytes()[-262144:]:
            sys.exit(0)              # already captured -> stay quiet
    except Exception:
        pass

print(json.dumps({
    "decision": "block",
    "reason": ("SESSION-END TOPIC SWEEP (once per session): if any topic-worthy "
               "threads surfaced this session and were not planted, plant them now "
               "via topic_add (batch; they enter as seedlings) and mention it in one "
               "soft line. If there is nothing to plant, simply finish."),
}))
