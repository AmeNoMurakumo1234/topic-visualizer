# Installing the Topic Visualizer

This repo is both a Claude Code marketplace and the `topic-visualizer` plugin it
hosts. Source of truth: `https://github.com/AmeNoMurakumo1234/topic-visualizer`.

## TL;DR

1. Add the marketplace `AmeNoMurakumo1234/topic-visualizer`.
2. Install the `topic-visualizer` plugin.
3. The MCP tools + skills + hooks work immediately; run the bundled server any time
   to browse your tree in the three views.

## Quick start (terminal CLI)

If you do not already have the Claude Code CLI: install it (Node.js 18+) with
`npm install -g @anthropic-ai/claude-code` (or the native installer / Homebrew /
WinGet; see the official [setup guide](https://code.claude.com/docs/en/setup)),
run `claude`, and log in.

Then add this marketplace + install the plugin straight from GitHub - no clone
needed. From any terminal:

```
claude plugin marketplace add AmeNoMurakumo1234/topic-visualizer
claude plugin install topic-visualizer@topic-visualizer
```

Inside a running `claude` session, use the slash forms instead:

```
/plugin marketplace add AmeNoMurakumo1234/topic-visualizer
/plugin install topic-visualizer@topic-visualizer
```

**Pin it in a repo (declarative).** Commit a `.claude/settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "topic-visualizer": { "source": { "source": "github", "repo": "AmeNoMurakumo1234/topic-visualizer" } }
  },
  "enabledPlugins": { "topic-visualizer@topic-visualizer": true }
}
```

**Desktop app.** Manage plugins from the **+ button -> Plugins**. Adding a new
custom (non-official) marketplace may require the CLI / integrated terminal on
some builds; the commands above work there too.

## What you get, immediately

- **MCP tools, zero setup.** `topic_add`, `topic_serve`, `topic_search`, and ten more
  (`topic_get`/`list`/`state`/`convert`/`attach`/`groom_report`/`export`/`import`/`merge`/
  `duplicates`) - thirteen in all. No server needs to be running: the tools fall back to direct SQLite at
  `~/.topic-visualizer/topics.db` (a plain file in your home dir, created on first
  capture; survives plugin updates). If the topics server IS running they pass
  through it - same store, same behavior.
- **Skills**: `topics-capture` (silent capture at the fork; mortality-aware near
  compaction), `topics-serve` (one card, first session of the day), `topics-groom`
  (the gardener's round, evidence-calibrated).
- **Hooks**: SessionStart serves the first-of-day card (works with no server
  running - direct sqlite fallback); Stop runs a ONE-per-session capture sweep.
  The pre-compaction mortality sweep lives in the topics-capture skill (the
  PreCompact hook event has no model-visible channel).
- **Prerequisite**: `python` (3.10+) on PATH - the MCP server and hooks run it.

## Seeing the tree (the human half)

The MCP tools capture and serve without any UI. To browse your tree in the three
views, run the bundled server - with no arguments it opens the same store the AI
captures into (`~/.topic-visualizer/topics.db`):

```
python "<plugin-dir>/server/server.py"
```

`<plugin-dir>` is wherever Claude Code installed the plugin (run
`claude plugin list` to see the path; it lives in the plugins cache under your
Claude config dir). It prints a localhost URL (default `http://127.0.0.1:8991`) -
Constellation, Lineage, Star Chart over your tree, localhost only. Point it at a
different file with `--db /path/to/other.db` if you keep more than one tree. The
plugin never phones home; your maybes are yours.

Prefer to kick the tires before installing? See the demo in the
[README](README.md#try-it-in-two-minutes-demo-mode) - synthetic, deterministic,
never stored.

## Configuration (all optional - sensible defaults, nothing to set up)

You do not need to set any of these; they are overrides for power users. Defaults
work out of the box.

| Variable | Default | Meaning |
|---|---|---|
| `TOPICS_DB` | `~/.topic-visualizer/topics.db` | SQLite path (MCP direct fallback) |
| `TOPICS_SERVER_URL` | `http://127.0.0.1:8991` | running topics server, if any |
| `TOPICS_EMBED_URL` | `http://127.0.0.1:8082` | OpenAI-style `/v1/embeddings` endpoint; semantic search/dedup when up, keyword fallback when not |
| `TOPICS_BACKEND` | `server` | `board` swaps every tool onto a message-board backend (topics as `OPEN THREAD` posts) |
| `TOPICS_BOARD_URL` / `TOPICS_BOARD_PROJECT` / `TOPICS_BOARD_AUTHOR` | - | board backend knobs |
| `TOPICS_ACTOR` | `ai` | actor stamped on MCP writes |

## Uninstall / disable

`/plugin uninstall topic-visualizer` - or disable it and keep using your own
integration ([INTEGRATING.md](INTEGRATING.md) shows how to embed the views in
another app).

## Contributing / building from source

Cloning is only for contributors, not consumers. `claude plugin validate ./plugin`
checks the manifest; the repo doubles as its own marketplace (root
`.claude-plugin/marketplace.json`, plugin source in `plugin/`).
