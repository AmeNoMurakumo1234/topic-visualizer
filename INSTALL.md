# Install

The repo doubles as its own plugin marketplace (`.claude-plugin/marketplace.json` at
the root, plugin source in `plugin/`). Two commands in any Claude Code session:

```
/plugin marketplace add F:\writing\plugins\topic-visualizer
/plugin install topic-visualizer@topic-visualizer
```

(From GitHub instead: `/plugin marketplace add <owner>/topic-visualizer`.)

Validate the manifest any time with `claude plugin validate ./plugin`.

## What you get, immediately

- **MCP tools, zero setup.** `topic_add`, `topic_serve`, `topic_search`,
  `topic_state`, `topic_convert`, `topic_groom_report`. No server needs to be
  running: the tools fall back to direct SQLite at `${CLAUDE_PLUGIN_DATA}/topics.db`
  (survives plugin updates). If the topics server IS running they pass through it -
  same store, same behavior.
- **Skills**: `topics-capture` (silent capture at the fork; mortality-aware near
  compaction), `topics-serve` (one card, first session of the day), `topics-groom`
  (the gardener's round, evidence-calibrated).
- **Hooks**: SessionStart serves the first-of-day card; Stop and PreCompact remind
  the AI to sweep unplanted seedlings - the mechanism at the discipline-decay points.

## Seeing the tree (the human half)

```
python <plugin>/server/server.py --db <CLAUDE_PLUGIN_DATA>/topics.db
```

It prints the URL (default http://127.0.0.1:8991) - three views over your tree:
Constellation, Lineage, Star Chart. Localhost only. The plugin never phones home;
your maybes are yours.

## Configuration (env, all optional)

| Variable | Default | Meaning |
|---|---|---|
| `TOPICS_DB` | `${CLAUDE_PLUGIN_DATA}/topics.db` | SQLite path (MCP direct fallback) |
| `TOPICS_SERVER_URL` | `http://127.0.0.1:8991` | running topics server, if any |
| `TOPICS_EMBED_URL` | `http://127.0.0.1:8082` | OpenAI-style `/v1/embeddings` endpoint; semantic search/dedup when up, keyword fallback when not |
| `TOPICS_BACKEND` | `server` | `board` swaps every tool onto a message-board backend (topics as `OPEN THREAD` posts) |
| `TOPICS_BOARD_URL` / `TOPICS_BOARD_PROJECT` / `TOPICS_BOARD_AUTHOR` | - | board backend knobs |
| `TOPICS_ACTOR` | `ai` | actor stamped on MCP writes |

## Uninstall / disable

`/plugin uninstall topic-visualizer` - or disable it and keep using your own
integration (this machine's message-board Topics tab is exactly that: the same
vendored views over a board adapter).
