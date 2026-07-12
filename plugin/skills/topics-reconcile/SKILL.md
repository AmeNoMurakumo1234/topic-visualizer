---
name: topics-reconcile
description: Use after a topic_import returns a worklist, or when topic_duplicates shows near-duplicate pairs, to curate a merged topic pile into one living tree. Governs the add-both-reconcile-later discipline - import adds liberally, and THIS is where the judgment happens: combine, keep-both-linked, or leave. Also governs export back to the git-committable .topics dir.
---

# topics-reconcile: turn a merged pile into one living tree

Import is deliberately dumb: it ADDS (idempotently) and hands back a worklist. It never
merges. Reconcile is where a real mind, with both bodies in view, decides what the import
could not. This is the serving-side discipline the CHARTER demands: a duplicated pile
reads as "we're on top of this" while it rots. A merged tree is the cure.

## When to reconcile

- Right after `topic_import` returns a non-empty `worklist` - it IS the agenda; work it now.
- During a grooming round: run `topic_duplicates` (band `kin` by default) for the same
  worklist any time, not only after an import.
- Never reconcile a pair you have not READ. Similarity is a candidate signal, never an order.

## The three moves (per candidate pair)

Read BOTH with `topic_get` first. Then choose in context:

1. **Combine** -> `topic_merge(into, from, body?)`. The common case for "extremely similar."
   Pick the survivor (`into`), and pass a `body` that is the REWRITTEN combination of both -
   not a truncation, not a concatenation: the single best statement of the shared topic and
   its one question. Children, extra parents, and conversions move to the survivor
   automatically; `from` is tombstoned (recoverable ~14 days, then gone).

2. **Keep both, related** -> `topic_attach`. Same surface, genuinely distinct topics that
   share a destination or a parent. Link them as co-parents / cross-avenues so the tree
   shows the relationship; do NOT merge.

3. **Leave** -> do nothing. Distinct despite the score. Recording nothing is a valid,
   common outcome; a false candidate costs one read.

## Picking the survivor

Merge the thinner into the richer: the topic with more children, more provenance, or the
clearer question is `into`. When equal, the older `created_at` wins (it carries more
history). Priority and the more-alive state survive automatically - you do not have to
preserve a beacon by hand.

## After reconciling: propagate

When the pass is done, `topic_export` (mode `mirror`) to the project's `.topics` dir and
commit it. Mirror drops the tombstoned files, so the merge travels to teammates through
normal git - no server, no sync. The exported files are byte-stable: an unchanged topic
produces no diff, so a reconcile commit shows exactly what changed.

## What reconcile is NOT

- Not auto-merge. There is no threshold that merges for you; that was rejected by design.
- Not a place to prune. A dead branch is `topic_state pruned`, not a merge.
- Not export-for-its-own-sake. Export because a reconcile changed the tree, not to feel busy.
