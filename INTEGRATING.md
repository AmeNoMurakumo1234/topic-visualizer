# Integrating the Topic Visualizer into your own web app

The three views run inside ANY web app that can serve six static files and write one
adapter. This document is the complete contract - written so you can hand it to your
own AI assistant and say *"integrate the topic visualizer into our app"* and it has
everything it needs: the file manifest, the exact adapter interface, the host-page
skeleton, a real worked example, and the acceptance checklist.

The proof it works: the plugin's own birthplace runs these exact files vendored into a
message-board web app whose storage is *posts*, not SQLite - the views never noticed.

## The one law

**The views are storage-blind.** All storage knowledge lives in ONE file - your
adapter - which presents `window.TopicsAdapter`. You vendor the view files verbatim
and never edit them; you write only the adapter (and a host page). If you find
yourself editing a vendored file, you are integrating wrong - fix it upstream or in
the adapter.

## Step 1 - vendor the view files (verbatim, from `plugin/web/`)

| File | Role | Edit? |
|---|---|---|
| `topics-core.js` | tree/DAG building, states, search, panel, prune flow | NEVER |
| `render-constellation.js` | force-graph view | NEVER |
| `render-lineage.js` | collapsible tidy-tree view | NEVER |
| `render-starchart.js` | radial focus+context view | NEVER |
| `topics-shell.js` | boot + view switching + toolbar wiring | NEVER |
| `topics.css` | all styles | NEVER |
| `adapter-sqlite.js` | the plugin's own adapter | DO NOT COPY - you write your own |

Keep a header comment in your copies naming this repo as the canonical source and the
commit you vendored from. To update later: re-copy the six files, keep your adapter.

## Step 2 - write your adapter

One JavaScript file defining `window.TopicsAdapter` (an object literal). It must be
loaded AFTER `topics-core.js` and BEFORE `topics-shell.js`.

### Required methods

**`async load(includeArchive) -> Topic[]`** - fetch every topic. Each Topic:

| field | type | meaning |
|---|---|---|
| `slug` | string | unique stable id (used everywhere) |
| `title` | string | short label; may carry a `(time-weight)` suffix |
| `body` | string | full context text |
| `author` | string | who planted it |
| `created` | string | display date (first 10 chars shown) |
| `parentSlug` | string or null | PRIMARY parent (the layout spine); null = root |
| `extraParents` | `[{slug, note}]` | additional avenues (multi-parent DAG); `[]` if none |
| `state` | string | `seedling` \| `open` \| `discussed` \| `pruned` \| `expired` |
| `critical` | bool | the beacon flag |

When `includeArchive` is true, ALSO return `pruned`/`expired` topics (they render as
resurrectable ghosts). If your store has no archive, ignore the argument and set
`archiveCapable: false` on the adapter - the toggle hides itself.

**`async setState(slug, state, actor, note)`** - state transitions. `state` is one of
`open` (reopen/resurrect), `discussed`. `actor` is `"human"` or an agent name.

**`async prune(slugs, actor)`** - prune a whole branch. `slugs[0]` is the root the
human confirmed; the full array is the subtree they SAW in the consequence dialog
(survivor topics - reachable via another live avenue - are already excluded). If your
backend can verify the cascade server-side, send the array; otherwise iterate.

### Optional methods (capability detection - UI hides what you omit)

| method | enables | notes |
|---|---|---|
| `async create(items)` | the quick-add box | `items = [{title, parent_slug, state, created_by}]` |
| `async search(q) -> [{slug, score, state}]` | server-ranked search | omit -> client keyword scoring still works |
| `async health() -> {captured, served, converted, pruned, expired, beacon_warning}` | the seam-health strip | omit -> strip hidden |
| `async projects() -> {projects: [{key, label, current}], current}` | the project-switcher dropdown | omit -> no dropdown. The list is yours to define (e.g. Claude projects on the machine, or your app's projects); selecting one reloads with `?project=<key>`, which your adapter reads to scope its calls |
| `async edit(slug, {title, body, parent_slug, critical}, actor)` | the panel Edit form | `parent_slug: ""` re-roots; return `{error}` to surface a message |
| `async attach(slug, parentSlug, note, actor, remove) ` | "+ add avenue" in the panel | the multi-parent write; return `{error}` to surface |
| `attachRemove: true` | the per-avenue detach button | only if your store can remove an avenue |
| `archiveCapable: false` | HIDES the archive toggle | omit when archive works |

Every optional gap degrades gracefully - the corresponding control simply never
renders. Start with the three required methods and ship; add capabilities as your
backend earns them.

## Step 3 - the host page

Copy [docs/examples/host-page-board.html](docs/examples/host-page-board.html) and
adjust paths. The shell looks up elements by id, so the skeleton must keep: the
`#viewtabs` buttons (`data-v="constellation|lineage|starchart"`), `#search`,
`#quickadd`, `#archive` (inside a `.archchip` label), `#stat`, `#hint`, `#legend`,
`#seamhealth`, `#stage` containing `#stars` (canvas) + `#renderer`, **`#panel` INSIDE
`<main>`** (it floats over the stage and must never cover your app's chrome), and
`#confirm` / `#confirmBox`. Script order:

```html
<script src="topics-core.js"></script>
<script src="adapter-YOURS.js"></script>
<script src="render-constellation.js"></script>
<script src="render-lineage.js"></script>
<script src="render-starchart.js"></script>
<script src="topics-shell.js"></script>
```

Demo mode comes free: any host page accepts `?demo=N` (synthetic, client-side,
never touches your adapter) - useful for verifying the vendoring before the adapter
even exists.

## The worked example: a message board as the store

[docs/examples/adapter-board.js](docs/examples/adapter-board.js) is the real,
running adapter from the birthplace instance. Its store is a message board with
*immutable post bodies* - worth reading because it shows how far the contract
stretches without touching the views:

- **Topics are posts** with an `OPEN THREAD:` title prefix; everything else on the
  board is invisible to the views.
- **Tree structure rides body conventions**: `parent: <slug>` lines (first = primary,
  rest = extra avenues), `stage: seedling`, `priority: critical`.
- **States map onto what the board already has**: resolve-completed = discussed,
  resolve-discarded = pruned (and, loaded with `includeArchive`, discarded posts
  return as ghosts; reopen = resurrect).
- **Immutability workaround**: post bodies cannot be edited through the board's API,
  so `attach()` posts an `also-parent: <slug> | <note>` THREAD REPLY, and `load()`
  parses replies back out (a `message_count` field guards the extra fetch). The
  thread becomes the topic's rediscovery log. No `edit()` - the Edit button simply
  never appears. No `attachRemove` - replies are append-only.
- **Auth**: the board's anti-CSRF check wants an exact `X-Requested-By` value on
  writes; your app's equivalent goes in the same place.

If a message board can be a topic store, your app's data model almost certainly can.

## Server-side integration (optional, for AI agents)

If your app's agents should read/write topics through MCP instead of the browser,
`plugin/server/mcp_tools.py` shows the same adapter law server-side: one tool
contract, swappable backends (`TOPICS_BACKEND`), with the ranking brains
(`near_duplicates_in`, `search_in`, `rank_candidates` in `server.py`) imported as a
library so ANY backend gets identical semantic dedup/search/serve ranking. Writing a
third backend = one class with `add/serve/search/state/convert/attach/groom`.

## Acceptance checklist (run these before calling it integrated)

1. Host page opens; `?demo=120` paints all three views (proves vendoring + shell,
   no adapter needed).
2. Without `?demo`: your real topics load; count in the header stat matches your store.
3. Click a node -> panel opens with title/body/avenues; Esc closes it.
4. Switch all three views - same data, selection survives re-render.
5. Search filters (matches lit + labeled, rest ghosted); Esc clears.
6. Mark discussed -> your store changed; reopen -> back.
7. Prune a small branch -> consequence dialog counts correctly, store reflects it;
   if you support archive: toggle it, see the ghosts, resurrect one.
8. If quick-add enabled: plant a topic, it appears under the selection.
9. If attach enabled: add an avenue, see the dashed cross-link in Constellation.
10. Zoom far out in Constellation with 100+ topics: every visible label is readable
    (the semantic-zoom contract; if labels are soup, a vendored file was modified).

## Versioning note

The adapter contract above is the v0.5 surface (v0.5 added the optional `projects()`
capability). New optional capabilities may be added (they degrade gracefully when
absent); REQUIRED-method changes will be called out loudly in
[plugin/CHANGELOG.md](plugin/CHANGELOG.md).
