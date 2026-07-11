# docs/prototype - the working snapshot (formerly web/prototype), and how it becomes the plugin's web layer

These four files are a verbatim snapshot (2026-07-11) of the WORKING prototype from the
birthplace instance, where they run against a message-board backend. They are kept here
as provenance + golden masters: the plugin's final views must look and behave like
these (five rounds of human reaction shaped every behavior).

## What must change in the port (and nothing else)

1. **The storage adapter.** Each file currently fetches `/api/posts?project=...` and
   posts to `/api/post/resolve` / `/api/reopen` with a board-specific shape (OPEN
   THREAD title prefix, `parent: <slug>` body convention, resolve kinds
   completed/discarded). The plugin replaces this with the clean topics API
   (see ../../server/README.md): `/api/topics` + `/state` + `/links` + `/beacon`.
   NOTHING else about the views should change - that is the adapter law.
2. **The single-module merge.** The three files triplicate their shared logic (data
   load + state mapping, family hues, demo generator, detail panel, prune/discuss/
   reopen actions, starfield/twinkle). Extract once into `topics-core.js`; keep three
   renderer modules; kill topics.html's iframes in favor of three renderers in one
   shell with one data load.
3. **Demo mode stays** (?demo=N, deterministic seed 42) - it is the scale-testing and
   screenshot tool, and it must keep producing the identical tree in all three views.

## Behavioral contract (do not regress; each item was owner-reacted)

- Cursor-anchored zoom (the point under the mouse stays fixed across scale changes).
- Semantic zoom: any shown label is READABLE (constant ~12px screen size via INLINE
  styles - stylesheets override SVG presentation attributes, a real bug we shipped
  once) with importance culling (~16 far / ~40 mid / all near); halo stroke scales
  with the label.
- State language everywhere: frontier sparkle, critical beacon (pulsing), discussed
  ember (reopenable), prune-with-descendant-count (reversible), legend in the HUD.
- Family hues: golden-angle per root lineage, tinting cores/leaves/edges/fog (A, C)
  and card leading edges (B).
- Star Chart: focus+context (rings compress outward, "+N deeper" halos), double-click
  or Focus-here re-centers with animation, breadcrumbs walk home.
- Lineage: collapsing is its zoom-out; it deliberately has no label culling.
