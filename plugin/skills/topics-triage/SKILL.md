---
name: topics-triage
description: Use when the live open-topic count has outgrown card-at-a-time serving (rough tell - more than ~30 live topics, or the human says "there's too much here, help me cut through it"), or right after a big groom leaves many freshly-nested live topics awaiting a verdict. Grouped triage - cluster the live topics into a handful of conceptual buckets, pose ONE broad ratifiable question per bucket, and bulk-apply the human's answer across the whole bucket with their actual words stamped on every member. Field result the ritual is built from - 5 questions cleared 51 of ~115 live topics in minutes, every close carrying the owner's ruling. Topics are conversation seeds in the LOCAL topic tree (the topic_* MCP tools) - NOT project-management tasks.
---

# Grouped triage: one question per bucket, not a card per topic

The failure this prevents: a healthy capture habit produces more live topics than
card-at-a-time serving can ever drain. The human faces 100+ open questions, engages with
none, and the tree's credibility dies of scale. The fix is altitude: cluster the live
topics into a few coherent buckets, ask one broad question per bucket, and let a single
answer settle the whole cluster - with sub-selection, never all-or-nothing.

**Division of labor (this is the design, not a suggestion):**
- the TOOL clusters and packages (`topic_buckets`) and bulk-applies (`topic_reconcile`),
- the AGENT frames the one question per bucket and maps the answer to per-member
  dispositions - judgment a tool can't compute,
- the HUMAN rules once per bucket, in their own words.

## Prerequisite: groom first

Buckets are seeded from the tree's OWN hub structure - a groomed tree already encodes
them. A bucket-serve over an un-groomed flat tree produces bad buckets (one giant "other",
arbitrary semantic groupings). Ideal order: `topics-groom` (shape the hubs) ->
`topics-triage` (serve them). If `topic_buckets` returns mostly `unbucketed` or a bloated
`other`, that IS the groom signal - stop and groom.

## The pass (four steps, human rules between 2 and 3)

**1. Pull the buckets.** `topic_buckets` (optionally `max_buckets`). Each bucket carries
its members (state, staleness, existing tracker links), counts, and a soft suggestion.
A top-level `alert` means the embedder is down - homeless leaf roots landed in
`unbucketed` because assignment was impossible, not because they belong nowhere; fix the
embedder or bucket those few by hand.

**2. Frame ONE broad, ratifiable question per bucket - with tracker context folded in.**
This is your judgment step. Before asking, check the work tracker the human actually
uses - whatever system that is (GitHub Issues via `gh`, Jira/Linear/Asana search, a team
board's CLI, plain grep over a TASKS file) - for the bucket's territory, starting from
the members' recorded links. Then compress the bucket into one question a human can
answer in a sentence, e.g.:

> "These 14 are all flavors of the auth-hardening question. The point-fix shipped last
> sprint (TRK-812); only the structural version is still live. Fold them into the
> structural epic, or keep any as separate conversations?"

Good bucket questions name the overlap, offer a default, and leave room for
sub-selection. Do NOT auto-generate bland prose - if you can't say what the bucket is
about in one honest sentence, it's two buckets (or needs a groom).

**3. The human rules - free-form, once per bucket.** "Defer these", "promote that one to
a rule", "fold all but the beacon into the epic", "park everything except X". Their
answer is the decision; capture their actual words.

**4. Bulk-apply with the ruling stamped.** ONE `topic_reconcile` call per bucket:
- `decision`: the human's actual words (e.g. `"owner ruling 2026-07-24: fold into the
  auth epic; keep the crypto question separate"`) - the tool stamps it on EVERY applied
  member, so each close carries the ruling without hand-copying,
- per-member dispositions: `discussed` (answered by the ruling), `converted` + `ref`
  (absorbed into an EXISTING tracker item - reconcile never mints; minting stays
  `topic_convert`'s human-confirmed act), `pruned` (dead branch, childless-only in bulk),
  and `leave_open` (below),
- read back `applied`/`errors` per item, and ALWAYS read back `seedlings_closed` - a
  bucket ruling may legitimately close seedlings, but never silently.

## Disciplines

- **"Leave open" is a first-class outcome.** Most topics should survive any pass - a
  false close costs a real question. `leave_open` records the ruling on the member
  (auditable: why it survived) while changing nothing - no state move, no staleness-clock
  reset. Sub-selection within a bucket is the norm: "park all except the beacon" closes
  some members and `leave_open`s the rest, in the same call.
- **One question per bucket, not one per topic.** If you catch yourself asking the human
  about individual members before the bucket ruling, you've fallen back into the
  per-card mode this skill exists to escape. Ask the broad question first; the ruling's
  sub-selection handles the exceptions.
- **The ruling is the human's words.** The `decision` stamp is a quote, not your
  paraphrase - the value of the field pattern was every close carrying what the owner
  actually said.
- **It pairs with the groom, both directions.** Grooming shapes the buckets; a triage
  usually reveals hubs whose members all closed - run `topic_groom_report` after and
  fold what it shows into the next groom, not into silent pruning now.
