# Export / Import / Reconcile: sharing a topic tree without a graveyard

Design spec, 2026-07-12. Brainstormed by the maintainers (superpowers:brainstorming),
all keystone decisions owner-ratified same day. This document is the WHY and WHAT; the
implementation plan derives from it.

> Applies to the sqlite backend (per-machine store). The board backend already shares a
> tree natively (topics are posts on a shared store), so it gets export + additive
> import but not the merge/DAG operations — see "Both backends" below.

## The insight the design serves

The plugin already has a team-sharing mechanism for anyone on a message board. This
spec is for everyone else — the per-machine sqlite users — and for two jobs the owner
named:

1. **A git-committable canonical tree.** The exported files *are* the shared artifact.
   The team commits `.topics/`, pulls it, and their store reconciles against it. No
   server, no cloud, no sync daemon — sharing is just git. This honors the CHARTER's
   hard line: no cloud sync, privacy is structural.
2. **Curating a merged dump.** It is not unreasonable for a dev to have 5–10 sessions
   dump their context into topics at once and then need to curate the result. Many
   contexts producing near-duplicates is the *normal* case, not the exception.

The trap this design must avoid is the CHARTER's trap in a new costume: an import that
silently folds "similar" topics together is just a faster way to build a graveyard of
wrong merges. So the governing principle is the same one topics-capture already runs on:

> **Capture liberally, reconcile deliberately.** Import is additive and dumb-but-safe.
> The judgment — combine, link, or leave — happens in a *separate reconcile pass* with
> real in-context understanding, never inside a batch import against a threshold.

Import never resolves a conflict. It *adds*, and it *hands back the agenda*. The next
call swings.

## Ratified decisions (the keystones)

1. **ADD-BOTH, RECONCILE-LATER.** On import, topics are added additively and
   idempotently; similarity is *flagged*, never auto-merged. Combining two topics is
   always a judgment made afterward with both bodies in view, not a threshold decision
   made blind.
2. **IMPORT TEES UP RECONCILE.** `topic_import`'s response carries the reconcile
   worklist — the candidate near-duplicate pairs above the "good" threshold. The flow
   is one motion: import → work the returned pairs. No separate discovery step.
3. **DIRECTORY OF PER-TOPIC FILES.** Export writes `.topics/<slug>.json`, one file per
   topic, so two sessions adding different topics never collide in git. Byte-stable
   output means unchanged topics produce no phantom diffs.
4. **MERGE IS A PRIMITIVE, RECONCILE IS A SKILL.** The one genuinely-new server
   operation is `topic_merge` (fold B into A with re-parenting). The intelligence that
   decides *what* to merge lives in a `topics-reconcile` skill (a prompt), where it is
   tunable without code and has full context — matching the existing
   topics-capture / topics-groom pattern.
5. **SOFT-DELETE THAT AGES OUT.** A merged-away topic is tombstoned (recoverable), and
   the existing prune sweep removes tombstones older than **14 days**. A merged item is
   deliberately dead, so it ages faster than a ~21-day untouched seedling. 14 is a
   ceiling, not a target.

## Architecture

Four new thin primitives on the store + MCP layer, one new skill. Export and import are
mostly mechanical over store methods that already exist; the only new DAG logic is
`topic_merge`.

```
sessions capture ──▶ local sqlite store
                          │  topic_export (mirror)
                          ▼
                     .topics/  ◀── git commit / pull / push ──▶ teammates
                          │  topic_import (additive + worklist)
                          ▼
                  topics-reconcile skill
             (topic_get → topic_merge | topic_attach | leave)
```

### Component 1 — Export format & layout

Export writes a **directory**, git-committable, defaulting to `.topics/` at the **repo
root** (no per-project namespace — the directory already lives inside the project's
repo, so a project key would be redundant).

- `.topics/<slug>.json` — one file per topic. Fields: `slug`, `title`, `body`, `state`,
  `priority`, `parents` (slugs), `links` (cross-link slugs), `provenance`, `created_at`,
  `updated_at`, and a `content_hash`. The slug is the filename and the stable identity.
- `.topics/index.json` — thin manifest: `schema_version`, `exported_at`, `count`,
  `source_project`. Lets import validate the dir and distinguish a whole-tree from a
  partial export.
- **Stable key order.** Files are serialized with sorted keys and a fixed field order, so
  re-exporting an unchanged topic yields a byte-identical file — no spurious git diffs.
- **Two modes:**
  - `snapshot` — write to a target/fresh dir; for a hand-off. Adds files, does not
    delete.
  - `mirror` (default, to `.topics/`) — make the dir exactly match the store: write
    current topics, **delete files whose topics no longer exist** (including tombstoned
    ones). Keeps the canonical repo tree honest.

`content_hash` is computed over the semantic fields (title, body, state, priority,
parents, links) — not timestamps — so it is the identity check import uses to detect
"same topic, unchanged."

### Component 2 — Tool surface (four primitives)

- **`topic_export(dir?, mode?, scope?)`** — write the dir. `dir` defaults to `.topics/`
  at repo root. `mode` ∈ {`mirror`(default), `snapshot`}. `scope` optionally limits the
  export to a subtree (by slug) or to `critical`-only; default is the whole project.
- **`topic_import(dir?)`** — read a dir; add every topic **additively + idempotently**:
  - exact slug present locally **and** identical `content_hash` → **skip** (idempotent).
  - slug present locally but **content differs** → import under a **disambiguated slug**
    (`<slug>-<shorthash>`) and record a near-dup link to the local one. Never overwrites.
  - slug tombstoned locally within its 14-day window → **skip** (do not resurrect a
    deliberately-merged topic from a stale hand-off).
  - otherwise → **add**.
  - Returns `{added, skipped, disambiguated, worklist}`. The **worklist** is the reconcile
    agenda: candidate pairs `{a, b, similarity, reason}` above the "good" threshold —
    both freshly-imported pairs and any pre-existing near-dups it noticed.
- **`topic_merge(into, from, body?)`** — fold `from` into `into` (see Component 3).
- **`topic_duplicates(threshold?)`** — list near-dup pairs on demand, same shape as the
  import worklist, so reconcile can be run any time — not only right after an import.

### Component 3 — `topic_merge` semantics (the sharp primitive)

`topic_merge(into, from, body?)` folds `from` into `into`:

- **Re-parent.** Every child of `from` becomes a child of `into`, deduped (no double edge
  if it is already a child).
- **Re-link.** `from`'s parents and cross-links transfer to `into`; any edge that would
  point `into` at itself is dropped.
- **Cycle-safety.** Refuse a merge that would make `into` its own ancestor (e.g. merging
  a parent into its own descendant). Return an error; do not corrupt the DAG. Checked
  **before** any write.
- **Body.** If `body` is supplied it becomes `into`'s body (the "rewrite the combined
  text" the reconcile pass produces). If omitted, `into` keeps its body and `from`'s body
  is preserved on the tombstone for recovery.
- **Priority / state.** The survivor keeps the stronger signal: `critical` wins if either
  side had it; the more-alive state wins.
- **Retire `from`.** Tombstone it: `merged_into = into`, `deleted_at = now`. Reversible
  until it ages out.
- **Transactional.** All re-pointing + tombstoning runs under the existing `_lock` in one
  transaction; `_fail` rolls back so a mid-merge error cannot half-migrate the DAG.

### Component 4 — Tombstone aging

- The existing prune sweep removes tombstones with `deleted_at` older than **14 days**
  (config knob, default 14). Merged bodies survive that long for undo, then are gone.
- **Mirror-export** drops files for tombstoned topics.
- **Import won't resurrect** a slug tombstoned within its window — a stale hand-off
  cannot undo a merge. After the window lapses the slug is free; if the same idea returns
  it is genuinely new context, and reconcile re-catches it.

### Component 5 — The reconcile pass (`topics-reconcile` skill)

Import returns the worklist; the **`topics-reconcile` skill** drives the AI to walk it.
Per candidate pair, the AI reads both (`topic_get`) and decides in-context:

- **Combine** → `topic_merge` with a rewritten merged `body`. The common case for
  "extremely similar."
- **Keep both, related** → `topic_attach` so they co-parent the shared child / cross-link;
  no merge. For "similar surface, genuinely distinct topics."
- **Leave** → distinct despite the score; record nothing.

The **"good" threshold** is the cutoff for what lands on the worklist at all — the same
embedding / `_dup_band` machinery the store already computes. Above it = "a human/AI
should look at this pair," *not* "merge this pair." The threshold is a config knob with a
default tuned so the worklist is candidates-worth-reviewing rather than noise. The skill
states plainly that the AI may always decline to merge. Reconcile after a session's
import, then `topic_export` (mirror) + commit so the merge propagates to the team via git.

## Error handling & safety

- **Import is re-runnable.** Exact slug + identical `content_hash` → skip; safe to repeat
  with no ballooning on re-import of an unchanged dir.
- **Export is deterministic.** Stable key order → byte-identical files for unchanged
  topics → no phantom git diffs.
- **Merge is transactional and validated up front.** Cycle and self-merge are rejected
  before any write; the migration is one rolled-back-on-failure transaction.
- **Bad input is reported, not fatal.** A malformed/partial topic file is skipped with a
  note in the import summary; a missing dir is a clean error, not a crash.
- **Both backends.** The sqlite backend gets the full feature. The board backend
  (append-only, no DAG) supports `topic_export` and additive `topic_import`, but
  `topic_merge` and `topic_duplicates`-driven merging return a clear
  "not supported on this backend" rather than pretending.

## Testing

**`test_server.py`:**
- export → import round-trips: empty tree, single topic, deep multi-parent tree.
- idempotent re-import (no growth, all skipped).
- slug collision with different content → disambiguated slug + near-dup link.
- `topic_merge`: child re-parenting, parent + cross-link transfer, dedup of existing
  edges, `critical`/state survivorship, `body` override vs preserved-on-tombstone.
- `topic_merge` cycle rejection (merge that would self-ancestor) and self-merge rejection.
- mirror-export deletes stale + tombstoned files; snapshot does not delete.
- import won't resurrect a within-window tombstoned slug.
- prune removes tombstones older than 14 days; keeps younger ones.

**`test_mcp.py`:**
- the four tools over the MCP layer.
- `topic_import` returns a well-formed worklist (pairs with slug/slug/similarity/reason).
- `topic_merge` combined-body path.
- board-backend `topic_merge` returns the not-supported error.

All test data is generic and computer-agnostic (no identifiers), consistent with the
0.6.1 scrub.

## Versioning

New tools + a new skill = a **minor** bump. Target **0.8.0**: `VERSION`, `plugin.json`,
`marketplace.json` tool list, CHANGELOG, and the README tool count all updated in the
same change. `topics-reconcile` skill ships alongside.

## Out of scope (YAGNI)

- **Live/continuous sync.** No server, no daemon, no cloud — sharing is git. Explicitly
  ruled out by the CHARTER.
- **Auto-merge on import.** Rejected keystone #1: merges are never made blind against a
  threshold.
- **Three-way / field-level merge with a stored ancestor.** The add-both-then-reconcile
  model makes an ancestor-tracking merge engine unnecessary.
- **Cross-machine tombstone reconciliation.** The canonical `.topics/` re-exported after
  reconcile carries merges via git; distributed undo of a merge is not a supported flow.
