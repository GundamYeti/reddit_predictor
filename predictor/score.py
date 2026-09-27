"""Brier scores per user and per subreddit.

For each resolved question, a forecast becomes p_yes (the chance the author
gave to YES): their confidence if they said YES, 1 - confidence if they said NO.
Brier = (p_yes - outcome)^2, where outcome is 1 for YES and 0 for NO.
0 is perfect, 0.25 is what always saying 50/50 gets, 1 is confidently wrong every time.

Rules that keep the score honest:
- Only comments posted before the question's closes_at count (no hindsight).
- A user who comments about one question many times counts once for it,
  using the average of their forecasts, so one spammer can't dominate.
- Small samples are pulled toward 0.25 ("adjusted"): someone who got one call
  right shouldn't outrank someone with forty good calls. PRIOR_WEIGHT is how
  many coin-flip forecasts each user starts with.
"""

import json

BASELINE = 0.25
PRIOR_WEIGHT = 5


def forecasts(conn, include_unreviewed=False, per_subreddit=False):
    """One row per (author, resolved question): mean p_yes and the outcome.

    per_subreddit splits that by subreddit too, so a user who argued the same
    question in two subreddits counts toward each of them.
    """
    reviews = "('accepted', 'unreviewed')" if include_unreviewed else "('accepted')"
    group = "c.author, q.id, c.subreddit" if per_subreddit else "c.author, q.id"
    return conn.execute(f"""
        SELECT c.author, q.id AS question_id, c.subreddit,
               AVG(CASE p.stance WHEN 'yes' THEN p.confidence ELSE 1 - p.confidence END) AS p_yes,
               CASE q.status WHEN 'yes' THEN 1 ELSE 0 END AS outcome,
               COUNT(*) AS comments
        FROM predictions p
        JOIN comments c ON c.id = p.comment_id
        JOIN questions q ON q.id = p.question_id
        WHERE p.relevant = 1
          AND p.review IN {reviews}
          AND q.status IN ('yes', 'no')
          AND c.created_utc < q.closes_at
        GROUP BY {group}
    """).fetchall()


def _summarize(rows, key):
    groups = {}
    for r in rows:
        groups.setdefault(r[key], []).append((r["p_yes"] - r["outcome"]) ** 2)
    out = []
    for name, briers in groups.items():
        n = len(briers)
        total = sum(briers)
        out.append({
            key: name,
            "n": n,
            "brier": round(total / n, 4),
            "adjusted": round((total + PRIOR_WEIGHT * BASELINE) / (n + PRIOR_WEIGHT), 4),
        })
    out.sort(key=lambda s: (s["adjusted"], -s["n"]))
    return out


def by_user(conn, include_unreviewed=False):
    return _summarize(forecasts(conn, include_unreviewed), "author")


def by_subreddit(conn, include_unreviewed=False):
    return _summarize(forecasts(conn, include_unreviewed, per_subreddit=True), "subreddit")


def export(conn, path, include_unreviewed=False):
    """Write {author: {...}} JSON, the lookup table the browser overlay will read."""
    users = {u["author"]: {k: u[k] for k in ("n", "brier", "adjusted")}
             for u in by_user(conn, include_unreviewed)}
    with open(path, "w") as fh:
        json.dump({"baseline": BASELINE, "prior_weight": PRIOR_WEIGHT, "users": users}, fh, indent=1)
    return len(users)
