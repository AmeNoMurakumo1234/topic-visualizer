-- Topic Visualizer: topics.db schema (v3 - multi-parent DAG, 2026-07-11)
-- One local SQLite file = one topic tree. The server owns all writes; the web views
-- and MCP tools go through the API, never the file directly.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- The tree. State machine (docs/2026-07-11-seam-design.md):
--   seedling -> open (on first touch) -> discussed <-> open ; pruned (by choice) ;
--   seedling -> expired (untouched ~21 days; the noise valve - counted in the groom
--   report, browsable in the archive, resurrectable).
CREATE TABLE IF NOT EXISTS topic (
  id               INTEGER PRIMARY KEY,
  slug             TEXT NOT NULL UNIQUE,
  title            TEXT NOT NULL,                    -- the question/tension, w/ (time-weight)
  body             TEXT NOT NULL DEFAULT '',         -- self-contained context + THE QUESTION:
  parent_id        INTEGER REFERENCES topic(id),     -- PRIMARY parent (first discovery
                                                     -- avenue; the layout spine); NULL =
                                                     -- root. Extra avenues: topic_parent.
  state            TEXT NOT NULL DEFAULT 'seedling'
                     CHECK (state IN ('seedling', 'open', 'discussed', 'pruned', 'expired')),
  priority         TEXT NOT NULL DEFAULT 'normal'
                     CHECK (priority IN ('normal', 'critical')),  -- the beacon; keep RARE
  tags             TEXT NOT NULL DEFAULT '',
  created_by       TEXT NOT NULL,                    -- 'human' | agent name
  created_at       TEXT NOT NULL DEFAULT (datetime('now')),
  touched_at       TEXT NOT NULL DEFAULT (datetime('now')),  -- last write of ANY kind (structural
                                                     -- reparent/attach included). 0.42: serve no
                                                     -- longer writes this (it was laundering
                                                     -- staleness) and it no longer graduates.
  engaged_at       TEXT NOT NULL DEFAULT (datetime('now')),  -- last GENUINE engagement with the idea
                                                     -- (capture, content edit, deliberate state
                                                     -- change, convert, beacon change) - the ONLY
                                                     -- graduators, and the staleness clock (0.42)
  served_at        TEXT,                             -- last serve impression; drives the serve
                                                     -- cooldown; NULL = never served (honest)
  provenance       TEXT NOT NULL DEFAULT '',
  state_changed_at TEXT,
  state_changed_by TEXT,
  state_note       TEXT,
  merged_into      TEXT,         -- survivor slug when this topic was folded away (a merge
                                 -- tombstone: state='pruned' + merged_into set; prune sweep
                                 -- hard-removes it after 14 days)
  role             TEXT NOT NULL DEFAULT 'topic'   -- 'topic' (a real question) | 'hub' (organizing
                                 -- scaffolding a groom minted). A hub is NOT a capture: undo removes
                                 -- an empty post-checkpoint hub; junk-drawer detection can flag it.
);
CREATE INDEX IF NOT EXISTS idx_topic_parent ON topic(parent_id);
CREATE INDEX IF NOT EXISTS idx_topic_state  ON topic(state);

-- Multi-parent: the same semantic topic reached from a SECOND conversational avenue.
-- The tree stays the layout spine (topic.parent_id); these are the extra edges that
-- make it a DAG - one topic, many roads in, never a duplicated subtree. The note
-- records what the later discovery added (the rediscovery enrichment).
CREATE TABLE IF NOT EXISTS topic_parent (
  id        INTEGER PRIMARY KEY,
  topic_id  INTEGER NOT NULL REFERENCES topic(id),
  parent_id INTEGER NOT NULL REFERENCES topic(id),
  note      TEXT NOT NULL DEFAULT '',                -- what this avenue added
  added_by  TEXT NOT NULL DEFAULT '',
  added_at  TEXT NOT NULL DEFAULT (datetime('now')),
  rel       TEXT NOT NULL DEFAULT 'co_parent',       -- co_parent (a real second parent - drawn and
                                                     -- positioned AS a parent) | see_also (a weak
                                                     -- cross-link). Judgment, not similarity: the
                                                     -- embedder can't tell a complement from noise.
  UNIQUE (topic_id, parent_id)
);
CREATE INDEX IF NOT EXISTS idx_tparent_topic  ON topic_parent(topic_id);
CREATE INDEX IF NOT EXISTS idx_tparent_parent ON topic_parent(parent_id);

-- The conversion moment: EXPLORING -> DECIDED/ACTING, the only bridge, always recorded.
CREATE TABLE IF NOT EXISTS topic_link (
  id         INTEGER PRIMARY KEY,
  topic_id   INTEGER NOT NULL REFERENCES topic(id),
  kind       TEXT NOT NULL CHECK (kind IN ('decision', 'work_item', 'document')),
  ref        TEXT NOT NULL,
  note       TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_link_topic ON topic_link(topic_id);

-- Append-only history: the audit trail that keeps pruning honest and reopening cheap.
CREATE TABLE IF NOT EXISTS topic_event (
  id       INTEGER PRIMARY KEY,
  topic_id INTEGER NOT NULL REFERENCES topic(id),
  event    TEXT NOT NULL,   -- created|touched|served|discussed|reopened|pruned|expired|converted|beacon_set|beacon_cleared|reparented|edited|reconciled
  actor    TEXT NOT NULL,
  note     TEXT NOT NULL DEFAULT '',
  at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_event_topic ON topic_event(topic_id);
CREATE INDEX IF NOT EXISTS idx_event_kind  ON topic_event(event);

-- Grooming safety net. A groom is the one bulk, hard-to-eyeball operation, so before it
-- reshapes the tree it drops a CHECKPOINT: a full logical snapshot of the topic tables.
-- Restore reverts every pre-existing topic to the snapshot (and un-tombstones anything the
-- groom merged/pruned), but NEVER deletes a topic captured AFTER the checkpoint - losing a
-- real capture is the one unforgivable sin, so post-checkpoint arrivals are always kept.
-- (topic_event is deliberately NOT snapshotted: history stays append-only and honest.)
CREATE TABLE IF NOT EXISTS groom_checkpoint (
  id          INTEGER PRIMARY KEY,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  label       TEXT NOT NULL DEFAULT '',
  actor       TEXT NOT NULL DEFAULT '',
  restored_at TEXT,                       -- set when this checkpoint was used to roll back
  auto        INTEGER NOT NULL DEFAULT 0, -- 1 = a safety snapshot taken BEFORE a restore (so an undo
                                          -- is itself recoverable); "restore latest" skips these so
                                          -- it targets the last real GROOM, not a pre-restore state
  snapshot    TEXT NOT NULL               -- JSON {topics:[...], parents:[...], links:[...]}
);
CREATE INDEX IF NOT EXISTS idx_checkpoint_created ON groom_checkpoint(created_at);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '3');
