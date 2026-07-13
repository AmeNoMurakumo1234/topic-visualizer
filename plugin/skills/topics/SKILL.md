---
name: topics
description: The always-on discipline for the topic tree - the "might-do" space that keeps the conversations you haven't had yet from dying in scrollback. Load this to orient to the WHOLE lifecycle and know which tool to reach for; it points to the task skills rather than repeating them. Trigger whenever unpursued ideas surface in a session, when the human mentions topics / the tree / the visualizer, when you need the capture reflex, how a topic becomes work, or how to check the system's health.
---

# topics: the discipline of the might-do tree

Topics are the home for **might-do** - the idea worth keeping that you cannot pursue now. Your work
tracker holds what was DECIDED; the topic tree holds what you MIGHT pursue. **Never blur them:** a maybe
that looks like a commitment becomes a landmine a future agent builds, and counting maybes makes every
health signal lie.

## The reflex (always on)

- A fork worth keeping surfaces and cannot be pursued now -> **capture it**. The bar is "losing it would
  cost something," not "interesting." Capture SILENTLY as a seedling (it auto-expires in ~3 weeks, so a
  wrong capture costs almost nothing). Full threshold + record shape: the **topics-capture** skill.
- **Never speculatively farm** ("50 things we could discuss about X"). The tree grows only by walked
  paths - bounded by real attention, never by brainstormed lists.
- The same topic reached from a second conversation -> **attach**, never a twin.

## The lifecycle (which tool)

- **capture** unpursued ideas as they surface -> `topics-capture`
- **serve** one card at the start of a session / when there's energy -> `topics-serve`
- **convert** a topic into a work item or a recorded decision - the ONLY bridge from might-do to
  committed; a maybe never silently becomes a promise
- **groom** the tree (merge dupes, expire the stale, verify conversions got recorded) -> `topics-groom`;
  reconcile drift between the tree and the work it spawned -> `topics-reconcile`

## Health (if the tree, visualizer, or search looks off)

- **`topic_doctor`** - says LOUDLY whether the plugin is at full value or silently degraded (server not
  persisting, or semantic ranking off / keyword-only). A non-empty `degraded` list means act.
- **`topic_open`** - ensure the visualizer host is up and get its URL (so the web tree is one call away).
- First run, or anything degraded -> the **topics-setup** skill wires persistence + a bundled embedder +
  project scope in one guided pass, and ends on a green doctor.
- Leaving? Run **topics-teardown** BEFORE uninstalling - it stops our processes and removes the autostart
  so nothing is orphaned (no failing login task, no ghost holding a port). We release as gracefully as we
  onboard.

## The metric

Served cards that became real conversations, conversions, or chosen prunings - **never store size.** A
small living tree beats a comprehensive dead one; celebrate prunings.
