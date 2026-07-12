# The Seam: frictionless capture + serving between a human mind and an AI mind

> HISTORICAL SPEC (ratified 2026-07-11). The CODE is current where they differ:
> schema is v3 (multi-parent), beacons are set via /edit not /beacon, the tool set
> grew topic_attach, serve ranking has no time-weight input, and the PreCompact
> mortality sweep lives in the topics-capture skill (no hook channel exists).

Design spec, 2026-07-11. Brainstormed by the maintainers (superpowers:brainstorming), all
keystone decisions owner-ratified same day. This document is the WHY and WHAT; the
implementation plan derives from it.

## The insight the design serves

Friction at this seam is not a list of points - it is ONE feedback loop:

> junk capture -> human distrusts the tree -> stops serving cards -> AI sees capture
> never pays off -> capture discipline decays -> the tree dies quietly.

Spun positive it compounds: clean capture -> trusted tree -> cards served ->
conversations -> conversions pay both sides -> capture feels worthwhile. Every feature
below exists to spin the loop positive. Grounding: Horvitz, Principles of
Mixed-Initiative UI (CHI 99) - time services to attention, minimize the cost of poor
guesses, reason act-vs-defer-vs-ask.

## Ratified decisions (the keystones)

1. CAPTURE AUTHORITY: silent + soft report. The AI plants topics autonomously as they
   surface; at most one soft line at a natural pause ("planted 2 topics"). Pruning and
   the seedling valve are the safety net, not per-capture permission.
2. SERVING CADENCE: first session of the day opens with ONE dealt card (skippable with
   a word). All other pushes at boundaries only (end-of-task offers, proximity
   one-liners); "deal me one" works anytime; never interrupt mid-flow.
3. NOISE VALVE: silent captures enter as SEEDLINGS (visually smaller/dimmer).
   Untouched ~21 days -> auto-EXPIRE (server job; counted aloud in the groom report -
   death stays visible at the policy level). Touched once -> full topic,
   death-by-choice applies. PLUS: a browsable ARCHIVE (expired + pruned, searchable,
   one-tap resurrect) and a SEMANTIC SEARCH BAR filtering every view by ranked match.
4. ARCHITECTURE: hybrid - mechanism exactly at the discipline-decay points (hooks +
   server jobs); skills keep the judgment calls (threshold, beacons, conversion).
5. MORTALITY-AWARE CAPTURE (owner addition): the AI's context death is the loss event
   this tool prevents. PreCompact hook sweeps unplanted ideas BEFORE the boundary; the
   capture threshold LOWERS as context pressure rises (act-vs-defer shifts toward act
   because the cost of loss climbs). The seedling valve is what licenses the
   aggression - over-capture near death costs ~nothing.

## Components

### Server (plugin form; the mechanism)
- SQLite owner (schema.sql v2: adds 'seedling' + 'expired' states, seam-health stats).
- HTTP API: GET /api/topics (tree; ?include=archive), POST /api/topics (BATCH array;
  returns per-item near-duplicates via token-overlap so the AI merges instead of
  double-planting), POST /{slug}/state (open|discussed|pruned + cascade for prune),
  POST /{slug}/links (topic_convert: decision/work_item/document refs, atomic),
  POST /{slug}/beacon, GET /api/topics/search?q= (ranked slugs: local embedder when
  installed, keyword/BM25-ish fallback always), GET /api/topics/health (the four vital
  signs: capture/serve/conversion/prune+expiry rates), GET /api/topics/serve?context=
  (ONE card + 2 alternates; ranking = beacons > territory match > age-decay
  resurfacing > time-weight fit).
- Jobs: seedling expiry (on startup + daily); beacon-ratio soft warning (>~10%).
- MCP tools mirror HTTP exactly: topic_add (batch), topic_serve, topic_state,
  topic_convert, topic_search, topic_groom_report.

### Hooks (plugin form; the structural nets)
- SessionStart: first-of-day check -> deal one card into context.
- Stop: session-end sweep - "anything topic-worthy not yet planted?"
- PreCompact: the mortality sweep - "ideas at risk of being lost to summarization -
  plant them NOW, liberally."

### Web (canonical in this repo; board vendors)
- SEARCH BAR in the shell header: filters all three views live; matches full
  brightness with labels FORCED visible (search overrides the semantic-zoom label
  budget); non-matches dim to ~15% ghosts (structure stays legible); Esc clears.
  Client-side keyword scoring is the universal fallback (works on any adapter);
  server /search upgrades to semantic when present.
- QUICK-ADD box (the human's two-second door; new root or child of selected).
- Panel EDIT (title/body) + RE-PARENT + beacon toggle.
- ARCHIVE explorer (expired + pruned; searchable; resurrect button).
- SEAM-HEALTH strip (the four rates, small, honest).
- Seedling visual state: smaller/dimmer node + "seedling" chip; touched -> full topic.

### Skills (the judgment layer)
- topics-capture: silent+report policy; graduated mortality threshold; batch at
  pauses; seedling framing.
- topics-serve: first-of-day ritual; boundary-only offers; active-topic session
  linkage (children auto-parent; end-of-session state proposal); atomic conversion.
- topics-groom: calibration feedback both directions ("of your last 20 captures: 14
  became topics, 3 expired, 3 pruned" - the AI tunes its own threshold); expiry
  counts; beacon audit.

### The dignity symmetry
The groom report teaches the AI from the human's actual behavior (no scolding); the
AI's silent capture respects the human's bandwidth. Neither side is plumbing. This is
the tool's soul; features that break the symmetry get declined.

## Deployment split (honest asymmetry)
- Plugin: full mechanism (hooks + MCP + server jobs + search endpoint).
- QC/board instance: same core+views vendored; adapter-board approximates - seedling
  as a `stage: seedling` body tag, expiry via the PM groom, hooks as agent wake/close
  ritual lines, search via the client-side fallback. Weaker, documented, acceptable:
  disciplined agents vs strangers.

## Not building (YAGNI)
No cloud sync; no multi-user permissions; no conversation-transcript storage (topics
only - privacy is structural); NEVER auto-topic-generation (lazy growth is law); no
mobile app.

## Success criteria
The seam-health strip trends positive over weeks of real use: captures that survive
seedlinghood, cards served that become conversations, conversions recorded, prunings
chosen. Secondary: neither side opts out - the human keeps serving, the AI keeps
planting, without reminders.
