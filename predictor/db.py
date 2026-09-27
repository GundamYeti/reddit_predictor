"""SQLite storage: questions you write, comments collected from Reddit, and
the predictions that link a comment to a question."""

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
    quote       TEXT NOT NULL DEFAULT '',
    rationale   TEXT NOT NULL DEFAULT '',
    extractor   TEXT NOT NULL,              -- model name, or 'human'
    review      TEXT NOT NULL DEFAULT 'unreviewed'
                CHECK (review IN ('unreviewed', 'accepted', 'rejected')),
    reviewed_at INTEGER,
    created_at  INTEGER NOT NULL DEFAULT (unixepoch()),
    PRIMARY KEY (comment_id, question_id)
);
"""


def connect(path=DEFAULT_DB):
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def insert_comments(conn, comments, source):
    """Insert normalized comment dicts; returns how many were new."""
    before = conn.total_changes
    conn.executemany(
        """INSERT OR IGNORE INTO comments
           (id, author, subreddit, body, created_utc, score, link_id, parent_id, permalink, source)
           VALUES (:id, :author, :subreddit, :body, :created_utc, :score, :link_id, :parent_id, :permalink, :source)""",
        ({**c, "source": source} for c in comments),
    )
    conn.commit()
    return conn.total_changes - before
