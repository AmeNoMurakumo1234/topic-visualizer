# Topic Visualizer

A Claude Code plugin that keeps the conversations you *haven't had yet* from dying.

## The problem

You're working with an AI. It comes back and says: *here are 4 things - or 7 things - 
worth talking about.* You follow one. It turns into a full session, a good one. The
other six just got lost.

Sure, you could file them as tickets - but a ticket **lies**: it declares an intent to
*do work* when what you actually had was a conversation that needed to happen - one that
might yield work, or a decision, or nothing at all. There was no home for
*might-not-do*. So the ideas died in scrollback, session after session, forever.

This plugin is that home.

## What it is

- **A topics ledger** - a local SQLite tree of conversation topics. Every AI session can
  plant topics into it: things surfaced but not pursued, each a node with a parent, so
  ideas keep their lineage as they branch.
- **Three visualizations of the same tree**, freely switchable, because no single layout
  answers every navigational instinct:
 - **Constellation** - a force graph. Answers *"what does my idea space look like?"*
 - **Lineage** - a collapsible left-to-right tree. Answers *"let me work this branch."*
 - **Star Chart** - a radial focus+context view (after the classic hyperbolic-browser
    work: Lamping/Rao/Pirolli, CHI '95): the focused topic is the sun, children orbit,
    deeper content compresses into "+N deeper" halos. Answers both questions at once.
- **A visual state language**, consistent across all three views:
 - **Frontier leaves** (crisp sparkles) - the deepest mapped layer, the unexplored edge.
 - **Critical beacons** (pulsing rings) - topics the AI marks as *"we really should talk
    about THIS."*
 - **Discussed embers** (dimmed, reopenable) - visible progress: see at a glance which
    regions of your thinking you've walked and which are still dark.
 - **Pruned** topics leave the map - by your explicit choice, with a descendant-count
    warning first, reversibly.
- **Family hues** - every root lineage gets its own color; its whole constellation,
  edges, and nebula fog inherit it. You'll know one nebula of ideas from another at any
  zoom, before reading a single word.
- **Semantic zoom** - labels are *readable or absent*, never soup: constant screen size,
  culled by importance as you zoom out, like city names on an atlas.
- **The exit doors** - a topic ends in exactly one of three ways: **pruned** (chose not
  to explore; costs nothing, cancels nothing), **discussed** (the conversation happened;
  reopenable), or **converted** - resolved into real work items and/or a recorded
  decision that future agents follow as process or policy. Conversion is explicit and
  logged; a maybe never silently becomes a commitment.

## The ontology (why this is not a todo list)

Ideas move through three stores, and the boundaries are load-bearing:

> **EXPLORING** (this plugin: might-not-do) -> **DECIDED** (a decision ledger) ->
> **ACTING** (your work tracker: decided-to-do)

Work trackers hold committed intent. Decision ledgers hold settled calls. Topics hold
*maybes* - and a maybe that looks like a work item becomes a landmine some future agent
builds. This tool exists precisely so the maybe-space never masquerades as the
committed-space. Read [CHARTER.md](CHARTER.md) - it is the soul of the thing.

## Status

**Pre-release: foundation.** The full working prototype runs today against a message
board backend (its birthplace); this repo is the generalized plugin form. See
[ROADMAP.md](ROADMAP.md) for the port plan and [server/](server/) for the storage
design. The prototype views live in [web/prototype/](web/prototype/) with provenance.

## Contents

- [CHARTER.md](CHARTER.md) - the philosophy; read before adopting
- [plugin/](plugin/) - the Claude Code plugin (manifest + skills)
- [server/](server/) - storage schema + API design (the adapter target)
- [web/prototype/](web/prototype/) - the three views, working snapshot
- [ROADMAP.md](ROADMAP.md) - what's built, what's next
- [INSTALL.md](INSTALL.md) | [CONTRIBUTING.md](CONTRIBUTING.md)

## Provenance

Born 2026-07-10/11 inside the Quantum Concepts project, designed in one sustained
human-AI collaboration: the human named the losses ("the other six things just got
lost"), the AI built running variants, the human reacted; four rounds, one day. The
mechanism this plugin implements was used to design itself - the idea for the plugin
lives as a critical beacon in the tree it describes. Sibling project: the
[Mind Coherence Suite](https://github.com/), maintained with the same care.
