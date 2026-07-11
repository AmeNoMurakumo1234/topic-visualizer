-- Topic Visualizer: topics.db schema (v0.1)
-- One local SQLite file = one topic tree. The plugin's MCP server owns all writes;
-- the web views read through the HTTP API, never the file directly.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- The tree. One row per topic; state transitions are appended to topic_event so the
-- history of a mind changing is never lost (a reopened topic remembers it was once
-- discussed; a pruned topic can be resurrected with its whole story intact).
CREATE TABLE IF NOT EXISTS topic (
  id               INTEGER PRIMARY KEY,
  slug             TEXT NOT NULL UNIQUE,             -- stable handle, url-safe
  title            TEXT NOT NULL,                    -- the question/tension, w/ (time-weight)
  body             TEXT NOT NULL DEFAULT '',         -- self-contained context + THE QUESTION:
  parent_id        INTEGER REFERENCES topic(id),     -- one parent max; NULL = root
  state            TEXT NOT NULL DEFAULT 'open'
                     CHECK (state IN ('open', 'discussed', 'pruned')),
  priority         TEXT NOT NULL DEFAULT 'normal'
                     CHECK (priority IN ('normal', 'critical')),  -- the beacon; keep RARE
  tags             TEXT NOT NULL DEFAULT '',         -- comma list; cross-cutting themes
  created_by       TEXT NOT NULL,                    -- 'human' | agent name
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  provenance       TEXT NOT NULL DEFAULT '',         -- which conversation/work birthed it
  state_changed_at TEXT,
  state_changed_by TEXT,
  state_note       TEXT                              -- why discussed/pruned/reopened
);
CREATE INDEX IF NOT EXISTS idx_topic_parent ON topic(parent_id);
CREATE INDEX IF NOT EXISTS idx_topic_state  ON topic(state);

-- The conversion moment: where a topic resolved into the other two stores.
-- (EXPLORING -> DECIDED / ACTING; the only bridge from maybe to commitment, always
-- explicit, always recorded.) A topic may link to many outcomes.
CREATE TABLE IF NOT EXISTS topic_link (
  id         INTEGER PRIMARY KEY,
  topic_id   INTEGER NOT NULL REFERENCES topic(id),
  kind       TEXT NOT NULL CHECK (kind IN ('decision', 'work_item', 'document')),
  ref        TEXT NOT NULL,                          -- external id: ticket slug, decision id, path/url
  note       TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_link_topic ON topic_link(topic_id);

-- Append-only history: every state change, reopen, merge, beacon change. The audit
-- trail that lets pruning be honest and reopening be cheap.
CREATE TABLE IF NOT EXISTS topic_event (
  id       INTEGER PRIMARY KEY,
  topic_id INTEGER NOT NULL REFERENCES topic(id),
  event    TEXT NOT NULL,                            -- created|discussed|reopened|pruned|converted|merged|beacon_set|beacon_cleared|reparented
  actor    TEXT NOT NULL,
  note     TEXT NOT NULL DEFAULT '',
  at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_event_topic ON topic_event(topic_id);

-- Single-row metadata (schema version for migrations).
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '1');
