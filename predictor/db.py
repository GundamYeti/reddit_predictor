"""SQLite storage: questions you write, comments collected from Reddit, and
the predictions that link a comment to a question."""

import calendar
import os
import sqlite3

DEFAULT_DB = os.environ.get("PREDICTOR_DB", "data/predictor.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id          INTEGER PRIMARY KEY,
    text        TEXT NOT NULL,              -- a yes/no question, e.g. "Will X happen by <date>?"
    criteria    TEXT NOT NULL DEFAULT '',   -- how you will decide YES vs NO
    keywords    TEXT NOT NULL DEFAULT '',   -- comma-separated; used to pre-filter comments
    opens_at    INTEGER,                    -- unix time; ignore comments before this
    closes_at   INTEGER NOT NULL,           -- unix time the answer became known; later comments are hindsight
    status      TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'yes', 'no', 'void')),
    resolved_at INTEGER,
    notes       TEXT NOT NULL DEFAULT '',
    created_at  INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS comments (
    id          TEXT PRIMARY KEY,           -- Reddit id without the t1_ prefix
    author      TEXT NOT NULL,
    subreddit   TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_utc INTEGER NOT NULL,
    score       INTEGER,
    link_id     TEXT,
    parent_id   TEXT,
    permalink   TEXT,
    source      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS comments_author ON comments(author);
CREATE INDEX IF NOT EXISTS comments_created ON comments(created_utc);

-- One row per (comment, question) the classifier has looked at, relevant or not,
-- so nothing is sent to the model twice.
CREATE TABLE IF NOT EXISTS predictions (
    comment_id  TEXT NOT NULL REFERENCES comments(id),
    question_id INTEGER NOT NULL REFERENCES questions(id),
    relevant    INTEGER NOT NULL,           -- 1 if the comment forecasts this question
    stance      TEXT CHECK (stance IN ('yes', 'no')),
    confidence  REAL,                       -- probability the author gives their stance, 0.5-0.99
    hedge_phrase TEXT NOT NULL DEFAULT '',  -- the author's exact certainty words; confidence comes from these
    condition   TEXT NOT NULL DEFAULT '',   -- '' unless "if A, then B"; then A
    condition_met INTEGER,                  -- for conditional forecasts: 1 = A happened (counts), 0 = it didn't, NULL = not decided
    quote       TEXT NOT NULL DEFAULT '',
    rationale   TEXT NOT NULL DEFAULT '',
    extractor   TEXT NOT NULL,              -- model name, or 'human'
    review      TEXT NOT NULL DEFAULT 'unreviewed'
                CHECK (review IN ('unreviewed', 'accepted', 'rejected')),
    reviewed_at INTEGER,
    created_at  INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (comment_id, question_id)
);

-- Discovery (see pilot.py): forecasts found without a preset question.
-- scans records every comment a model has read, including ones with no forecast.
CREATE TABLE IF NOT EXISTS scans (
    comment_id  TEXT NOT NULL REFERENCES comments(id),
    extractor   TEXT NOT NULL,
    n_forecasts INTEGER NOT NULL,
    note        TEXT NOT NULL DEFAULT '',
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (comment_id, extractor)
);

CREATE TABLE IF NOT EXISTS forecasts (
    id           INTEGER PRIMARY KEY,
    comment_id   TEXT NOT NULL REFERENCES comments(id),
    extractor    TEXT NOT NULL,
    proposition  TEXT NOT NULL,     -- the event, stated positively: "Biden withdraws from the 2024 race"
    direction    TEXT NOT NULL CHECK (direction IN ('happens', 'does_not_happen')),
    deadline     TEXT NOT NULL DEFAULT '',
    hedge_phrase TEXT NOT NULL DEFAULT '',  -- exact certainty words; '' = plain assertion
    condition    TEXT NOT NULL DEFAULT '',  -- '' unless "if A, then B"
    sarcastic    INTEGER NOT NULL DEFAULT 0,
    quote        TEXT NOT NULL DEFAULT '',
    created_at   INTEGER NOT NULL DEFAULT (unixepoch())
);
CREATE INDEX IF NOT EXISTS forecasts_comment ON forecasts(comment_id);

-- Batch API jobs (see batch.py). A batch is submitted, then collected up to 24 hours later.
CREATE TABLE IF NOT EXISTS batches (
    id           TEXT PRIMARY KEY,          -- the API's batch id
    extractor    TEXT NOT NULL,
    tag          TEXT NOT NULL,             -- which sample the comments came from
    n_comments   INTEGER NOT NULL,
    est_cost     REAL NOT NULL,             -- dollars, estimated at submit time
    cost         REAL,                      -- dollars, from actual usage once collected
    status       TEXT NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'collected', 'canceled')),
    created_at   INTEGER NOT NULL DEFAULT (unixepoch()),
    collected_at INTEGER
);
CREATE TABLE IF NOT EXISTS batch_requests (
    batch_id     TEXT NOT NULL REFERENCES batches(id),
    custom_id    TEXT NOT NULL,
    comment_ids  TEXT NOT NULL,             -- JSON list of the comments packed into this request
    PRIMARY KEY (batch_id, custom_id)
);

-- Every paid model run, for the monthly budget.
CREATE TABLE IF NOT EXISTS spend (
    id      INTEGER PRIMARY KEY,
    at      INTEGER NOT NULL DEFAULT (unixepoch()),
    dollars REAL NOT NULL,
    what    TEXT NOT NULL DEFAULT ''
);

-- Your hand labels: the answer key the model is measured against.
CREATE TABLE IF NOT EXISTS labels (
    comment_id  TEXT PRIMARY KEY REFERENCES comments(id),
    label       TEXT NOT NULL CHECK (label IN ('forecast', 'conditional', 'not', 'unsure')),
    note        TEXT NOT NULL DEFAULT '',
    labeled_at  INTEGER NOT NULL DEFAULT (unixepoch())
);
"""


def connect(path=DEFAULT_DB):
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


# Columns added after a database was first created: (table, column, definition).
ADDED_COLUMNS = [
    ("predictions", "hedge_phrase", "TEXT NOT NULL DEFAULT ''"),
    ("predictions", "condition", "TEXT NOT NULL DEFAULT ''"),
    ("predictions", "condition_met", "INTEGER"),
]


def _migrate(conn):
    for table, column, definition in ADDED_COLUMNS:
        if column not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()


def record_spend(conn, dollars, what=""):
    conn.execute("INSERT INTO spend (dollars, what) VALUES (?, ?)", (dollars, what))
    conn.commit()


def month_spend(conn, now=None):
    """Dollars recorded since the start of this calendar month (UTC)."""
    import time
    t = time.gmtime(now if now is not None else time.time())
    start = int(calendar.timegm((t.tm_year, t.tm_mon, 1, 0, 0, 0)))
    return conn.execute("SELECT COALESCE(SUM(dollars), 0) FROM spend WHERE at >= ?", (start,)).fetchone()[0]


def insert_comments(conn, comments, source, batch=50):
    """Insert normalized comment dicts, committing every `batch` so a crash
    part-way through a long download keeps what it already fetched.
    Returns how many were new."""
    before = conn.total_changes
    pending = []
    for c in comments:
        pending.append({**c, "source": source})
        if len(pending) >= batch:
            _insert(conn, pending)
            pending = []
    _insert(conn, pending)
    return conn.total_changes - before


def _insert(conn, rows):
    conn.executemany(
        """INSERT OR IGNORE INTO comments
           (id, author, subreddit, body, created_utc, score, link_id, parent_id, permalink, source)
           VALUES (:id, :author, :subreddit, :body, :created_utc, :score, :link_id, :parent_id, :permalink, :source)""",
        rows,
    )
    conn.commit()
