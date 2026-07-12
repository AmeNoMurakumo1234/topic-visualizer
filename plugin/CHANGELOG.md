# Changelog

## 0.6.0 - 2026-07-11 - Grooming release: read/enumerate topics, in-place priority, honest signals

Field feedback from a full grooming session (41 topics bulk-imported from 5 sessions).
The blockers first:

- **`topic_get {slug}`** (NEW): full detail for one topic - title, body (the QUESTION),
  state, priority, tags, provenance, ALL parents + extra avenues with their notes,
  children, recorded conversions, and recent history. A groomer can finally read a body
  they didn't author before deciding convert/prune/keep (search returns only
  slug/score/state).
- **`topic_list`** (NEW): enumerate the whole store (compact rows: slug/title/state/
  priority/parent, paginated with a total). Inventorying 41 topics no longer needs a
  hand-unioned keyword sweep.
- **`topic_state` sets `priority`** in place (critical | normal) - so the groom's beacon
  audit can actually promote/demote an existing topic instead of re-planting it (which
  would orphan its edges/notes/history). `state` is now optional; pass either or both.
- **`topic_add` takes an `actor`** - pass a stable label so per-actor calibration learns
  from ~2 real authors instead of 4 free-text variants.
- **Near-duplicate + search results carry a `band`** (dup_likely | kin | weak) and `mode`
  beside the raw score, so a caller knows where "same territory, plant no twin" begins
  (keyword scores are unbounded; the bands are documented as heuristic there).
- **`health` / `groom_report` separate CURRENT state from the 30-day window**: a `by_state`
  snapshot (seedling/open/discussed/pruned/expired) + `converted_topics`, distinct from
  the `window` activity counts - so "live vs converted" is never ambiguous. Adds an
  `embedder` block (`{url, status: up|down|unknown}`) so a groomer KNOWS whether semantic
  ranking engaged (see README on pointing `TOPICS_EMBED_URL` at your local embedder).
- **Idempotent `topic_attach`**: re-attaching an existing avenue returns
  `{ok, already: true}` instead of an error, so a batch's results stay clean.
- **Readable slugs**: truncate on a WORD boundary (never `...-docume`) + a short content
  hash for stable uniqueness.
- **Docs**: where the store lives (`~/.topic-visualizer/projects/<key>.db`) and how to
  point the plugin at an existing local embedding endpoint.
- Fixed the stale MCP `serverInfo` version (was pinned at 0.4.2; now a single `VERSION`).

Not in this release (tracked): batch variants of state/attach/convert; `topic_export` /
`topic_import` for sharing a tree across a team; deriving `actor` automatically from a
stable session identity.

## 0.5.1 - 2026-07-11 - Worktree-aware project keys + Constellation captures in still mode

Two fixes from a consumer wiring 0.5.0 into a Claude Code repo (whose per-session cwd is
a throwaway git worktree at `<repo>/.claude/worktrees/<rand>`):

- PROJECT KEY = REPO ROOT, not the ephemeral worktree. `project_key_from_cwd()` now
  resolves cwd to the canonical git repo root (`git rev-parse --git-common-dir`, shared
  by every worktree of a repo), so all of a repo's sessions share ONE store instead of
  scattering into a new empty per-worktree store each session. `list_projects()` folds
  the `~/.claude/projects` worktree dirs (`<repokey>-claude-worktrees-<rand>`) back to one
  entry per repo, so the dropdown shows repos, not dozens of worktree folders.
  `encode_project_path()` now also replaces `.` (matching Claude's dir naming, so
  `.claude` -> `-claude` and derived keys line up with dropdown entries). `TOPICS_PROJECT`
  stays the manual override. The git call is windowless (CREATE_NO_WINDOW) and falls back
  to the raw cwd outside a repo.
- CONSTELLATION captures in still mode. Under `?still` / `prefers-reduced-motion` /
  `navigator.webdriver`, the force graph jumps straight to its settled layout (runs every
  physics tick synchronously, schedules NO animation frame), the label-reflow RAF runs
  once synchronously, SMIL is paused (`svg.pauseAnimations()`), and a catch-all
  `.reduced-motion * { animation:none; transition:none }` kills any remaining keyframe or
  transition. The page paints once and goes idle, so a headless viewer gets a clean frame
  on all three views (Constellation was the last that could hang).
- CLEAN PROJECT LABELS in the switcher dropdown. It showed the full encoded key
  (`C--NB-Disk-FyiBOS`); now it shows just the folder name (`FyiBOS`). The real name is
  read from the project's session transcript (the `~/.claude/projects` dir name is a lossy
  encoding), worktree-stripped, so hyphenated names survive intact (`quantum-concepts`
  stays `quantum-concepts`, not `concepts`). No drive/path leak.
- RESPONSIVE HEADER. It wraps cleanly onto extra rows when narrow instead of smushing;
  controls are grouped so related ones travel together - the project switcher + the three
  view toggles as one unit (the toggle trio never splits or clips), the
  search/add/archive/backdrop as another. The decorative subtitle drops on narrow screens
  so the title always has room. Host pages gain `.hgroup` wrappers (`#…` element ids
  unchanged - the shell still finds everything).

## 0.5.0 - 2026-07-11 - Per-project stores + a project switcher + screenshot-safe motion

- PER-PROJECT STORES: topics are scoped per PROJECT instead of one global tree. Each
  project gets its own SQLite file (`~/.topic-visualizer/projects/<key>.db`), and the
  current project AUTO-derives from the loaded session's working directory, encoded the
  same way Claude names `~/.claude/projects` (`F:\writing\business` ->
  `F--writing-business`). Existing single-store topics are preserved as the `default`
  project. Every route + MCP call is `?project=`-aware; connections are cached and pinned
  per-request under a reentrant lock (ThreadingHTTPServer-safe); seedling expiry sweeps
  every project. New `GET /api/projects` lists the projects the machine offers.
- PROJECT SWITCHER (web): a dropdown in the shell header, shown when the adapter reports
  the new OPTIONAL `projects()` capability (degrades gracefully - no capability, no
  dropdown). Picking a project re-scopes the tree. The adapter supplies the list, so
  nothing is hardcoded to a machine: the sqlite adapter offers the machine's Claude
  projects; a board adapter offers its board projects.
- SCREENSHOT-SAFE MOTION: perpetual animations (twinkles, meteor, the beacon pulse, the
  SMIL node pulses) never let the page idle, which hangs some screenshot pipelines. They
  now stop under `prefers-reduced-motion`, an automation browser (`navigator.webdriver`),
  or the deterministic `?still=1` (or `?static`) URL lever - append it for a clean shot
  on any tool. The full graph still renders; a beacon keeps its ring, it just stops
  pulsing.
- MACHINE-AGNOSTIC / DE-PERSONALIZED: no default hardcodes an author-specific project or
  agent - the board backend's project auto-derives from cwd and its author falls back to
  the generic actor; the worked example + prototypes carry placeholder identity.
- The adapter contract is now the **v0.5 surface**: adds the optional `projects()` method.

## 0.4.2 - 2026-07-11 - Consumer-friendly install (no machine paths, no env vars)

- INSTALL.md rewritten to install straight from GitHub as a marketplace
  (`claude plugin marketplace add AmeNoMurakumo1234/topic-visualizer` +
  `install topic-visualizer@topic-visualizer`) - CLI, slash, and declarative
  `.claude/settings.json` forms. No local machine paths; cloning is
  contributors-only.
- The default topics DB moved to a real, user-typeable home path
  `~/.topic-visualizer/topics.db` (created on first capture, survives updates) and
  is now the single default across the MCP tools, the server, and the first-of-day
  hook. Dropped the `${CLAUDE_PLUGIN_DATA}` env override from `.mcp.json` - that
  variable only exists inside Claude Code's own execution and is not something a
  consumer can use from their shell, so public docs never reference it. Running the
  viewer is now just `python <plugin>/server/server.py` (no args, no env).

## 0.4.1 - 2026-07-11 - The hardening: 3-lane audit, verified and fixed

A parallel adversarial audit (server/MCP, web, plugin-form/docs) followed by a
verify-and-fix pass. The load-bearing fixes:

- SERVER DATA INTEGRITY: error returns now ROLL BACK (a refused action used to
  leave uncommitted writes that rode out on the next unrelated commit); the prune
  cascade TOCTOU check runs BEFORE survivor promotion (a REFUSED prune used to
  permanently re-parent survivors); convert validates the whole link batch before
  writing any of it; slug mint+insert under one lock (concurrent-capture race);
  archived topics rejected as new parents; extra_parents joined to LIVE parents
  in the live view. Regression tests for all of it (13 server / 7 MCP).
- HTTP: top-level handler guard (malformed input -> JSON error, never a dropped
  connection), dict-body enforcement, content-length clamp, static-route
  precedence fix; GET /serve no longer graduates seedlings (resurface != touch).
- MCP: a valid-JSON non-object line (e.g. a JSON-RPC batch array) no longer kills
  the process; backend singleton (the per-call fallback leaked a sqlite connection
  and re-ran expiry every call); board convert reports honestly when the issue
  minted but the resolve failed (a blind retry used to mint duplicates); board
  captures default to seedling (skill parity); default DB path unified.
- WEB XSS: shared esc() now guards EVERY innerHTML interpolation - renderer
  labels, lineage cards + chip titles, star-chart crumbs, confirm dialog,
  datalists (titles are AI-authored conversation text; six raw sinks shipped).
- WEB correctness: primary-parent cycles from a hostile/corrupt store are cut at
  buildTree instead of hanging every view; the prune dialog sends the cascade the
  human SAW (the recomputed set was defeating the server's own TOCTOU guard) and
  server refusals now surface in the dialog; stale node objects re-resolve on
  select; adapter load failures show "could not reach the topics store"; Esc
  closes the confirm modal before the panel; label-rAF canceled on unmount; demo
  quick-add keeps settled constellation positions.
- HOOKS (contract fixes): Stop now uses the decision-block contract and fires
  ONCE per session with a loop guard (the old additionalContext emission was a
  silent no-op); the PreCompact hook is REMOVED - that event has no model-visible
  channel, so the mortality sweep lives in the topics-capture skill; the
  first-of-day card gained the direct-sqlite fallback (works with no server).
- DOCS trued to the code: server README rewritten from "not yet implemented" spec
  to the shipped surface; seam-design stamped historical; tool listings include
  topic_attach; versions aligned; skill claims hedged to backend reality.

## 0.4.0 - 2026-07-11 - Multi-parent DAG + the panel beauty pass

- MULTI-PARENT (owner insight: two conversations can lead to the same child topic).
  Topics form a DAG, never a duplicated subtree: topic.parent_id stays the PRIMARY
  parent (layout spine); new topic_parent table holds extra avenues (schema v3).
  attach/detach via POST /api/topics/{slug}/attach (full-DAG cycle guard) and the
  `topic_attach` MCP tool. Rediscovery ENRICHMENT: attaching appends a
  "[rediscovered <date> via <parent>]" note to the body + a rediscovered event -
  the topic accumulates later discoveries instead of fragmenting.
- SURVIVOR PRUNE LAW: pruning a branch SPARES any descendant reachable via a live
  avenue outside the pruned set - the surviving avenue is promoted to its primary
  parent. Mirrored client-side (core.pruneSet) so the confirm dialog says how many
  survive; server tests cover it.
- BOARD BACKEND: multiple "parent:" body lines = extra avenues at creation;
  attaching to an existing topic posts an "also-parent: <slug> | <note>" THREAD
  REPLY (post bodies are immutable through the board API - the thread becomes the
  discovery log); loads parse replies back out (message_count guards the fetch).
- WEB: cross-link edges (dashed violet) in Constellation (with a gentle force tug)
  and Star Chart; "N avenues" chip in Lineage; panel AVENUES IN section (jump to a
  parent, detach where the store allows, "+ add avenue" input).
- PANEL BEAUTY PASS: floating glass card inside <main> (never covers the header
  chrome), gradient title, state pills, boxed body, refined buttons, entrance
  animation. Esc closes the panel. Board page: "<- board" link moved to the far
  left. topics-capture skill teaches attach-not-twin.

## 0.3.0 - 2026-07-11 - Installable: MCP face, semantic ranking, archive + edit

- INSTALLABLE PLUGIN: the repo is its own marketplace (root .claude-plugin/
  marketplace.json -> ./plugin); plugin/ is now self-contained (server/ + web/ moved
  inside - an install copies only the plugin source dir). Both manifests pass
  `claude plugin validate`. INSTALL.md carries the real two-command flow.
- MCP FACE (server/mcp_tools.py, registered via .mcp.json): topic_add / topic_serve /
  topic_search / topic_state / topic_convert / topic_groom_report over stdio
  JSON-RPC. Two backends behind one contract: the plugin server (HTTP passthrough
  with a zero-setup DIRECT sqlite fallback at ${CLAUDE_PLUGIN_DATA}/topics.db when
  no server is running) and a message-board backend (topics as OPEN THREAD posts)
  where topic_convert(work_item) MINTS a real board issue - the EXPLORING -> ACTING
  crossing, live. 4/4 e2e tests over real stdio, including a board-sandbox lifecycle.
- SEMANTIC ranking everywhere ranking exists (search, write-time dedup, serve
  territory-fit): any OpenAI-style /v1/embeddings endpoint via TOPICS_EMBED_URL,
  graceful keyword fallback when absent. Store-agnostic ranking seams
  (near_duplicates_in / search_in / rank_candidates) shared by both MCP backends.
- ARCHIVE EXPLORER (web): header toggle shows pruned/expired topics as ghosts
  (dashed, struck-through, quiet); any archived topic is resurrectable from the
  panel. The past stays visitable - death by choice, never by deletion.
- PANEL EDIT (web): title / body / re-parent (cycle-guarded server-side) / beacon
  toggle, capability-detected per adapter (hidden where the store cannot edit).
- FIX: X-Requested-By anti-CSRF value for the board backend.

## 0.2.0 - 2026-07-11 - The Seam (design + working implementation)

- docs/2026-07-11-seam-design.md: the full ratified design (silent capture + soft
  report; first-of-day serving; seedlings w/ auto-expiry + archive + semantic search;
  hybrid mechanism-at-decay-points; mortality-aware capture).
- SERVER SHIPS (server/server.py, stdlib-only, 8/8 e2e tests): batch capture w/
  write-time near-duplicate detection, seedling->open touch graduation, serve ranking
  (beacons > territory > age-decay resurfacing), ranked search w/ keyword fallback,
  edit/re-parent w/ cycle guard, atomic conversion, TOCTOU-verified prune cascades,
  daily seedling expiry, seam-health + groom/calibration reports. Serves web/ static.
- WEB: search bar filters all three views (matches always labeled - search overrides
  the zoom budget; non-matches ghost to 13%), quick-add box, seedling visual state,
  seam-health strip. Verified live against the running server.
- SKILLS updated to the ratified policies; HOOKS scaffolded (SessionStart first-of-day
  card, Stop sweep, PreCompact mortality sweep) - validate on first real install.

## 0.1.0 - 2026-07-11 - Foundation

The repo's first real content, written the day after the prototype was born:

- README (the problem story + what it is), CHARTER (a garden, not an archive - the
  seven disciplines + the two-memory-architectures purpose statement).
- Plugin manifest + three skills: `topics-capture` (lazy growth, the capture
  threshold, the beacon), `topics-serve` (one card, never the list; the three exit
  doors incl. the explicit conversion moment), `topics-groom` (the recurring
  gardener's round; the metric that matters).
- Storage design: server/schema.sql (topic tree + conversion links + append-only
  event history) and server/README.md (one process, HTTP + MCP faces, the adapter
  law, client-confirmed server-verified prune cascades).
- web/prototype: verbatim snapshot of the four working view files from the birthplace
  instance + PORTING.md (the behavioral contract, owner-reacted, do-not-regress).
- ROADMAP: server -> single-module merge -> port -> capture UX -> serving -> first
  outside user.

Not yet runnable as a plugin; see INSTALL.md for the intended flow.
