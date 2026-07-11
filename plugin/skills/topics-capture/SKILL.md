---
name: topics-capture
description: Use during any conversation when a substantive topic surfaces that cannot be pursued now - an idea the human waves past, a sibling of the thing being discussed, a question you (the AI) believe deserves real future attention. Captures it into the topics tree so it survives the session instead of dying in scrollback. Also governs when NOT to capture.
---

# topics-capture: plant what would otherwise die

## When a topic is born

A topic enters the tree at the moment it surfaces and is *not pursued* - not at session
end from memory (too late, too lossy). The classic births:

- You presented N options/findings/questions; the human picked one. The others that pass
  the threshold (below) each become a topic **now**.
- Mid-conversation, a genuinely new question opened and was deliberately set aside
  ("later", "not now", "interesting but...").
- You, the AI, believe something deserves discussion the human hasn't noticed. Capture
  it - and if it truly matters, set the beacon (below).

## The capture threshold (most things do NOT earn a node)

Capture only if **a real future conversation about it would change what gets built or
decided**. "Interesting" is not the bar; losing-it-would-cost-something is the bar.
When in doubt, and the human is present, one line: *"worth keeping X as a topic?"*

**Never speculatively farm topics.** Generating topic lists ("here are 50 things we
could discuss about cars") is forbidden - the tree grows only by walked paths. This
single rule is what keeps the tree bounded by real attention and prevents the
graveyard failure (see the repo CHARTER).

## How to capture (the record)

Each topic is self-contained - written for a future session with zero context:

- **Title**: the topic as a question or tension where possible, with a time-weight tag:
  `(~10 min)`, `(~1 hour)`, `(errand)`, `(deep dive)`.
- **Body**: 3-5 sentences of context (why it matters, where it came from), then
  `THE QUESTION:` - the one question a future conversation must answer.
- **Parent**: the topic it branched from, if it was born inside another topic's
  conversation. Root topics are fine and normal. One parent maximum; use tags for
  cross-cutting themes. Never force a hierarchy at capture time.
- **Provenance**: date + which conversation/work surfaced it.

## The beacon (use sparingly)

If you, the AI, judge a topic *critical* - "we really should talk about THIS" - mark it
`priority: critical`. It will pulse in every view. The signal is only worth something
while it is rare: a tree full of beacons has none. Expect to set it roughly once per
many captures, and be ready to defend it when asked.

## What capture is NOT

- Not a work item. If the human has clearly *decided to do* something, it belongs in
  the work tracker, not here. Topics are might-not-do.
- Not a decision. If the human just *ruled* on something, it belongs in the decision
  ledger. Topics are not-yet-decided.
- Not a note-to-self dump. If it fails the threshold, let it go. Most passing thoughts
  should die; that is healthy.
