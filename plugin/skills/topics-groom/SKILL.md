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

0. **Checkpoint FIRST - always, before you change anything.** A groom is the one bulk,
   hard-to-eyeball edit, so it opens with a safety net: call **`topic_checkpoint`** (label it,
   e.g. `pre-groom 2026-07-13`) before the first merge/reparent/prune. That snapshot is the
   human's undo. If they dislike the result, **`topic_restore`** (or the visualizer's **Undo last
   groom** button) rolls the tree back to exactly this point - reparents and merges fully reverse,
   merged-away topics return, and anything captured DURING the groom is KEPT, never discarded. No
   checkpoint, no reshape: this step is not optional. (Checkpoints are a sqlite-backend feature;
   on the board backend the tool returns "not supported" and you simply groom without one.)

1. **Duplicates and near-misses.** Topics phrased differently but asking the same
   question get merged (keep the better-formed one; note the merge). `topic_list` to see
   them all; `topic_get` to compare two bodies before merging. This is also where the
   synonym gap shows - if search keeps missing kin topics, that is the signal to add
   semantic indexing, not before. When enumeration turns up near-duplicates, hand off to
   the **topics-reconcile** skill (`topic_duplicates` -> `topic_get` both ->
   `topic_merge`/`topic_attach`) rather than merging by hand - it carries the
   survivor-picking and propagation discipline.

2. **Expiry candidates - by choice, never by silence.** A topic un-ENGAGED for ~a month
   is a candidate, not a casualty (as of 0.42 the clock is engagement: a card merely
   served, or moved during a reshape, but never actually worked with, still qualifies). Present candidates to the human ONE at
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

5. **Shape the tree - BREADTH is the alarmed axis; DEPTH is unbounded (owner call, 2026-07-20).**
   `fan_out.breadth_warning` trips when roots sprawl (> `root_warn_at`) or any hub goes over-wide
   (`over_wide`) - that warning IS the groom trigger for this step. There is **NO max depth and no
   depth warning, by design**: a 5-deep chain of genuine sub-questions is a healthy tree, and the
   cure for a breadth warning is always real depth (merge twins, nest sub-questions under the
   sibling they refine) - never a flatten. The trap in the other direction still stands: don't fix
   width by inventing hubs ("aim for 3-7" hit by manufacturing siblings produces a shallow, wide,
   incoherent tree that PASSES the metric and still reads as "weird"). Lead with the relationships
   already in the graph.

   > **Propose the axis, THEN apply - never impose your own taxonomy silently.** The reshape (new
   > hubs, reparents, merges) applies a POINT OF VIEW about how the tree should be organized, and the
   > human's "this looks weird" is precisely the judgment the metric can't encode. So DRAFT the plan
   > first - "I'd nest X and Y under #110, merge A into B, add one 'floor' hub; here's the organizing
   > axis" - put it to the human, let them ratify or adjust the AXIS, and THEN apply. Similarity
   > proposes; a human ratifies the axis. The step-0 checkpoint makes trialing safe, but ratify the
   > SHAPE before you spend the human's trust on it. (The mechanical steps - merging obvious
   > duplicates, recording conversions, expiry choices - don't need this; the TAXONOMY reshape does.)

   **The avenue IS the depth signal - use it first.** An extra parent (avenue) between two SIBLINGS
   almost always means one topic is a sub-question or complement of the other - so it belongs UNDER
   its sibling, not beside it. `topic_groom_report`'s `coherence.reparent_hints` lists exactly these
   pairs (child + suggested_parent + the avenue's note). Work them FIRST:
   `topic_reparent {slug: child, parent_slug: suggested_parent}`. **Real relational depth OUTRANKS
   the 3-7 fan target** - a #110-centered branch with its sub-questions nested reads right; a flat
   hub of ten "peers" that are actually related does not.

   **Then the rest of shape, in order:**
   - **MERGE duplicates** (step 1) - a wide fan is very often just twins the tree never collapsed;
     the single biggest lever, and it deepens by removing false peers.
   - **NEST only REAL facets**: `topic_add {..., role:'hub'}` a hub (its `parent_slug` sets a real
     primary parent at birth; `role:'hub'` marks it as organizing scaffolding, NOT a captured
     question - so an undo can sweep it clean if empty, and junk-drawer detection knows it's a
     container), then `topic_reparent` the children that share an undeniable theme under it. **Depth
     follows the data** - surface however deep the real structure runs, never manufacture layers to
     look tree-ish; false precision is its own rot.
   - **REPARENT the mis-placed** (`topic_reparent {slug, parent_slug}`, batch `items:[...]`): a topic
     captured under whatever conversation birthed it often sits far from its true home (chronology,
     not meaning). Safe at groom time because you hold the whole tree in view; capture (correctly)
     does not.

   **Coherence, not just width** (`coherence` in the report + your own read - width is necessary,
   never sufficient):
   - **redundant ancestor parent** (`redundant_parents` - the strongest, near-certain signal): a card
     with two parents where one is an ANCESTOR of the other reaches that ancestor TWICE (directly, and
     transitively via the parent that is the ancestor's descendant), so the direct edge is a duplicate
     longer path. **Keep the parent that is the DESCENDANT (the child-side) of the other - NOT "the
     nearer" one, specifically the one that is a child/descendant of the other parent - and drop the
     ancestor edge.** The card then hangs off that descendant parent alone and is the ancestor's
     grandchild through it. The report hands you `keep_parent` (the descendant to keep) and
     `redundant_parent` (the ancestor to drop). Action: if the ancestor is the card's current PRIMARY,
     `topic_reparent {slug: child, parent_slug: keep_parent}` (it collapses the now-redundant avenue
     and drops the old primary edge); if the ancestor is an AVENUE, `topic_attach {slug: child,
     parent_slug: redundant_parent, remove: true}`. Unlike the sibling hint below, this needs no
     judgment - it's a provable duplicate.
   - **avenue-between-siblings** -> reparent (above); the report computes these.
   - **junk-drawer nodes** (`possible_buckets`): a parent whose title is a BUCKET, not a question
     ("conversations we haven't had", "misc") hides a real sub-cluster - open it, reparent the
     members to true homes.
   - **root orphans near a hub** (`coherence.root_orphan_hints`, 0.42 - the most common real
     grooming action): a topic captured at ROOT (chronological capture, not meaning) that
     semantically belongs under an existing hub. Each hint is {orphan, hub, score}; propose the
     move, the human ratifies, then `topic_reparent`. SEMANTIC-ONLY: when the embedder is down
     the list is honestly absent (`root_orphan_note` says so) - absence of hints is then NOT
     evidence the roots are fine; eyeball `fan_out.root_count` yourself.
   - **mixed-altitude / mixed-voice siblings** (judgment - the report can't compute it): children at
     different levels of abstraction, or in different phrasings, under one parent -> re-level them
     (`topic_edit` to rename/rephrase a title, `topic_reparent` to re-nest).
   - **one theme split across two siblings** (judgment): the same story under two hubs, or two
     clashing taxonomies at one level (your invented hubs beside pre-existing territory nodes) ->
     merge the hubs / conform to ONE axis.

   > **Reshape with `topic_reparent`, NOT `topic_attach`.** attach only overlays an extra avenue (a
   > cross-link) - the member stays put and the spine doesn't move. Moving a topic's home is
   > `topic_reparent` (sqlite backend; the board's primary parent lives in an immutable post body).
   > `topic_add`'s `parent_slug` sets a real primary parent, so the flat-plant gap only bites
   > EXISTING topics during a groom.

   > **When you DO keep an avenue, its `kind` is your JUDGMENT** - similarity can't tell a complement
   > from noise (a genuine complement scores like an unrelated pair to the embedder). An avenue
   > defaults to `co_parent` (you attached it because you saw a real link) and RENDERS as a real
   > second parent - solid, and in Constellation the node is pulled BETWEEN its parents. Mark
   > `topic_attach {..., kind:'see_also'}` only for a genuinely weak aside; that one stays a quiet
   > dashed link. The three-way call: a true sub-question becomes a CHILD (`topic_reparent`); a true
   > co-equal facet stays a `co_parent` avenue; only a weak aside is `see_also`.

   Semantic similarity PROPOSES; your JUDGMENT decides which clusters are real - an autonomous
   similarity-only regroup is worse than no grooming (it picks the wrong axis). Also: orphans whose
   parent was pruned but survived - verify that was intended; family hues still map to real families.

6. **Calibration feedback (the loop teaching both minds).** topic_groom_report
   returns per-actor capture outcomes where the backend records them - the sqlite store does; the board backend reports only state counts ("of your last 20 captures: 14 became topics,
   3 expired, 3 pruned"). READ YOURS and tune your capture threshold against the
   human's actual behavior - high expiry rate means you are planting below the bar;
   near-zero expiry with a tiny tree may mean you are missing captures. No scolding
   in either direction; the numbers are the teacher.

7. **Report in one breath.** The groom ends with a two-line summary to the human:
   what merged, what's waiting on expiry choices, beacon count, tree size trend.
   Tree GREW a lot? Check capture threshold discipline. Tree static and unserved?
   Check the serving ritual - storing without serving is the trap (CHARTER). Close by
   reminding them the reshape is reversible: `topic_restore` (or the **Undo last groom**
   button) rolls back to the checkpoint you took in step 0, keeping anything captured since.

## The metric that matters

Not size. Not coverage. **Cards served that led to real conversations, conversions, or
chosen prunings.** A tree of 30 living topics that deals one good card a day is a
success; a tree of 500 organized topics nobody touches is the failure this whole
plugin was built to prevent.
