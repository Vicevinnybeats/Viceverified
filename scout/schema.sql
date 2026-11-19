-- The Scout's memory: everything it ever found (so nothing is reported twice).
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,              -- hash of the link
  title_key TEXT,                   -- simplified title, to catch the same story from many sites
  source TEXT NOT NULL,             -- google-news | reddit | youtube | twitch
  kind TEXT NOT NULL,               -- news | post | video | clip
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  author TEXT,
  published_at TEXT,
  found_at TEXT NOT NULL,
  metric INTEGER DEFAULT 0,         -- views / upvotes
  metric_label TEXT,
  thumbnail TEXT,
  score INTEGER DEFAULT 0,          -- 0-100 "would this make a good Short?"
  category TEXT,                    -- news | leak | clip | meme | guide | other
  new_info INTEGER DEFAULT 0,       -- 1 = genuinely new information
  angle TEXT,                       -- Qwen's Short idea
  scored_by TEXT,                   -- qwen | rules
  status TEXT DEFAULT 'new'         -- new | used | skip
);
CREATE INDEX IF NOT EXISTS idx_items_found ON items(found_at);
CREATE INDEX IF NOT EXISTS idx_items_title_key ON items(title_key);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  found INTEGER,
  new_items INTEGER,
  errors TEXT
);
