---
name: topics-setup
description: Run ONCE to get topic-visualizer from "installed" to "fully working" - or any time topic_doctor reports degraded. Interactively walks the three real choices (persistence of the visualizer, semantic ranking, which project the store tracks), EXECUTES each one (writing the OS-specific service yourself), and ends on a green doctor summary. Trigger when the user says "set up topics", "topics setup", "finish setting up the visualizer", "why won't my visualizer stay running", "why is semantic ranking off", or whenever topic_doctor shows a non-empty degraded list. You (the agent) drive this end to end; the user only answers a few questions.
---

# topics-setup: from installed to actually working

Out of the box this plugin CAPTURES topics fine (the direct-sqlite fallback), but two things
silently do not work until someone sets them up: the **visualizer does not persist** (the web UI needs
a running server that survives a restart) and **semantic ranking is off** (no embedder is bundled). A
naive user never learns either. This skill closes that gap in one guided pass.

**Your job:** diagnose, then ask the user the few choices that are genuinely theirs, then DO the work
(you write the service, you launch the embedder) and confirm with the doctor. Ask - never impose. If a
choice is skipped, that is fine; just make sure the user KNOWS what they skipped.

## Step 0 - Diagnose first (always)

Call the **`topic_doctor`** MCP tool. It returns resolved config + live up/down and a `degraded` list.
Read it back to the user in plain language: what already works, and what is degraded. Everything below
is aimed at emptying that `degraded` list. Re-run it after each fix to show progress.

## Step 1 - Persistence: keep the visualizer running

If the doctor says the server is not running / not persistent, ask:

> "Want the topic visualizer to stay running across restarts? I can set it to launch automatically at
> login." [yes / no]

On **yes**, use the bundled installer (do not make the user hand-write a service):

- **Windows (primary target):** run `python "<PLUGIN>/server/install_service.py"` (resolve `<PLUGIN>`
  to this plugin's installed path; add `--embedder` if the user also set up the bundled embedder in
  Step 2). It writes a **no-admin**, windowless login autostart (a Startup-folder entry - no elevation
  needed, unlike a scheduled task) and is idempotent (uninstall with `--uninstall`). On the next login
  it auto-adopts the newest installed version, so plugin updates need no re-install.
- **macOS / Linux:** the same script, run on that OS, PRINTS a ready launchd plist / systemd `--user`
  unit. Place it and enable it (`launchctl load -w …` / `systemctl --user enable --now …`). This is the
  best-effort path - if you cannot fully wire it, hand the user the exact remaining command; do not
  pretend it is done.

The installer now STARTS the visualizer for you, detached, the same way login does - its JSON
output includes `"started": true`. Do NOT run `server.py` directly: a hand-started server is a
child of your session and dies when the terminal closes (it will look fine to `topic_doctor` for
this session, then vanish). If for any reason you must start it yourself, use the launcher, never
the server: `pythonw ~/.topic-visualizer/tv-autostart.py` (Windows: or `wscript` the Startup VBS).
Then confirm persistence with `topic_doctor` - it now tells detached from session-bound (Step 1a).

## Step 2 - Semantic ranking: the embedder

If the doctor says semantic ranking is OFF, ask:

> "Set up semantic ranking? It makes search, dedup, and serve much sharper. Options: (a) bundled CPU
> embedder - I start a small local one; (b) bring-your-own - point at an OpenAI-style /v1/embeddings
> endpoint you already run; (c) skip - stay in keyword mode." [a / b / c]

- **(a) bundled (recommended):** run the plugin's bundled embedder,
  `python "<PLUGIN>/server/serve_embedder.py"` (CPU, all-MiniLM-L6-v2, auto-downloads ~80MB once). If
  the user chose persistence in Step 1, add it to the SAME autostart so both come up at login. It needs
  `sentence-transformers` (`pip install sentence-transformers`); if that is missing it prints exactly
  that and exits - install it and retry, or fall back to (b)/(c).
- **(b) BYO:** set `TOPICS_EMBED_URL` to their endpoint (persist it in their environment, not just this
  shell) and verify the doctor now reports the embedder reachable.
- **(c) skip:** fine - but state plainly that search/dedup/serve will run keyword-only, and that the
  degraded banner will show in the web UI until an embedder is set.

## Step 3 - Project scope

Topics are stored **per project**, keyed from the working directory. Confirm the target with the user:

> "Topics will be tracked for the project `<detected key>` (from this directory). Right?"

If they want a different one, set `TOPICS_PROJECT` (persist it). The web view opens to whatever
`?project=` it is given and remembers the last pick, so no other wiring is needed.

## Step 4 - Finish on green (or an honest remainder)

Re-run **`topic_doctor`**. If `degraded` is now empty, tell the user they are fully set up and where the
visualizer lives (the server URL). If anything remains, list EXACTLY what is left and the one command to
finish it - never end on a silent partial. Offer to open the visualizer.

## Removing it later

If persistence was installed, mention once that it is cleanly reversible: running the **topics-teardown**
skill BEFORE uninstalling stops the processes and removes the autostart, so nothing is orphaned. We
onboard gracefully and we release gracefully.

## The bar

A user who does not understand the internals should be able to run this once and either be fully working
or told precisely what remains. Silent half-value is the failure this skill exists to prevent - so the
last thing you do is prove the state with the doctor, not assert it.

The session-end sweep is a routine checkpoint; set `TOPICS_SWEEP_HOOK=off` to silence it entirely.
