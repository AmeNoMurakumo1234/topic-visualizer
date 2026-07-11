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
- Tabbed shell (topics.html) switching views, remembered choice, lazy loading.
- Deterministic demo mode (?demo=N) for scale testing without polluting real data.

## Next (the plugin form, in order)

1. **DONE (2026-07-11): the server** (server/server.py, 8/8 e2e tests in
   plugin/server/test_server.py). Remaining server-side: the MCP tools file (thin wrapper over
   the same operations), optional local embedder install extra.
2. **DONE (2026-07-11): the single-module merge.** web/ now holds topics-core.js
   (tree building, hues, states, demo, shared panel + prune flow, semantic-zoom
   helpers) + three renderer modules + shell + adapter-sqlite.js (the server-spec
   client, awaiting the server) + index.html. The birthplace board VENDORS these
   files verbatim with its own adapter-board.js; verified live there against demo
   AND real data, all three views, golden-master eyeballed.
3. **DONE (2026-07-11): sqlite adapter wired + verified live** (create/search/health
   added; seedlings + search bar + quick-add + seam strip verified against the running
   server). Remaining web: archive explorer view, panel edit/re-parent UI.
4. **Capture UX**: wire the skills to the MCP tools; sharpen the zero-friction moment
   (the AI files topics mid-conversation without breaking flow).
5. **Serving ritual**: `topic_serve` ranking + the one-card presentation pattern.
6. **First outside user** (not the birthplace machine): install, run, watch where it
   hurts, fix. The tool about conversations will be improved by having them.

## Open questions (tracked as topics, fittingly)

- Form factor details: marketplace listing? versioned releases like the sibling suite?
- Semantic search over topics: only when the synonym gap actually bites (see CHARTER
  discipline 3 and the groom skill) - never before.
- Multi-tree support (work/personal)? Likely just multiple db files + a picker.
