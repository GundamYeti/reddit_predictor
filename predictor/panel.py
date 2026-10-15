"""The panel: a fixed set of heavy commenters whose comments we follow.

Scanning everyone is far over budget, but commenting is concentrated: the top
25-50 commenters in a subreddit write a large share of its comments, and they're
the only people who comment enough to build a track record. See PLAN.md.

  pick:  the top N commenters per subreddit in a given week (Arctic Shift author counts)
  fetch: each member's comments, week by week; keep those passing the phrase
         filter, then a random sample of at most cap-per-week (spread evenly
         through the month); stored as source "panel" for `batch submit --tag panel`
"""

import math
import random
import time
import urllib.parse

from . import db, prefilter, sources

SEARCH = "https://arctic-shift.photon-reddit.com/api/comments/search"
AGGREGATE = SEARCH + "/aggregate"
DAY, WEEK = 86400, 7 * 86400
TAG = "panel"
MIN_WINDOW = 3 * 3600


def is_person(author):
    a = author.lower()
    return (author not in sources.SKIP_AUTHORS and not a.endswith("bot") and "modteam" not in a
            and a != "visualmod")


def author_counts(subreddit, after, before, get=sources._get_json, pause=2.0):
    """{author: comments} between two unix times, splitting windows the archive times out on."""
    time.sleep(pause)
    q = urllib.parse.urlencode({"aggregate": "author", "subreddit": subreddit,
                                "after": after, "before": before, "limit": 10000})
    try:
        rows = get(f"{AGGREGATE}?{q}")
    except sources.SearchTimeout:
        if before - after <= MIN_WINDOW:
            raise
        mid = (after + before) // 2
        a, b = author_counts(subreddit, after, mid, get, pause), author_counts(subreddit, mid, before, get, pause)
        return {k: a.get(k, 0) + b.get(k, 0) for k in a.keys() | b.keys()}
    return {r["key"]: int(r["count"]) for r in rows}


def pick(conn, subreddits, top, week_start, get=sources._get_json, pause=2.0, out=print):
    """Add the top commenters of each subreddit in the week starting week_start."""
    added = 0
    for sub in subreddits:
        counts = {}
        for d in range(7):
            for author, n in author_counts(sub, week_start + d * DAY, week_start + (d + 1) * DAY, get, pause).items():
                counts[author] = counts.get(author, 0) + n
        people = sorted(((n, a) for a, n in counts.items() if is_person(a)), reverse=True)[:top]
        for n, author in people:
            cur = conn.execute("INSERT OR IGNORE INTO panel (author, subreddit, weekly_comments) VALUES (?, ?, ?)",
                               (author, sub, n))
            added += cur.rowcount
        conn.commit()
        out(f"r/{sub}: top {len(people)} commenters, {people[-1][0] if people else 0}-{people[0][0] if people else 0}"
            f" comments that week")
    return added


def weeks(since, until, done=()):
    """Week-long windows covering since..until, the last one ending at or before until.

    If some weeks are already fetched, new windows continue on from them (forward
    to until, and back to since) instead of starting a fresh grid at since, so a
    monthly refresh never re-reads days it already has.
    """
    if not done:
        return list(range(since, until - WEEK + 1, WEEK))
    first, last = min(done), max(done)
    back = list(range(first - WEEK, since - 1, -WEEK))[::-1]
    forward = list(range(last + WEEK, until - WEEK + 1, WEEK))
    return back + forward


def member_week(author, subreddit, after, before, get=sources._get_json, pause=1.5):
    """All of one member's comments in one subreddit and window, oldest first."""
    params = {"author": author, "subreddit": subreddit, "after": after, "before": before,
              "limit": 100, "sort": "asc"}
    found = {}
    while True:
        time.sleep(pause)
        batch = get(SEARCH + "?" + urllib.parse.urlencode(params))
        # Each page starts at the previous page's last timestamp, so drop repeats.
        found.update((c["id"], c) for c in map(sources.normalize, batch) if c)
        if len(batch) < 100:
            return list(found.values())
        last = int(float(batch[-1]["created_utc"]))
        params["after"] = last if last > params["after"] else last + 1


def fetch(conn, since, until, cap_per_month=40, pattern=prefilter.STRICT, get=sources._get_json, pause=1.5,
          out=print):
    """Fetch every active member's comments week by week; skips weeks already fetched."""
    per_week = math.ceil(cap_per_month * 7 / 30)
    members = conn.execute("SELECT * FROM panel WHERE status = 'active' ORDER BY subreddit, weekly_comments DESC"
                           ).fetchall()
    stored = 0
    for i, m in enumerate(members, 1):
        done = {r[0] for r in conn.execute(
            "SELECT week_start FROM panel_fetches WHERE author = ? AND subreddit = ?", (m["author"], m["subreddit"]))}
        kept_here = seen_here = 0
        for w in weeks(since, until, done):
            try:
                comments = member_week(m["author"], m["subreddit"], w, w + WEEK, get, pause)
            except RuntimeError as e:  # the archive kept failing; this week is retried next run
                out(f"  u/{m['author']} week of {time.strftime('%Y-%m-%d', time.gmtime(w))}: skipped ({e})")
                continue
            passing = [c for c in comments if prefilter.passes(c["body"], pattern)]
            # A random sample, not the first N, so the cap doesn't favor the start of the week.
            random.Random(f"{m['author']}/{w}").shuffle(passing)
            kept = passing[:per_week]
            db.insert_comments(conn, kept, TAG)
            conn.execute("INSERT INTO panel_fetches (author, subreddit, week_start, seen, passed, kept)"
                         " VALUES (?, ?, ?, ?, ?, ?)",
                         (m["author"], m["subreddit"], w, len(comments), len(passing), len(kept)))
            conn.commit()
            kept_here += len(kept)
            seen_here += len(comments)
        stored += kept_here
        out(f"  [{i}/{len(members)}] r/{m['subreddit']} u/{m['author']}: kept {kept_here} of {seen_here} comments")
    out(f"Stored {stored} comments as sample {TAG!r}. Next: python -m predictor batch submit --tag {TAG}")
    return stored


def members(conn, extractor=None):
    """Per active member: months fetched, comments scanned, forecasts found."""
    return conn.execute("""
        SELECT p.author, p.subreddit, p.weekly_comments,
               (SELECT COUNT(*) FROM panel_fetches f WHERE f.author = p.author AND f.subreddit = p.subreddit) / 4.3
                   AS months,
               (SELECT COUNT(*) FROM scans s JOIN comments c ON c.id = s.comment_id
                 WHERE c.source = 'panel' AND c.author = p.author AND c.subreddit = p.subreddit
                   AND (? IS NULL OR s.extractor = ?)) AS scanned,
               (SELECT COUNT(*) FROM forecasts f JOIN comments c ON c.id = f.comment_id
                 WHERE c.source = 'panel' AND c.author = p.author AND c.subreddit = p.subreddit
                   AND (? IS NULL OR f.extractor = ?)) AS forecasts
        FROM panel p WHERE p.status = 'active' ORDER BY p.subreddit, p.author""",
        (extractor, extractor, extractor, extractor)).fetchall()


def prune(conn, min_per_month=5, min_scanned=20, extractor=None, dry_run=False, out=print):
    """Drop members who make fewer than min_per_month forecasts a month.

    Only members with at least min_scanned comments scanned are judged; the rest
    keep their place until there's enough to go on. Dropped members keep their
    data and can be set back to 'active' by hand.
    """
    dropped = []
    for m in members(conn, extractor):
        if m["scanned"] < min_scanned or not m["months"]:
            continue
        rate = m["forecasts"] / m["months"]
        if rate < min_per_month:
            dropped.append((m["author"], m["subreddit"], rate))
    for author, sub, rate in dropped:
        out(f"  drop r/{sub} u/{author}: {rate:.1f} forecasts a month")
        if not dry_run:
            conn.execute("UPDATE panel SET status = 'dropped' WHERE author = ? AND subreddit = ?", (author, sub))
    conn.commit()
    out(f"{'Would drop' if dry_run else 'Dropped'} {len(dropped)} members.")
    return dropped


def status(conn, extractor=None, out=print):
    """Per subreddit: members, comments stored, scanned, forecasts found."""
    rows = conn.execute("""
        SELECT p.subreddit, COUNT(DISTINCT p.author) AS members,
               (SELECT COUNT(*) FROM comments c WHERE c.source = 'panel' AND c.subreddit = p.subreddit) AS stored,
               (SELECT COUNT(*) FROM scans s JOIN comments c ON c.id = s.comment_id
                 WHERE c.source = 'panel' AND c.subreddit = p.subreddit AND (? IS NULL OR s.extractor = ?)) AS scanned,
               (SELECT COUNT(*) FROM forecasts f JOIN comments c ON c.id = f.comment_id
                 WHERE c.source = 'panel' AND c.subreddit = p.subreddit AND (? IS NULL OR f.extractor = ?)) AS forecasts
        FROM panel p WHERE p.status = 'active' GROUP BY p.subreddit ORDER BY p.subreddit""",
        (extractor, extractor, extractor, extractor)).fetchall()
    if not rows:
        out("The panel is empty. Start with: python -m predictor panel pick --subreddits politics,nba --top 20")
        return
    out(f"{'subreddit':24} {'members':>7} {'stored':>7} {'scanned':>7} {'forecasts':>9}")
    for r in rows:
        out(f"r/{r['subreddit']:22} {r['members']:>7} {r['stored']:>7} {r['scanned']:>7} {r['forecasts']:>9}")
