# The server - one small process, two faces over one SQLite store

`server.py` is the plugin's storage + brain: a stdlib-only process (no pip installs)
that owns all writes to `topics.db` and serves the web views. `mcp_tools.py` is the
AI-side face: a stdio MCP server that passes through to the HTTP API when the server
is running and falls back to DIRECT in-process sqlite when it is not - capture works
with zero setup either way, against the same store.

```
python server.py [--db topics.db] [--port 8991] [--web ../web]
```

## HTTP surface (what the web adapter and hooks call)

| Method + path | Does |
|---|---|
| `GET /api/topics[?include=archive]` | every topic (+ pruned/expired ghosts with archive) |
| `GET /api/topics/search?q=` | ranked search: facet words filter, rest ranks semantically (embedder up) or by keyword |
| `GET /api/topics/serve?context=` | ONE card + 2 alternates (beacons > territory fit > age decay); resurfaces but never graduates a seedling |
| `GET /api/topics/health` | seam vital signs (captured/served/converted/pruned/expired, beacon ratio) |
| `GET /api/topics/groom` | health + per-actor capture calibration + expiry candidates |
| `POST /api/topics` | batch capture `{actor, topics: [...]}` -> per-item `{slug, near_duplicates}` |
| `POST /api/topics/{slug}/state` | `{state: open|discussed|pruned, actor, note, cascade?}` - prune verifies the client-confirmed cascade and SPARES multi-parent survivors |
| `POST /api/topics/{slug}/links` | atomic conversion `{links: [{kind: decision|work_item|document, ref, note}], actor}` |
| `POST /api/topics/{slug}/edit` | `{title?, body?, parent_slug? ("" = root), critical?}` - re-parent is cycle-guarded over the full DAG |
| `POST /api/topics/{slug}/attach` | multi-parent: `{parent_slug, note, remove?}` - adds an extra avenue + the rediscovery enrichment |
| `GET /` + static | serves the web views from `--web` |

Beacons are set via `edit` (`critical: true/false`). Seedlings auto-expire after
~21 untouched days (daily job); everything stays browsable and resurrectable in the
archive.

## MCP surface (mcp_tools.py)

Seven tools: `topic_add`, `topic_serve`, `topic_search`, `topic_state`,
`topic_convert`, `topic_attach`, `topic_groom_report`. Two backends behind the same
contract (`TOPICS_BACKEND=server|board`); the board backend maps topics onto
message-board posts and reuses the store-agnostic ranking functions
(`near_duplicates_in`, `search_in`, `rank_candidates`) imported from this module.

## Design laws

- **The adapter law**: the web views never know the storage; only adapters
  (`../web/adapter-sqlite.js`, a host's own adapter) speak HTTP to this server.
  The MCP direct-sqlite fallback is the ONE sanctioned bypass of the HTTP face -
  it calls the same functions in-process, same lock discipline.
- **Single-writer discipline**: one connection, one lock; error returns roll back
  (`_fail`) so a refused action can never leak half-written state into the next
  commit.
- **Prune is client-confirmed, server-verified**: the client sends the subtree the
  human SAW; the server refuses if it changed (TOCTOU), and spares any descendant
  still reachable via a live extra avenue (the multi-parent law).

## Tests

`python test_server.py` (HTTP e2e over a throwaway db) and `python test_mcp.py`
(real stdio JSON-RPC; the board leg auto-skips without a live board).
