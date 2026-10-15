"""Brier scores per user and per subreddit, raw and relative to the crowd.

For each resolved question, a forecast becomes p_yes (the chance the author
gave to YES): their confidence if they said YES, 1 - confidence if they said NO.
Brier = (p_yes - outcome)^2, where outcome is 1 for YES and 0 for NO.
0 is perfect, 0.25 is what always saying 50/50 gets, 1 is confidently wrong every time.

Rules that keep the score honest:
- Only comments posted before the question's closes_at count (no hindsight).
- A user who comments about one question many times counts once for it,
  using the average of their forecasts, so one spammer can't dominate.
- Both sides: a user who said YES and NO on the same question within
  BOTH_SIDES_DAYS of each other is scored on whichever side was wrong. Saying
  both and keeping whichever comes true earns nothing. Changing your mind
  over a longer stretch is ordinary updating and is averaged as usual.
- Conditional forecasts ("if A, then B") count only once you've marked that A
  happened (condition_met = 1). Otherwise they're set aside: being wrong about
  B means nothing if A never happened.
- Small samples are pulled toward 0.25 ("adjusted"): someone who got one call
  right shouldn't outrank someone with forty good calls. PRIOR_WEIGHT is how
  many coin-flip forecasts each user starts with.
- Peer score: the user's Brier minus the Brier of everyone else's average
  forecast on the same question within PEER_WINDOW_DAYS of theirs. Negative
  means better than the crowd at the time. This is what separates skill from
  easy calls: when everyone saw it coming, being right earns about 0.
  peer_adjusted pulls small samples toward 0 (no evidence either way).
"""

import json
from collections import defaultdict

BASELINE = 0.25
PRIOR_WEIGHT = 5
BOTH_SIDES_DAYS = 7
PEER_WINDOW_DAYS = 7
DAY = 86400


def predictions(conn, include_unreviewed=False):
    """Every countable forecast, one row per comment and question."""
    reviews = "('accepted', 'unreviewed')" if include_unreviewed else "('accepted')"
    return conn.execute(f"""
        SELECT c.author, c.subreddit, c.created_utc, q.id AS question_id,
               CASE p.stance WHEN 'yes' THEN p.confidence ELSE 1 - p.confidence END AS p_yes,
               CASE q.status WHEN 'yes' THEN 1 ELSE 0 END AS outcome
        FROM predictions p
        JOIN comments c ON c.id = p.comment_id
        JOIN questions q ON q.id = p.question_id
        WHERE p.relevant = 1
          AND p.review IN {reviews}
          AND q.status IN ('yes', 'no')
          AND c.created_utc < q.closes_at
          AND (p.condition = '' OR p.condition_met = 1)
    """).fetchall()


def _combine(rows):
    """One user's forecasts on one question -> (p_yes, brier, time, both_sides)."""
    outcome = rows[0]["outcome"]
    yes = [r for r in rows if r["p_yes"] > 0.5]
    no = [r for r in rows if r["p_yes"] < 0.5]
    both_sides = any(abs(a["created_utc"] - b["created_utc"]) <= BOTH_SIDES_DAYS * DAY for a in yes for b in no)
    p_yes = sum(r["p_yes"] for r in rows) / len(rows)
    if both_sides:
        brier = max((r["p_yes"] - outcome) ** 2 for r in rows)
    else:
        brier = (p_yes - outcome) ** 2
    when = sum(r["created_utc"] for r in rows) / len(rows)
    return p_yes, brier, when, both_sides


def forecasts(conn, include_unreviewed=False, per_subreddit=False):
    """One dict per (author, resolved question), or per (author, question, subreddit).

    per_subreddit splits that by subreddit too, so a user who argued the same
    question in two subreddits counts toward each of them. The crowd for the
    peer score is always everyone on the question, whatever the subreddit.
    """
    rows = predictions(conn, include_unreviewed)
    by_author = defaultdict(list)
    for r in rows:
        by_author[(r["author"], r["question_id"])].append(r)

    # Each author's combined forecast, for building the crowd.
    crowd = defaultdict(list)  # question_id -> [(author, p_yes, time)]
    for (author, qid), rs in by_author.items():
        p_yes, _, when, _ = _combine(rs)
        crowd[qid].append((author, p_yes, when))

    groups = defaultdict(list)
    for r in rows:
        key = (r["author"], r["question_id"]) + ((r["subreddit"],) if per_subreddit else ())
        groups[key].append(r)

    out = []
    for key, rs in groups.items():
        author, qid = key[0], key[1]
        p_yes, brier, when, both_sides = _combine(rs)
        outcome = rs[0]["outcome"]
        others = [p for a, p, t in crowd[qid] if a != author and abs(t - when) <= PEER_WINDOW_DAYS * DAY]
        peer = None
        if others:
            crowd_p = sum(others) / len(others)
            peer = brier - (crowd_p - outcome) ** 2
        out.append({"author": author, "question_id": qid, "subreddit": rs[0]["subreddit"] if per_subreddit else None,
                    "p_yes": p_yes, "outcome": outcome, "brier": brier, "peer": peer,
                    "both_sides": both_sides, "comments": len(rs), "crowd_size": len(others)})
    return out


def _summarize(rows, key):
    groups = defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    out = []
    for name, rs in groups.items():
        n = len(rs)
        total = sum(r["brier"] for r in rs)
        peers = [r["peer"] for r in rs if r["peer"] is not None]
        out.append({
            key: name,
            "n": n,
            "brier": round(total / n, 4),
            "adjusted": round((total + PRIOR_WEIGHT * BASELINE) / (n + PRIOR_WEIGHT), 4),
            "peer_n": len(peers),
            "peer": round(sum(peers) / len(peers), 4) if peers else None,
            "peer_adjusted": round(sum(peers) / (len(peers) + PRIOR_WEIGHT), 4) if peers else None,
            "both_sides": sum(r["both_sides"] for r in rs),
        })
    # Rank by the crowd-relative score where there is one; users with no crowd to
    # compare against come after, ranked by adjusted Brier.
    out.sort(key=lambda s: (s["peer_adjusted"] is None, s["peer_adjusted"] or 0, s["adjusted"], -s["n"]))
    return out


def by_user(conn, include_unreviewed=False):
    return _summarize(forecasts(conn, include_unreviewed), "author")


def by_subreddit(conn, include_unreviewed=False):
    return _summarize(forecasts(conn, include_unreviewed, per_subreddit=True), "subreddit")


def export(conn, path, include_unreviewed=False):
    """Write {author: {...}} JSON, the lookup table the feed will read."""
    fields = ("n", "brier", "adjusted", "peer_n", "peer", "peer_adjusted")
    users = {u["author"]: {k: u[k] for k in fields} for u in by_user(conn, include_unreviewed)}
    with open(path, "w") as fh:
        json.dump({"baseline": BASELINE, "prior_weight": PRIOR_WEIGHT, "users": users}, fh, indent=1)
    return len(users)
