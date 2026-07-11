# Install

**Not yet installable - pre-release foundation.** This document will carry the real
flow once the server ships (see [ROADMAP.md](ROADMAP.md)). The intended shape, so you
know where this is going:

1. Install the plugin (Claude Code plugin marketplace or `claude plugin` CLI, same
   flow as the sibling Mind Coherence Suite).
2. First run creates `topics.db` next to your project (or at a configured path) and
   starts the local topics server (localhost only).
3. Open the Topics page in your browser (the server prints the URL) - three views,
   one tree, initially empty.
4. Work with Claude normally. The `topics-capture` skill plants unpursued topics as
   they surface; ask "deal me one" any time (`topics-serve`); run `topics-groom`
   weekly.

The plugin never phones home; everything is local. Your maybes are yours.
