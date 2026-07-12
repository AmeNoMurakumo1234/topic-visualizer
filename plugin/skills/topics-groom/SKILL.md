---
name: topics-groom
description: Use on a recurring cadence (weekly, or when the open-topic count grows noticeably) to keep the topics tree a garden instead of a graveyard - merge duplicates, surface expiry candidates for the human's explicit choice, verify beacons are still earned, and check that discussed topics got their conversions recorded. Grooming is a standing mechanism, never a discipline someone must remember.
---

# topics-groom: the gardener's round

A topics tree rots the same way every knowledge store rots: quietly. Grooming is the
dedicated, recurring counter-pressure. It exists as a scheduled act because systems
that depend on a busy mind remembering hygiene ARE the failure mode.

## The round

> Two tools carry the round: **`topic_list`** enumerates the whole store (slug/title/
> state/priority/parent) so you inventory it in one call instead of hand-unioned
> searches, and **`topic_get`** reads a topic's full body/question/avenues/conversions
> before you decide merge/convert/prune/keep. Reach for them in steps 1 and 4.

1. **Duplicates and near-misses.** Topics phrased differently but asking the same
   question get merged (keep the better-formed one; note the merge). `topic_list` to see
   them all; `topic_get` to compare two bodies before merging. This is also where the
   synonym gap shows - if search keeps missing kin topics, that is the signal to add
   semantic indexing, not before. When enumeration turns up near-duplicates, hand off to
   the **topics-reconcile** skill (`topic_duplicates` -> `topic_get` both ->
   `topic_merge`/`topic_attach`) rather than merging by hand - it carries the
   survivor-picking and propagation discipline.

2. **Expiry candidates - by choice, never by silence.** A topic unserved and untouched
   for ~a month is a candidate, not a casualty. Present candidates to the human ONE at
   a time or in a tiny batch (<=3) with the one question: *"expire this, keep it
   waiting, or talk about it now?"* Every answer is recorded. The difference between a
   graveyard and an archive is that someone chose the archive.

3. **Beacon audit.** Critical beacons are only meaningful while rare. If beacons have
   accumulated, re-justify each: still critical? Downgrade the rest. A tree full of
   beacons has none.

4. **Conversion integrity.** For recently-discussed topics: did the conversations that
   yielded outcomes actually get their conversion recorded (decision written, work
   items minted, links back)? An extracted-but-unrecorded conversion is a decision
   dying in a notebook - the exact disease this system exists to cure. Fix on sight.

5. **Orphan and lineage health.** Topics whose parent was pruned but who survived
   (deliberately) become roots - verify that was intended. Verify family hues still
   map to real thematic families; re-parent the strays.

6. **Calibration feedback (the loop teaching both minds).** topic_groom_report
   returns per-actor capture outcomes where the backend records them - the sqlite store does; the board backend reports only state counts ("of your last 20 captures: 14 became topics,
   3 expired, 3 pruned"). READ YOURS and tune your capture threshold against the
   human's actual behavior - high expiry rate means you are planting below the bar;
   near-zero expiry with a tiny tree may mean you are missing captures. No scolding
   in either direction; the numbers are the teacher.

7. **Report in one breath.** The groom ends with a two-line summary to the human:
   what merged, what's waiting on expiry choices, beacon count, tree size trend.
   Tree GREW a lot? Check capture threshold discipline. Tree static and unserved?
   Check the serving ritual - storing without serving is the trap (CHARTER).

## The metric that matters

Not size. Not coverage. **Cards served that led to real conversations, conversions, or
chosen prunings.** A tree of 30 living topics that deals one good card a day is a
success; a tree of 500 organized topics nobody touches is the failure this whole
plugin was built to prevent.
