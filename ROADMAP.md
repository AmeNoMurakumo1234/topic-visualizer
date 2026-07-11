# Roadmap

## Done (the prototype, 2026-07-10/11)

Everything below exists and runs today in the birthplace instance (message-board
backend); snapshots live in [web/prototype/](web/prototype/):

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

1. **Server**: implement [server/README.md](server/README.md) against
   [server/schema.sql](server/schema.sql) - one small process, HTTP API + MCP tools,
   SQLite owner. Zero heavy dependencies; localhost only.
2. **The single-module merge**: extract the triplicated view logic into one
   `topics-core.js` (data load, state, hues, panel, actions, demo) with a STORAGE
   ADAPTER seam; three renderers, one shell, no iframes. The views must never know
   the storage (the adapter law).
3. **Port the views** onto the sqlite adapter; golden-master eyeball check per view
   against the prototype snapshots.
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
