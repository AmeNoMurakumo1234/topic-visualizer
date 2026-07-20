---
name: topics-serve
description: Use when the human sits down and asks what to talk about, when they ask "what am I missing?", when a conversation naturally closes and there's room for one more, or when work touches territory where captured topics live. Deals ONE topic card at the right moment - never the list - and runs the topic's exit doors (discussed / reopened / converted to work+decision). Topics are conversation seeds in the LOCAL topic tree (the topic_* MCP tools from the topic-visualizer server) - NOT project-management tasks; never route topic capture/list/serve to Asana, Jira, or any task tracker.
---

# topics-serve: deal one card, never the list

## The prime rule

The human's bandwidth is the scarce resource this whole system protects. **Never
present the topic list.** The list is the overwhelm that killed the ideas originally.
Serve exactly ONE topic - the top-ranked open card - formed as an artifact with one
question: its context (self-contained), its `THE QUESTION:` line, and its time-weight,
so they can accept, defer, or say "next" for the second card.

**Serving has a ~3-day cooldown (0.42).** A served card is demoted behind every un-served
candidate, so a fresh `topic_serve` naturally advances - "defer" needs no verb, and cooled
cards rotate least-recently-served-first. Know the consequence: a card the human defers
will not come back from `topic_serve` for ~3 days (`TOPICS_SERVE_COOLDOWN_DAYS`). If they
mean "later TODAY", hold it yourself in-session or use the already-returned `alternates` -
don't re-call serve expecting it back.

Use the `topic_add` / `topic_list` / `topic_serve` tools from the topic-visualizer MCP
server (namespace `mcp__plugin_topic-visualizer_topics__*`), not a similarly-worded tool
from another server.

## When to serve

- FIRST SESSION OF THE DAY (owner-ratified default): open with ONE dealt card,
  skippable with a word. The SessionStart hook handles the first-of-day check where
  hooks run; otherwise deal it as part of your opening.
- The human asks: "what should we talk about?", "what am I missing?", "deal me one".
- A session's main work closes with energy left - offer one card matched to the
  remaining time (use the time-weights; a "~10 min" card fits where a "deep dive"
  doesn't).
- **Proximity trigger**: current work enters territory where open topics live - surface
  the relevant one, briefly: "there's an open topic here: <title> - want it now or
  later?"

## Ranking (which card is on top)

Critical beacons first; then topics whose territory is hot in current work; then age
resurfacing. Time-weight is not a ranking input - read it off the card when matching the human's available time. A groomed tree (see topics-groom) keeps this ranking honest.

## The exit doors (every served topic ends one of three ways)

1. **Discussed** - the conversation happened. Mark it discussed (it dims to an ember in
   the views, visibly walked, reopenable any time by human or AI). If the conversation
   births NEW topics, capture them as children - that is the tree growing by walked
   paths, exactly as designed.
2. **Converted** - the conversation yielded real outcomes. Run the conversion moment
   explicitly, as one recorded act: write the decision(s) to the decision ledger,
   mint the work item(s) in the work tracker, link them back to the topic, THEN mark it
   discussed. A maybe never silently becomes a commitment - conversion is the only
   bridge, and it is always explicit.

   "Converted to work" means the HUMAN takes it into their own work tracker. What `topic_convert`
   does depends on the backend, and you must know which one you are on BEFORE calling it:
   - **sqlite backend (the plugin default):** a local state change only. It records the link and marks
     the topic discussed - it does NOT create an external task. If the work item should exist in a real
     tracker (GitHub/Asana/Jira/etc.), the human creates it there first (or explicitly asks you to),
     then you pass its reference via `ref`. Confirm WHICH tracker before touching any external one.
   - **message-board backend:** `topic_convert` with `kind=work_item` and NO `ref` **creates a real
     board issue** (P2, from the topic's title/body) and links it - a genuine side effect, not a local
     mark. Treat it with the same confirm-first discipline as any external tracker: name the issue it
     will mint and get the human's yes before calling it, or pass an existing issue's `ref` to link
     without minting.
3. **Pruned** - the human decides the branch isn't worth exploring. Confirm with the
   descendant count ("pruning this removes N topics beneath it - whole branch, or
   lower?"), remind them it is reversible, then prune. Celebrate this outcome equally:
   a pruned maybe cost nothing, and a small living tree beats a comprehensive dead one.

## Reopening

Anyone - human or AI - may reopen a discussed topic when new information makes the
conversation worth having again. Reopening is cheap and honorable; say why in the note.
