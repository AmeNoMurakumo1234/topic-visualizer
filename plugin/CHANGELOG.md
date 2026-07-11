# Changelog

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
