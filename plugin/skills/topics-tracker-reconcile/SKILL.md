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
  card carries the STALENESS ALARM line. (sqlite backend only - the BOARD backend has no
  staleness block, so on the board run this on the sprint/monthly triggers below.)
- A sprint/release just landed work the tree predicted.
- Monthly, as part of a groom, even without the alarm.

## The pass (three steps, human ratifies between 2 and 3)

**1. Pull the candidates.** `topic_list` (or `topic_search` scoped to a territory), keep
`state: open`. `health.staleness` carries the stale COUNTS (and the groom report's
`expiry_candidates_full_topics` a 3-item sample) - the full stale list you assemble
yourself from `topic_list`. This is YOUR read - the tool does not fetch tracker state.

**2. Match with your own tools, then present the mapping.** Search the work tracker the
human actually uses - whatever system that is: GitHub Issues via `gh`, Jira/Linear/Asana
search, a team board's CLI, plain grep over a TASKS file - for each candidate's
territory. Build a table: topic -> disposition -> evidence:

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

**3. Apply in one call.** `topic_reconcile` with the ratified items (each slug at most
once - duplicates in a batch error rather than double-apply). When one human ruling
covers many items, pass it as `decision` - it stamps every applied member - and use
`leave_open` for members the ruling deliberately spares (the grouped form of this pass
is its own skill: `topics-triage`). Read the per-item results -
one bad item fails alone, never the batch - and report `applied`/`errors` honestly. On
the sqlite backend every applied item leaves a `reconciled` audit event; the board leg
records the note on the resolve instead.

## Discipline

- The matching is judgment, not string-equality: a topic can be answered by work that
  never mentions its words. When unsure, propose `leave open` - a false close costs a
  real question; a false open costs one more serve.
- Seedlings are the capture layer and the expiry valve owns them - do not sweep them into
  a reconcile by DEFAULT. The carve-out: a deliberate human decision may close a seedling
  that the tracker already covers (the human says "that one's covered - close it"). The
  tool surfaces every such close (`seedlings_closed` + a per-item `was_seedling` flag in
  the result) - read that back to the human so a batch never eats seedlings silently.
- After the pass, run `topic_groom_report` once: the reconcile usually reveals hubs whose
  children all closed - candidates for the next groom, not for silent pruning.
