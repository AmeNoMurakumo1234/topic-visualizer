# server/ - storage + API design

The plugin's local backbone: a small server that owns `topics.db` (see
[schema.sql](schema.sql)), exposes the topics API over HTTP for the web views, and
exposes the same operations as MCP tools for the AI.

**Status: designed, not yet implemented.** This document is the spec the implementation
must satisfy; the schema is final enough to build against.

## Shape

One process, two faces over one store:

```
            +----------------------------+
  Claude -->|  MCP tools                 |
  (skills)  |  topic_add / topic_serve   |      +------------+
            |  topic_state / topic_link  +----->| topics.db  |
  Browser ->|  HTTP API + static views   |      |  (SQLite)  |
  (3 views) |  GET /api/topics ...       |      +------------+
            +----------------------------+
```

## HTTP API (what the views consume)

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/topics` | full tree: id, slug, title, body, parent, state, priority, tags, links, dates. Pruned topics excluded by default (`?include=pruned` to resurrect-browse). |
| POST | `/api/topics` | create (title, body, parent_slug?, priority?, tags?, created_by, provenance) |
| POST | `/api/topics/{slug}/state` | `{state: discussed\|open\|pruned, actor, note}` - reopen = state:open on a discussed/pruned topic; every change appends a topic_event |
| POST | `/api/topics/{slug}/links` | the conversion moment: `{kind: decision\|work_item\|document, ref, note}` |
| POST | `/api/topics/{slug}/beacon` | `{critical: bool, actor}` (audited via topic_event) |

Prune cascades are **client-confirmed, server-executed**: the client sends the subtree
slugs it showed the human in the consequence dialog; the server verifies the set matches
the current subtree (no TOCTOU pruning of children added mid-dialog) and applies
atomically.

## MCP tools (what the AI uses)

`topic_add`, `topic_serve` (returns the ONE top-ranked card - ranking: beacons, then
territory match against a caller-supplied context string, then age/time-weight),
`topic_state`, `topic_link`, `topic_groom_report` (the numbers the topics-groom skill needs:
dupe candidates, expiry candidates, beacon count, size trend). Tools mirror the HTTP
semantics exactly - one behavior, two doors.

## The adapter law

The three views must never know the storage. They consume the API above through a thin
client adapter (see the port plan in [../ROADMAP.md](../ROADMAP.md)); the prototype's
adapter spoke to a message-board API instead, and swapping adapters is the entire
difference between the birthplace instance and this plugin. Keep it that way.

## Implementation notes (for the builder)

- Python stdlib (`http.server` + `sqlite3`) or Node - zero heavy deps; this is a local
  single-user tool, not a service. Bind localhost only.
- All writes go through the server process (WAL mode, single writer): the views and
  MCP tools never open the db file directly.
- `topic_serve` is deliberately server-side ranking, so every client (skill, view,
  future CLI) deals the same card.
