# Topic Visualizer - Onboarding Overhaul (design + roadmap)

**Status:** COMPLETE (all 5 slices shipped, 0.11.0 -> 0.15.0), 2026-07-12. **Source:** the consumer field
report (the onboarding-cliff report) - a heavy user who already built the missing pieces consumer-side and
offered them back.
**Working model:** owner-shipped plugin (every commit under the owner's identity). Contributors stage
edits; the owner commits + pushes + bumps `version`; consumers pull via
`/plugin marketplace update topic-visualizer` (same-version content will NOT re-pull - the bump ships it).

## The problem, plainly

Out of the box, capture works (the zero-setup direct-sqlite fallback), but the plugin **silently runs at
a fraction of its value**:

- **The visualizer does not persist** - the namesake web UI needs a manual `server/server.py` kept alive
  by hand; close the terminal and it is gone. No surfaced "open the visualizer" affordance.
- **Semantic ranking is silently off** - the ranker defaults `TOPICS_EMBED_URL` to `:8082`, but the
  plugin ships nothing on that port, so search / dedup / serve-ranking quietly degrade to keyword mode.
- **No `doctor` / `config`** surfaces resolved paths, URLs, or up/down status, so a naive user never
  learns they are at half value.

The failure mode is not a crash - it is invisible half-function, and the working capture tools mask it.

**The bar:** a user who does not understand the internals can install the plugin, run ONE prompt, and
either have it fully working or be told exactly what is left.

## Target experience (tiered)

- **Tier 0 (out of the box):** capture works AND the product ANNOUNCES what is missing - nobody silently
  runs at half value.
- **Tier 1 (`/topics-setup`):** one guided prompt asks the few real choices and stands up persistence +
  a bundled embedder accordingly. Most users stop here with the full thing.
- **Tier 2 (advanced):** documented env vars for a BYO embedder, custom model, custom service.

## Design principles

1. **Portability by agent-delegation.** Do NOT ship a perfected cross-OS installer binary. The setup
   prompt is a *skill* that instructs the AGENT to write the right service for the detected OS (launchd /
   `systemd --user` / Scheduled Task). Plugin-native, cheap, and portable without a build matrix.
2. **Loud, never silent.** Every degraded state is surfaced at a place the USER sees (a web banner + a
   `doctor` line), not only in an agent-only call like `groom_report()`.
3. **Ask, do not impose.** Persistence and model choices are user-specific; the setup prompt ASKS them
   rather than defaulting them onto the user. "Optional" must not mean "invisible and absent."
4. **Reuse what is proven.** Generalize the consumer's already-working reference impls rather than invent:
   `messageboard/scripts/start-embedding.ps1` (CPU `/v1/embeddings` launcher) and
   `messageboard/scripts/setup-startup.ps1` (logon persistence task).

## Audience decision (owner-confirmed 2026-07-12)

**Windows-first.** Implement + verify the whole Windows path end-to-end (our consumers). A non-Windows
user gets **best-effort** scaffolding - the setup skill still runs and does what it can, then hands the
OS-specific remainder to THEIR agent to finish ("here is what is left; your AI can wire the launchd /
systemd service"). We do NOT carry a cross-OS build matrix. This forks only at Slices 3-4 (embedder +
service); Slice 1 and the live-refresh slice are audience-agnostic.

## The slices (build order)

Each slice is its own spec -> build -> owner-ship cycle. Dependencies noted.

### Slice 1 - `topics doctor` + loud degraded state   [DONE 0.11.0]
- **Goal:** one command/tool prints resolved paths, URLs, versions, and up/down status for every piece;
  the web UI shows a banner when the embedder is absent ("Semantic ranking OFF - no embedder at <url>;
  showing keyword results").
- **Why first:** cures the worst failure (silent half-value) immediately; audience-agnostic (no OS/model
  forks); becomes the green-check that `/topics-setup` ends on.
- **Files:** `server/mcp_tools.py` (expose a `doctor` result via MCP + a CLI entry), `web/` (banner off
  the existing `groom_report().embedder.status`), a `topics-doctor` skill wrapper.
- **Acceptance:** no embedder -> doctor reports RED + web shows the banner; board embedder up -> both
  green; resolved env (`TOPICS_EMBED_URL` / `TOPICS_ACTOR` / `TOPICS_PROJECT` / store path) printed.
- **Depends on:** nothing.

### Slice 2 - `/topics-setup` guided skill   [DONE 0.12.0]
- **Goal:** interactive - persistence? [y/n]; semantic [bundled / BYO url / skip]; project(s)
  [auto-detect + confirm] - executes each choice (delegating OS-specifics to the agent), ends on
  `doctor` green.
- **Files:** new `plugin/skills/topics-setup/SKILL.md`.
- **Depends on:** Slice 1 (the green-check) and Slice 3 (to actually stand up semantic); can ship earlier
  in a guide-with-manual-fallback form.

### Slice 3 - bundle the embedder (`topics serve-embedder`)   [DONE 0.13.0]
- **Goal:** a minimal CPU `/v1/embeddings` launcher around a small auto-downloaded model (or a wrapped
  llama.cpp embedding binary), exposed as `topics serve-embedder`. Keep `TOPICS_EMBED_URL` as the BYO
  escape hatch; STOP defaulting to a port we serve nothing on.
- **Carry the gotcha:** a `trust_remote_code` model needs live hub *metadata* calls, so a naive
  `HF_HUB_OFFLINE=1` hard-fails with `LocalEntryNotFound` - document + handle it.
- **Open decision (settle in this slice):** exact model + runtime (sentence-transformers CPU vs a
  llama.cpp gguf). Generalize `start-embedding.ps1`.
- **Depends on:** nothing hard; unblocks Slice 2's semantic path.

### Slice 4 - service installer + version coherence   [DONE 0.14.0]
- **Goal:** `topics install-service` (agent writes launchd / `systemd --user` / Scheduled Task;
  idempotent, uninstallable) to keep host + embedder alive across restarts; a `/version` endpoint; the
  MCP face warns when it and the HTTP backend are on different upgrade clocks.
- **Depends on:** Slice 3 (so persistence covers the embedder too).

### Slice 5 - surface the visualizer + the when-to-use reflex   [DONE 0.15.0]
- **Goal:** a first-class "open the visualizer" affordance (ensures the host is up, hands back the URL);
  ship the always-on discipline of *when* a passing thought becomes a topic as its own skill (or folded
  into `topics-capture`), so agents get the reflex out of the box, not just the tools.
- **Depends on:** Slice 4 (host-up guarantee) for the "open" affordance; the reflex skill is independent.

### Addendum - graceful teardown   [DONE 0.16.0]
Onboarding installs real persistence (autostart + server + embedder), so a naive plugin-delete orphans a
failing login Scheduled Task and a ghost process holding the port + DB lock. The mirror of setup:
`install_service.py --uninstall/--stop` STOPS only OUR python processes (matched by script path AND
process name - never by port, so a shared/BYO embedder survives; the naive command-line-substring match
was caught over-killing shells and fixed) and removes the autostart; a `topics-teardown` skill
orchestrates stop -> remove autostart -> ASK about the data store -> confirm clean, run BEFORE uninstall.
We onboard gracefully; we release gracefully.

## Sequencing rationale

1 is the foundation and the biggest immediate relief (kills the silent-half-value failure) with zero
risky choices. 2 is the headline but only fully executes once 1 + 3 exist. 3 unblocks real semantic and
is the heaviest (model/runtime choice). 4 and 5 are hardening and polish. Ship each slice on its own so
value lands continuously rather than in one big-bang release.
