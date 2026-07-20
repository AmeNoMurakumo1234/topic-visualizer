# 0.42 "fight staleness" — design

Date: 2026-07-20. Driver: field feedback from the first substantive working session
(Eric + Assay, v0.41.1: full groom 32→13 roots, a serving pass, ~21-topic reconcile
against a shipped GitHub board). Every claim in the feedback was verified against
source before this design; two were stronger than reported.

Scope ratified by the owner: Assay's six agent-side frictions + the joint staleness
asks + Eric's hide-discussed toggle. General visual-discovery polish deferred to its
own pass. Already shipped separately: 0.41.2 (topics-serve skill no longer claims
`topic_convert` is side-effect-free; both backends documented, confirm-first on the
board mint path).

## The root defect (one bug wearing three hats)

`topic.touched_at` conflates three meanings — structural edit, served-impression,
genuine engagement — and `_touch()` fires on all of them:

- `edit_topic` calls `_touch` unconditionally (server.py:1285), so a reparent — even a
  no-op reparent — graduates a seedling. That is Assay's "reshaping graduated 13
  seedlings" (#6).
- `serve_card` writes `touched_at = now` (server.py:1434), so serving a card removes it
  from the stale list. A topic served ten times and discussed zero times looks
  permanently fresh: the "N opens untouched while unserved" metric is not merely
  missing, it is uncomputable because serving launders the evidence. This is stronger
  than what the feedback claimed (#1/#4).

Fixing the field's semantics first makes the staleness alarm honest and the serve
cooldown natural; #1, #2 (graduation), and #4 collapse into one change.

## 1. Timestamp semantics (keystone — approach A, owner-ratified)

Two new columns on `topic`, `ALTER TABLE ADD COLUMN`:

- **`engaged_at`** — last genuine engagement with the *idea*: capture, title/body
  edit, deliberate state change (open/discussed/reopen/prune), convert,
  priority/beacon change. These writers also graduate seedlings.
- **`served_at`** — last time serve showed the card. Nothing else writes it; it
  graduates nothing.
- **`touched_at`** — keeps meaning "last write of any kind" (structural
  reparent/attach included) for UI display and back-compat, but **serve stops writing
  it** and **`_touch()` stops graduating** — graduation moves to the engagement
  writers.

Migration backfills `engaged_at = touched_at` (least-wrong for existing rows) and
`served_at` from the newest `served` event per topic. The event log remains the audit
trail; columns are the fast current-state cache.

## 2. Serve: implicit cooldown (owner-ratified over an explicit defer verb)

`rank_candidates`: the age bonus reads `engaged_at`; a card whose `served_at` is
within the cooldown window (default 3 days, `TOPICS_SERVE_COOLDOWN_DAYS`) takes a
demotion large enough to fall behind any un-served candidate — unless it is the only
live candidate (never serve a blank). Re-serve after a human defer therefore just
advances. Board backend: no board schema change — the MCP layer keeps a serve-memory
sidecar (state-dir JSON keyed by backend+slug) so cooldown works for agent-driven
serving on both backends; sqlite web serving uses the server-side column.

## 3. Staleness becomes the loudest health signal

`health()` gains a `staleness` block, FIRST key in the report (beacon ratio demoted
below it): `served_30d:live` ratio, `stale_open_count` (open AND `engaged_at` older
than 30d — honest now), `never_served_count`, boolean `staleness_warning`.
`expiry_candidates` gains a total count (not just LIMIT-3 samples). `expired: 0`
gains a companion distinguishing "nothing rotted" from "expiry never evaluated
anything."

Proactive nudge: the existing SessionStart first-of-day hook adds one line when
`staleness_warning` is true — "N stale opens, served:live is X — want a reconcile
pass?" No new hook.

## 4. `topic_reconcile` bulk verb + tracker-reconcile skill (owner-ratified)

> Erratum (0.42.0 ship): the skill shipped as **`topics-tracker-reconcile`** - the name
> this section originally used collided with the existing `topics-reconcile` import-dedup
> skill and briefly overwrote it during implementation (caught in review, restored).

New MCP tool: batch of `{slug, disposition: discussed|pruned|converted, ref?, note?}`
→ each applied atomically via existing state machinery, event-logged `reconciled`,
per-item results (a bad slug fails that item, not the batch). The skill codifies:
pull open topics → match against the tracker with the agent's own tools → human
ratifies the mapping → one call. Matching stays the agent's job; the plugin never
grows tracker integrations. Decided against (owner default stands): sqlite-side issue
minting.

## 5. Root-orphan → nearest-hub hints

`groom_report()` gains `root_orphan_hints`: each root topic's title+body embedding
vs each hub (topic with ≥2 children) via the existing `TOPICS_EMBED_URL` infra;
emit `{orphan, hub, score}` above threshold, cap 10, sorted by score. Embedder down →
`[]` plus `semantic: "unavailable"` — no keyword fallback (an honest "can't compute"
beats a bad guess; misleading emptiness is the bug being fixed). [Judgment call,
presented and approved.]

Why the existing hints missed: `reparent_hints` requires `c.parent_id IS NOT NULL`
(roots structurally excluded), `redundant_parents` needs ≥2 parents, and
`groom_report` never calls the embedder at all — 32 roots produced zero hints by
construction, not by tuning.

## 6. Cross-surface visibility

`groom_report()` and `health()` gain `recent_human_activity`: last-7d events with
`actor='human'` — `{slug, event, at}`, cap 20. Deferred as YAGNI: per-agent read
watermark / `changed_since` param. [Judgment call, presented and approved.]

## 7. Hide-discussed toggle (Eric)

Per-view toggle in Lineage and Star Chart filtering discussed/ember nodes, persisted
in localStorage like the remembered-view choice. Constellation untouched.

## 8. Testing & release

Stdlib-unittest additions in the existing pattern: graduation classification
(structural vs engagement, incl. the no-op reparent), cooldown ordering + the
only-candidate override, reconcile batch semantics (partial failure), staleness math
incl. backfill, hint behavior with embedder down, recent_human_activity actor
filter. Full 7-suite pass before release. One bump to **0.42.0** across the 3
lockstep fields; single-line commits under the owner's identity; marketplace-update
reminder at the end. Review passes after implementation until clean (owner ask).

Out of scope: sqlite-side issue minting, general visual polish, board-backend
seedling/reparent parity.
