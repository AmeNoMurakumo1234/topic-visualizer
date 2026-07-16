# Roadmap

## Done (the prototype, 2026-07-10/11)

Everything below exists and runs today in the birthplace instance (message-board
backend); snapshots live in [docs/prototype/](docs/prototype/):

- Three views over one tree: Constellation (force graph), Lineage (collapsible tidy
  tree), Star Chart (radial focus+context with re-rooting + breadcrumbs).
- State language across all views: frontier sparkles, critical beacons (pulsing),
  discussed embers (reopenable), prune-with-descendant-count (reversible).
- Family hues (color-by-group, golden-angle per root lineage) + nebula fog + curved
  edges + starfield/twinkle.
- Semantic zoom: cursor-anchored zoom; labels readable-or-absent (constant screen size,
  importance-culled budget: ~16 far / ~40 mid / all near).
- Tabbed shell switching views, remembered choice, lazy loading.
- Deterministic demo mode (?demo=N) for scale testing without polluting real data.

## Done (plugin form — current as of 0.8.0; see plugin/CHANGELOG.md)

1. **The server** (plugin/server/server.py, 27 e2e tests): batch capture w/ dedup,
   seedling lifecycle, serve ranking, search, edit w/ cycle guard, atomic conversion,
   verified prune cascades, expiry, health + groom reports.
2. **The single-module merge**: topics-core.js + three renderers + shell + adapters.
   The birthplace board VENDORS these verbatim with its own adapter-board.js.
3. **sqlite adapter wired + verified live** (create/search/health/edit/archive).
4. **SEMANTIC ranking** (search, dedup, serve territory-fit) via any OpenAI-style
   /v1/embeddings endpoint (TOPICS_EMBED_URL); keyword fallback when absent. The
   "only when the synonym gap bites" question resolved early because a local CPU
   embedder was already running here - zero extra install cost.
5. **The MCP face** (plugin/server/mcp_tools.py, 11 e2e over real stdio): thirteen tools
   (capture/get/list/serve/search/state/convert/attach/groom + export/import/merge/
   duplicates), TWO backends (plugin sqlite w/ zero-setup direct fallback; message-board
   posts w/ topic_convert minting REAL work items). plugin/.mcp.json registers it.
6. **Archive explorer + panel edit** (web): pruned/expired ghosts, resurrect, edit
   title/body/re-parent/beacon (capability-detected per adapter). Verified live on
   both backends.
7. **Installable plugin**: repo doubles as its own marketplace (root marketplace.json,
   plugin/ self-contained: server + web + skills + hooks + .mcp.json); both manifests
   pass `claude plugin validate`. See INSTALL.md.

## Next

1. **First real install** (this machine, then a genuinely outside user): run the
   INSTALL.md flow, validate hooks fire (SessionStart card, Stop/PreCompact sweeps),
   watch where it hurts, fix. The tool about conversations will be improved by
   having them.
2. **Capture UX in anger**: live with the skills + MCP tools through real sessions;
   calibrate the capture threshold from groom evidence, not intuition.
3. **Serving ritual polish**: does the first-of-day card actually feel like a gift?

## Open questions (tracked as topics, fittingly)

- Form factor details: marketplace listing? versioned releases like the sibling suite?
- Multi-tree support (work/personal)? Likely just multiple db files + a picker.

## Known minors (field-observed, next cycle)

- **cwd-keyed default store** (found 2026-07-15, 0.41.1 field test): the server keys its
  DEFAULT project store from its working directory at start. A login autostart (Startup
  VBS) starts it with cwd C:\WINDOWS\system32, so a garbage-keyed store
  (C--WINDOWS-system32.db) appears and pollutes the web UI's project picker. Session MCP
  captures are unaffected (they pass the project explicitly); only the server's default
  store and the picker's initial selection drift with the start context. Fix direction:
  the launcher should pass an explicit neutral default project (or the server should
  refuse to auto-key from a system directory and fall back to "default").
