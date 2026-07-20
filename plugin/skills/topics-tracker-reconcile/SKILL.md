---
name: topics-tracker-reconcile
description: Use on the staleness alarm (health.staleness.warning, or the first-of-day nudge), after a work sprint ships things the topic tree predicted, or roughly monthly - the pass that closes open topics AGAINST the real work tracker so the tree stays a garden of live questions instead of a museum of answered ones. The single highest-value grooming act observed in field use, now codified. Topics are conversation seeds in the LOCAL topic tree (the topic_* MCP tools) - NOT project-management tasks.
---

# Reconcile the topic tree against the work tracker

The failure this prevents: work ships, but the topics that predicted it stay open. The
tree slowly fills with already-answered questions, serving loses its punch, and the human
stops trusting the cards. Field data (2026-07-20): a ~21-topic reconcile was the most
valuable thing a groom session did - and it was entirely manual. This skill is that
workflow, with `topic_reconcile` as the one-call apply step.

## When

- `health.staleness.warning` is true (the report now leads with it), or the first-of-day
  card carries the STALENESS ALARM line.
- A sprint/release just landed work the tree predicted.
- Monthly, as part of a groom, even without the alarm.

## The pass (three steps, human ratifies between 2 and 3)

**1. Pull the candidates.** `topic_list` (or `topic_search` scoped to a territory), keep
`state: open` + long-stale opens from `health.staleness`. This is YOUR read - the tool
does not fetch tracker state.

**2. Match with your own tools, then present the mapping.** Grep the tracker the human
actually uses (gh CLI, board `mb issues`, etc.) for each candidate's territory. Build a
table: topic -> disposition -> evidence:

- **discussed** - the tracker shows the question got answered/absorbed (link the evidence
  in `note`).
- **converted** + `ref` - a REAL tracker item exists for it (issue number/URL). `ref` is
  REQUIRED: reconcile never mints tracker items; minting stays `topic_convert`'s
  human-confirmed act.
- **pruned** - dead branch, the human says so. Reconcile refuses to prune a topic with
  live children (a bulk call must never cascade a subtree unseen) - reconcile the
  children first or use `topic_state` with its confirm-cascade.
- **leave open** - still a live question. Most topics should survive a reconcile; this
  pass is not a purge.

Present the table and WAIT for the human's ratification. Adjust what they push back on.

**3. Apply in one call.** `topic_reconcile` with the ratified items. Read the per-item
results - one bad item fails alone, never the batch - and report `applied`/`errors`
honestly. Every applied item leaves a `reconciled` audit event.

## Discipline

- The matching is judgment, not string-equality: a topic can be answered by work that
  never mentions its words. When unsure, propose `leave open` - a false close costs a
  real question; a false open costs one more serve.
- Do not reconcile seedlings; they are the capture layer, and the expiry valve owns them.
- After the pass, run `topic_groom_report` once: the reconcile usually reveals hubs whose
  children all closed - candidates for the next groom, not for silent pruning.
