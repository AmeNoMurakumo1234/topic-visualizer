# Changelog

## 0.40.0 - 2026-07-13 - Board-backend integration: doctor/open work + the sqlite doctor hints the board

From a teammate's integration report:

- **`topic_doctor` and `topic_open` CRASHED on the board backend** - `BoardBackend` had neither
  `doctor()` nor `open_visualizer()`, so both AttributeError'd. Added board-appropriate versions:
  `doctor()` checks the board is reachable + serving the topic lane (reports the topic count + embedder
  status) and does NOT flag the unused sqlite `:8991` server as degraded - that false "degraded" was the
  confusing signal a board user hit; `open_visualizer()` hands back the board's own vendored visualizer
  URL (no sqlite server to start).
- **The sqlite doctor now HINTS the board.** On the default (sqlite) backend, if a message board is
  running, `topic_doctor` surfaces `board_detected` + a `routing_hint` ("a board is running; if your
  topics belong there, set `TOPICS_BACKEND=board`") - so an agent discovers the board routing instead
  of silently capturing to a local cwd-keyed store and having to ask.
- Regression guard: a new test asserts `BoardBackend` and `ServerBackend` have matching method surfaces,
  so a tool method added to one but forgotten on the other (the exact bug here) fails the suite.

Unchanged: the default backend stays sqlite (correct for external consumers). A team routes to the board
via `TOPICS_BACKEND=board` + `TOPICS_BOARD_PROJECT` (lane) / `TOPICS_BOARD_AUTHOR` (name).

## 0.39.1 - 2026-07-13 - redundant-parent: precise wording + chain-robust selection

- Sharpened 0.39.0 per the consumer: the rule is NOT "keep the nearer parent" (vague) - it is **keep
  the parent that is the DESCENDANT (child-side) of the other, drop the ancestor.** The code already
  selected the descendant; the skill and report wording now say so precisely, so an agent can't
  misread "nearest."
- Hardened the selection for a deeper chain: with P1->P2->P3 all parenting one card, it now keeps
  P3 (the leaf-most descendant) and drops BOTH P1 and P2 - never an intermediate. (Verified.)

## 0.39.0 - 2026-07-13 - Groom detects a redundant ancestor parent (consumer)

- A consumer found a subtle grooming residue: a card with two parents where one parent is an
  ANCESTOR of the other. The card reaches that ancestor twice - directly AND transitively via the
  nearer parent - so the direct edge is a duplicate longer path. The card should sit under the
  NEAREST parent alone and be the ancestor's grandchild through it.
- New read-only coherence signal `groom_report().coherence.redundant_parents` detects it
  (`{child, redundant_parent, keep_parent}`). It is a near-certain cleanup - a *provable* duplicate
  path, not a judgment, so it ranks above the sibling-avenue hint. The `topics-groom` skill's shape
  step now lists it first with the action: `topic_reparent` the card to `keep_parent` if the ancestor
  is its primary, else `topic_attach {..., remove: true}` the ancestor avenue.
- ZERO risk to the (already careful) mutation process: the signal is a DETECTOR only; the reshape
  uses the existing, audited `topic_reparent` / `topic_attach`. Verified end-to-end: detect ->
  reparent -> the card has a single nearest parent, is the ancestor's grandchild, the redundant edge
  is dropped, and the hint clears.

## 0.38.0 - 2026-07-13 - Third-audit sweep: cosmetic floor confirmed; 5 small items fixed, 1 flagged

A third Fable-5 pass gave every 0.37 fix an explicit clean bill ("no bug introduced by this round's
edits" - the fix-a-bug-injects-a-bug cycle has stopped) and called the calibration: **cosmetic floor
reached.** Swept the residue it surfaced:

- **[MED] The board backend's scoped mirror export still deleted out-of-scope files** - the 0.37
  scoped-export fix landed in `server.py` but was never ported to the board copy. Ported the
  `scope is None` delete guard (+ made it additive) to `BoardBackend.export`.
- **[LOW] A scoped export rewrote the full mirror's `index.json` down to the subset** - the index is
  now written only for a full (unscoped) export, on both backends.
- **[LOW] 0.36-era safety checkpoints migrated to `auto=0`** - a one-time migration backfills
  `auto=1` on the legacy `auto: before restore` rows, so an old DB's Undo can't target them.
- **[LOW] The MCP test suite was RED** (it asserted the pre-0.33 fifteen-tool set) - now asserts
  against the live `mcp_tools.TOOLS` registry, so it can't rot again. The MCP suite is a working gate.
- **[LOW] A resurrected merged topic, if later re-pruned, was hard-deleted** (the last drop of the
  0.37 resurrect leak) - `set_state` now clears `merged_into` on reopen.

Flagged, not applied: a mid-drag `pointerup` racing `unmount()` could throw in a renderer (the inner
drag listeners aren't on the abort signal) - realistically unreachable without a failed pointer
capture, and the clean fix is fiddly enough not to rush into a sanity pass. Still deferred by
decision: export/import `rel`/`role`/`tags` fidelity (needs a versioned format) and restore's
try/rollback. 41 server tests + the MCP suite green.

## 0.37.0 - 2026-07-13 - Second-audit fixes: 8 more (incl. one fix-injected bug), 2 flagged

A second Fable-5 pass verified the first round's fixes (clean bills on the restore/reconcile core and
the sweeps) and found fresh integration-seam issues. Each verified before changing code.

- **[HIGH] "Undo last groom" restored the WRONG checkpoint after any prior restore** - a bug INJECTED
  by 0.36's auto-checkpoint: the button filtered `auto:` snapshots for *display*, but the server's
  restore-latest still picked the newest *including* `auto:`, so a second undo silently re-applied the
  groom while reporting "Groom undone." Now the safety snapshot carries a structural `auto=1` flag
  (new column); restore-latest skips `auto=1`, and the button passes the explicit checkpoint id it showed.
- **[HIGH] A resurrected merged topic was hard-deleted 14 days later** - `expire_merged` swept on
  `merged_into` alone; a topic resurrected from the archive still carries `merged_into` but is LIVE.
  The sweep now requires `state='pruned'`, so only real tombstones age out.
- **[MED-HIGH] Star Chart piled at the origin after a live-refresh while focused** - render kept the
  stale focus object across `core.load()`; now it re-resolves to the current node.
- **[MED] All three renderers leaked pan/zoom listeners** on the shared container (view-switching
  stacked handlers -> double-zoom + dead-listener errors). Each mount now uses an AbortController,
  aborted on unmount.
- **[MED] A scoped export in mirror mode deleted every out-of-scope file** (a committed full mirror
  gone in one call). A scoped export is now always additive.
- **[MED-LOW] Restore's slug-reuse guard mishandled ISO-`T` timestamps** (could skip a genuine
  pre-checkpoint topic) - normalized before comparison.
- **[LOW] `BoardBackend.add` permanently rebound `self.author`** onto every later board op - now a
  per-call local. Cosmetic: lineage's avenue-out chip tooltip said "INTO".

Flagged, not applied (need a decision / careful isolated pass): export/import loses `rel`/`role`/`tags`
and can promote an avenue to primary (needs a versioned export format, not a patch); and `restore_checkpoint`
lacks the try/rollback `expire_merged` got - low-probability, but re-indenting ~95 lines of the
cardinal-invariant path risks injecting a bug, so it's deferred to a careful refactor.

## 0.36.0 - 2026-07-13 - Audit follow-ups: restore is undoable, safer locks, import cycle guard

Acting on the three flagged audit items (owner-directed):

- **Restore is now itself recoverable.** A restore auto-checkpoints the current (pre-restore) state
  first (labeled `auto:`), so an accidental "Undo last groom" can be undone - restoring that
  auto-checkpoint redoes the groom. The Undo button skips `auto:` checkpoints when picking the last
  groom to revert. (The button's two-click confirm dialog already guards the click itself; this adds
  a recoverable safety net behind it.)
- **`busy_timeout=4000`** on every connection, so the MCP direct-sqlite fallback waits for a lock
  instead of erroring `database is locked` when it opens a file the server is mid-writing. (The fuller
  lock-held-during-embedder-I/O refactor stays deferred - too delicate to do without care.)
- **Import cycle guard**: `_wire_imported` now walks the DAG before setting a parent, so a
  hand-authored `.topics` dir can't commit a primary-parent cycle (order-independent - the edge that
  closes a cycle is always caught).

Owner declined (with auto-checkpoint making restore reversible, these are lower-stakes): preserving
post-checkpoint conversions through a restore, and narrowing pass-3 recovery to merges only.

## 0.35.0 - 2026-07-13 - Audit fixes: 7 confirmed bugs fixed (each verified), 3 design items flagged

A Fable-5 read-only audit surfaced ~10 issues; each was verified against the actual code and
reproduced before any change (a false "fix" is its own bug). Confirmed and fixed:

- **[HIGH] Restore could overwrite a real capture via slug reuse.** Slugs hash the TITLE only, so a
  merged + hard-removed topic frees its slug for a same-titled new capture; restore then overwrote
  that capture with the snapshot body. Restore now guards identity (a re-inserted set + a
  created_at-vs-checkpoint check) and preserves the newer capture - the "never lose a capture"
  invariant holds. (Verified: reused slug keeps its own body.)
- **[HIGH] `expire_merged` FK abort + ride-along commit.** A post-merge capture can be parented
  under a tombstone (capture never checks parent state); the tombstone's 14-day hard-removal then
  tripped the `parent_id` foreign key, aborting the whole sweep and leaving partial deletes a later
  commit persisted. Fix: re-home such children to root before the delete (kills the FK) + the sweep
  is now atomic (rollback on any failure).
- **[HIGH] Checkpoint snapshot dropped `rel`/`role`/provenance/identity** (version skew - checkpoints
  predate those columns): a groom's `see_also` avenues reverted to `co_parent` on undo, hubs came
  back as plain topics, provenance was lost. Snapshot + restore now carry them; old checkpoints read
  defensively.
- **[LOW] Nested empty hubs were half-swept** on undo (single pass) - now a repeat-until-fixpoint
  sweep clears the whole chain.
- **[LOW] A `see_also` generated a reparent hint** (`reparent_hints` ignored `rel`) - now only a
  `co_parent` avenue between siblings is a depth hint.
- **[LOW] Title-only edits logged a spurious `reparented` event** (the web panel always sends
  `parent_slug`) - `edit_topic` now skips a no-op reparent.
- **[LOW] Constellation drew dangling avenue edges under "hide discussed"** - the xlink loop now
  applies the same hide skip as the node loop.

Each fix has a regression test (38 total) or a traced reproduction. Three items were NOT auto-applied
because they are design decisions, not clear bugs - flagged for the owner: restore-of-restore is
itself unundoable + drops post-checkpoint conversions on pre-existing topics; the request lock is
held during embedder network I/O (with a dual-process sqlite fallback on stall); and `import_topics`
lacks a cycle guard + can mint slugs the HTTP mutation route can't address.

## 0.34.0 - 2026-07-13 - Undo sweeps empty groom hubs (scaffolding is not a capture)

- Consumer follow-up on the undo: reparents reverted correctly and no real capture was lost, but a
  groom-created organizing HUB lingered as an empty orphan - restore keeps every post-checkpoint
  topic and couldn't tell a structural hub from a real capture, so a 5-hub groom left 5 childless
  hubs to hand-prune. The one-click "clean revert" wasn't actually clean.
- Fix (the consumer's Option 1 + 3): topics carry a `role` (`topic` default | `hub`; new column,
  idempotent migration). Grooming mints organizing hubs with `topic_add {role:'hub'}`. On restore, a
  sweep removes any `role='hub'` that is (a) created after the checkpoint AND (b) childless after the
  revert - deterministic, no heuristics. The invariant holds: a real capture is never a hub (never
  swept), and a hub still holding a mid-groom capture is NOT empty (kept). The result now reports it
  - `removed_hubs` in the MCP return, "N empty hub(s) swept" in the Undo button dialog.
- `role` also composes with junk-drawer detection (a flagged hub is a container, not a question) -
  wired into the groom skill's NEST step.

## 0.33.0 - 2026-07-13 - Co-parent avenues (drawn as real parents) + topic_edit closes the MCP surface

- The audit's 4th point: a genuine second parent rendered as a throwaway dashed "see also" and was
  ignored by layout. Now an avenue carries a KIND (new `rel` column, idempotent migration):
  - **Judgment, not similarity.** Tested against the real embedder, cosine scores genuine complements
    (0.12-0.35) like unrelated noise (0.13) - it captures paraphrase (0.88), not "two facets of one
    subject." So similarity is the wrong tool. An avenue's kind is set by the mind that created it:
    it defaults to `co_parent` (you attached it because you saw a real link); mark `see_also` for a
    weak aside. `topic_attach` gained a `kind` arg; re-attaching reclassifies.
  - **Rendered AS a parent.** All three views draw a `co_parent` as a solid, real parent edge (vs the
    `see_also`'s quiet dash). In Constellation a co_parent tugs at full parity with a primary tree
    edge, pulling the node toward both parents - subtle inside a tight shared-hub cluster (the parents
    are both tethered to the hub), pronounced when the parents live in different families.
- **`topic_edit` closes the "stashed in the API" gap.** `/edit` could change a topic's title/body but
  no MCP tool reached it - only `topic_reparent` (parent) and `topic_state` (beacon) tapped `/edit`.
  New `topic_edit {slug, title?, body?}` (batch) exposes the content edit. Full HTTP<->MCP audit done:
  every consumer capability now has a tool (20); the HTTP-only routes (health, version, projects,
  backgrounds) are deliberately folded into other tools or web-only, and cascade-prune auto-cascades.

## 0.32.0 - 2026-07-13 - Grooming shapes it WELL: depth-first, avenue-aware, coherence-checked

- A consumer audit of a real 55->60-topic groom found the loop chasing a WIDTH number while
  ignoring the depth signal already in the graph: an avenue (extra parent) between two siblings
  usually means one topic is a sub-question or complement of the other. Four fixes so the groom
  shapes the tree *well*, not just to-metric:
  - **Depth over width** (skill): the shape step leads with the relationships in the graph, not the
    3-7 fan. Real relational depth OUTRANKS the fan target - width-first was producing shallow, wide,
    incoherent hubs that passed the metric and still read as "weird."
  - **Avenue-between-siblings => reparent** (report + skill): `topic_groom_report` gains
    `coherence.reparent_hints` - every avenue whose two ends share a primary parent, i.e. a child
    hiding as a peer - to work FIRST with `topic_reparent`.
  - **Coherence, not just width** (report + skill): `coherence.possible_buckets` flags junk-drawer
    parents (a bucket title, not a question); the skill adds the judgment checks the report can't
    compute - mixed-altitude/voice siblings, a theme split across siblings, two clashing taxonomies.
  - **Propose-then-confirm** (skill): the taxonomy reshape now DRAFTS the hub/reparent plan and puts
    the organizing axis to the human to ratify BEFORE applying - the metric can't encode "this looks
    weird." The mechanical steps (dedup, conversions, expiry) don't need it; the subjective reshape does.
- (Rendering a genuine second parent AS a parent, not a throwaway dashed avenue - the audit's 4th
  point - is a separate renderer pass, next.)

## 0.31.0 - 2026-07-13 - Grooming undo: checkpoint + restore (never lose a capture)

- Grooming is the one bulk, hard-to-eyeball edit, so it now opens with a safety net and can be
  rolled back whole. NEW `topic_checkpoint` (snapshot the tree), `topic_checkpoints` (list restore
  points), `topic_restore {id?}` (roll back; omit id = the latest). The `topics-groom` skill now
  mandates a checkpoint as step 0 and documents the undo in its closing report. The board backend
  returns "not supported" - its git history is its undo, and board grooming doesn't reshape the
  primary tree.
- Restore is a RECONCILE, not a wipe - the subtlety that makes it trustworthy. Topics that existed
  at the checkpoint revert to the snapshot (reparents and merges fully reverse; merged-away topics
  return), but any topic CAPTURED AFTER the checkpoint is KEPT, never discarded. Losing a real
  capture made during a groom is the one unforgivable sin; a groom-created hub may linger empty
  (cosmetic, the next groom clears it). History (`topic_event`) is never wiped.
- Browser: an **"Undo last groom"** button (sqlite backend only, capability-gated on the adapter)
  with a confirm dialog that names the checkpoint time and promises the keep, and a result line
  ("4 restored; 1 captured since kept"). Deterministic, one click.
- Schema: `groom_checkpoint` table (idempotent add), retaining the newest 15 restore points.

## 0.30.0 - 2026-07-13 - topic_reparent: grooming can finally reshape the tree

- The `topics-groom` skill's headline step - nest a wide fan, reparent the mis-placed - was
  impossible via MCP. The only parent tool was `topic_attach`, which adds an AVENUE (an extra
  cross-link in the multi-parent DAG), NOT the primary parent. So a faithful groom built hubs with
  N dangling dashed links and zero real children; the spine and the fan-out metric never moved and
  the tree read as broken. A consumer hit exactly this on a 55-topic tree.
- NEW `topic_reparent {slug, parent_slug}` (batch: `items:[{slug,parent_slug}, ...]`) moves a
  topic's PRIMARY parent through the existing, fully cycle-guarded edit endpoint; `parent_slug=""`
  detaches to root, and a now-redundant avenue collapses into the new primary edge. A missing
  `parent_slug` key is refused (so a batch can't silently detach to root). The board backend
  refuses cleanly - its primary parent lives in an immutable post body.
- The `topics-groom` skill now names `topic_reparent` for the reshape step and spells out
  attach-vs-reparent, so it can no longer instruct an unsupported op. Also notes that `topic_add`'s
  `parent_slug` sets a real primary parent at birth, so the gap only ever bit EXISTING topics.

## 0.29.0 - 2026-07-13 - Changelog backfilled + kept honest by a test

- Backfilled every release from 0.9.1 through 0.28.0. The changelog had frozen at 0.9 while the
  plugin shipped 19 versions - a stale, abandoned doc is worse than none. To stop the rot at its
  root (updating it was never part of the release ritual), a new test
  `test_changelog_covers_current_version` now fails any release whose VERSION has no `## <version>`
  heading here - so a CHANGELOG entry is enforced at the same gate as version-field coherence.

## 0.28.0 - 2026-07-13 - Star Chart critical-pull

- Star Chart criticals now read identically to Constellation: orange label + beacon halo + a
  1.22x size bump, so a critical topic looks the same in all three views. Discussed nodes already
  carried the shared teal recolor; the Star Chart legend now matches. Closes the cross-view
  attention-layer sweep begun in 0.26.

## 0.27.0 - 2026-07-13 - Hide any visible branch

- Lineage's "Hide this branch" now works on ANY visible child, not just a revealed one under a
  partial parent (0.25 gated it too narrowly, so a fully-expanded tree offered no hide affordance).
  On a fully-open parent it demotes to partial - reveals every sibling, drops only the chosen
  branch - so nothing else in the view moves. The true inverse of revealing one avenue-out.

## 0.26.0 - 2026-07-13 - Constellation attention layer

- Criticals pop (orange label + halo + size bump). "Discussed" changes from a near-invisible fade
  (read as "ignore me") to a legible teal ring at half opacity (reads as "touched"). A "hide
  discussed" legend toggle declutters on demand, dropping those nodes AND their edges. Emphasis,
  not collapse - hiding by default would gut the whole-shape view Constellation exists to show.

## 0.25.0 - 2026-07-13 - Lineage panel actions

- Two actions on a selected Lineage node, so you steer the tree from the detail panel instead of
  hunting the tiny +/- caret: "Show critical/discussed/seedling (N)" partially reveals just that
  category's still-hidden children, and "Hide this branch" un-reveals a single revealed child.

## 0.24.0 - 2026-07-13 - Partial-layout fix + smart initial state

- Fixed the partial-expansion layout: a revealed child now lays out under its parent (the layout
  pass was still positioning it as a far-away leaf). Initial state: a node with many children is
  never dumped fully-expanded on first visit (big trees auto-open only shallow + narrow nodes), and
  every critical topic's path is revealed on load so beacons always show via partial expansion.

## 0.23.0 - 2026-07-13 - Lineage partial expansion

- Reveal-to-child instead of blast-all: expanding a collapsed node reveals a path to one child
  rather than dumping the entire subtree. `revealPath` threads open just the ancestors needed.

## 0.22.0 - 2026-07-13 - Lineage collapse polish

- Collapsing a node keeps that node visually fixed (no more vanishing-camera jump on collapse), and
  expand/collapse is available from the detail panel, not only the caret.

## 0.21.0 - 2026-07-13 - Lineage collapses by default at scale

- Past a handful of nodes, Lineage opens collapsed beyond the top level - a drill-down view, not a
  wall of everything. Small trees (<=35 nodes) still open fully.

## 0.20.0 - 2026-07-13 - Grooming becomes a judgment shaper

- The topics-groom skill's shape step now guides merge + nest + reparent toward a 3-7-children
  branching band, driven by judgment (semantic similarity PROPOSES clusters; you decide which are
  real). Retired the idea of autonomous mechanical grooming - a similarity-only regroup picks the
  wrong axis and is worse than no grooming.

## 0.19.0 - 2026-07-13 - Header + panel layout

- The header reads as planned rows instead of smushing on wide screens; the linked-item chips in
  the right panel hang above their row instead of cramming into three columns.

## 0.18.0 - 2026-07-13 - No-admin persistence + upgrade-aware launcher

- Autostart via the Startup folder (no admin needed - schtasks required elevation); an
  upgrade-aware self-healing launcher resolves the newest installed version dir; plus three
  doctor/path fixes.

## 0.17.0 - 2026-07-12 - Self-healing autostart

- A silent UI-uninstall now cleans up its own autostart artifact instead of leaving a dangling
  launcher pointing at a removed version.

## 0.16.0 - 2026-07-12 - Graceful teardown

- A new `topics-teardown` skill + installer `--uninstall`/`--stop` release the machine as cleanly
  as onboarding set it up: stop processes by EXACT script path (never a command-line substring),
  remove the service and the autostart artifact.

## 0.15.0 - 2026-07-12 - Surface the visualizer + discipline skill

- `topic_open` MCP tool opens the web visualizer on demand; a top-level `topics` discipline skill
  teaches the capture -> serve -> groom loop as one practice.

## 0.14.0 - 2026-07-12 - Service installer + version coherence

- `install_service.py` sets the server/embedder to run in the background; `VersionCoherenceTests`
  enforce that the three version fields (plugin.json, marketplace.json, server VERSION) stay in
  lockstep, so a bump that misses a file cannot ship.

## 0.13.0 - 2026-07-12 - Bundled CPU embedder

- Ships `serve_embedder.py` (sentence-transformers all-MiniLM-L6-v2, CPU) so semantic search and
  write-time dedup work out of the box - no external embedding endpoint required.

## 0.12.0 - 2026-07-12 - Guided onboarding skill (the headline fix)

- `topics-setup`: a guided first-run skill that walks a consumer from install to a working,
  semantically-ranked store. The field report's headline ask - onboarding was the cliff.

## 0.11.0 - 2026-07-12 - Doctor + degraded banner

- `topic_doctor` MCP tool + `--doctor` CLI diagnose the install (store path, embedder reachability,
  service state); a loud banner in the UI when running degraded - the plugin never silently runs at
  half value.

## 0.10.0 - 2026-07-12 - Live refresh

- The web views poll a cheap change-signal and refresh so the tree is never stale (plus a manual
  refresh). Toggling off the polling also stops it - your call.

## 0.9.1 - 2026-07-12 - Remember last project

- The web adapters remember the last-viewed project (localStorage `topics-project`) and reopen to
  it instead of resetting to the default each visit.

## 0.9.0 - 2026-07-12 - Board topic lane (type='topic')

- The board backend now stores topics as a first-class `type='topic'` post (was `type='proposal'`
  with an `OPEN THREAD:` title prefix), and reads them via `/api/posts?type=topic`. This lets a host
  board exclude topics from its coordination surfaces (feed / owner-queue / health) — a topic no
  longer balls the owner or shows up as coordination. The `OPEN THREAD:` prefix remains as a human
  label. Requires a board that understands `type='topic'` (see INTEGRATING.md). The example adapter
  is updated to match. The sqlite backend is unaffected.

## 0.8.0 - 2026-07-12 - Export / import / reconcile

- **Share the tree through git, not a server.** `topic_export` writes this project's live
  tree to a directory of byte-stable per-topic files (`<repo>/.topics/<slug>.json`,
  git-committable); `mirror` mode makes the dir exactly match the store, `snapshot` only
  adds. No cloud, no daemon - sharing is a commit.
- **`topic_import` is additive + idempotent.** Unchanged topics skip (content-hash), a
  slug collision with different content imports under a disambiguated slug, a recently-
  merged slug is not resurrected. It NEVER auto-merges; it returns a reconcile WORKLIST of
  candidate near-duplicate pairs touching the imported topics.
- **`topic_merge` folds one topic into another** - re-parents children, transfers parent/
  extra edges and conversions to the survivor, takes the stronger priority/state, optional
  rewritten combined body, and tombstones the loser (recoverable in the archive, hard-
  removed after 14 days by the prune sweep). Cycle- and self-guarded.
- **`topic_duplicates`** lists candidate near-dup pairs on demand (the same worklist).
- **New `topics-reconcile` skill** carries the add-both-reconcile-later judgment: read both
  with topic_get, then combine / keep-both-linked / leave - similarity is a candidate
  signal, never an order.
- Board backend gets read-only `export` + additive `import`; `topic_merge` returns a clear
  "not supported" (the board is already a shared store). New `topic.merged_into` column
  (idempotent migration).
- Hardened the board-integration EXAMPLE (`docs/examples/adapter-board.js`), the template
  `INTEGRATING.md` points consumers at: `load()` strips the `OPEN THREAD:` marker on read
  (matching the MCP backend), `create()` caps the title at 200 chars, and
  `setState`/`create`/`prune` now surface write errors instead of swallowing them.

## 0.7.0 - 2026-07-11 - Batch mutations

- `topic_state`, `topic_convert`, and `topic_attach` now take an optional `items:[...]`
  array (the same pattern `topic_add` already used), so a grooming round applies many
  changes in ONE tool call instead of one-per-op (the reporter's round took 22 sequential
  calls). Each op is applied independently and returns a per-item result under
  `{results:[...]}`; the single-arg form is unchanged. Batch beacon-audit demotions,
  multi-avenue attaches, and end-of-round conversions are now one call each.

## 0.6.1 - 2026-07-11 - Audit fixes: zero-setup store path, honest errors, full scrub

A fresh-eyes audit before calling 0.6 done. Fixes:

- ZERO-SETUP STORE PATH (the important one). The direct-sqlite fallback (`ServerBackend.
  _fallback`) and the first-of-day `SessionStart` hook resolved the store BEFORE anchoring
  `DB_PATH`, so with no server running they wrote to `<cwd>/projects/<key>.db` instead of
  `~/.topic-visualizer/projects/<key>.db` - and under Claude Code the cwd is a throwaway
  worktree, so captures scattered per-worktree (the exact bug 0.5.1's repo-root keying
  killed, reintroduced on the fallback path). Both now anchor to the home store and read
  the correct PER-PROJECT file. The first-of-day card also opened the legacy `default`
  store (empty since 0.5.0's per-project split) - it now reads the session's project.
- HONEST ERRORS: `topic_state` with BOTH a state and a priority no longer masks a failed
  sub-call as `{ok:true}` (e.g. the board backend's append-only priority always errors) -
  any sub-error is surfaced at the top level so it isn't swallowed.
- The `topic_get` description now notes the board backend returns core fields only (no
  children/history) - that detail is sqlite-only.
- The topics-groom skill now points at `topic_list` (enumerate) and `topic_get` (read a
  body) - the two tools 0.6.0 added for exactly that round.
- FULL IDENTIFIER SCRUB: the shipped demo data and the prototype snapshots hard-coded an
  agent name + the author's project domains; the README/CONTRIBUTING named the author's
  business. All replaced with neutral, generic placeholders - the plugin now references
  nothing but the `Ame No Murakumo` publisher brand.

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
  (`C--Repos-MyApp`); now it shows just the folder name (`MyApp`). The real name is read
  from the project's session transcript (the `~/.claude/projects` dir name is a lossy
  encoding), worktree-stripped, so hyphenated names survive intact (`my-cool-app` stays
  `my-cool-app`, not `app`). No drive/path leak.
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
  same way Claude names `~/.claude/projects` (`C:\Repos\my-app` ->
  `C--Repos-my-app`). Existing single-store topics are preserved as the `default`
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
