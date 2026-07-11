#!/usr/bin/env python3
"""Stop / PreCompact hook: the capture sweep - the structural net for the two ways an
AI session dies (chosen and unchosen). Emits a sweep instruction as context; the
PreCompact form is the MORTALITY sweep (capture liberally - seedling expiry makes
over-capture cheap). Fails silent."""
import json, sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "stop"
MSG = {
    "stop": ("SESSION-END TOPIC SWEEP: before closing - any topic-worthy threads from "
             "this session not yet planted? Plant them now via topic_add (batch; they "
             "enter as seedlings). One soft line if you plant."),
    "precompact": ("PRE-COMPACTION MORTALITY SWEEP: context is about to be summarized "
                   "and unplanted ideas will be LOST. Capture liberally NOW via "
                   "topic_add (batch) - lower the bar deliberately; seedling expiry "
                   "makes over-capture cheap, lost ideas are not recoverable."),
}[MODE]
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "Stop" if MODE == "stop" else "PreCompact",
    "additionalContext": MSG}}))
