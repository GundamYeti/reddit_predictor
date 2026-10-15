"""The panel: picking heavy commenters and fetching their comments, with a fake archive.

Run: python -m unittest discover tests
"""

import unittest
import urllib.parse

from predictor import db, panel, prefilter, sources

WEEK0 = 1720396800  # a Monday


def fake_archive(comments_by_author, timeout_days=()):
    """A stand-in for sources._get_json, answering aggregate and search URLs."""
    calls = []

    def get(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        calls.append(q)
        after, before = int(q["after"]), int(q["before"])
        if url.startswith(panel.AGGREGATE):
            if before - after > 6 * 3600 and (after - WEEK0) // 86400 in timeout_days:
                raise sources.SearchTimeout("Timeout. Maybe slow down a bit")
            counts = {}
            for author, cs in comments_by_author.items():
                n = sum(after <= c["created_utc"] < before for c in cs)
                if n:
                    counts[author] = n
            return [{"key": a, "count": str(n)} for a, n in counts.items()]
        rows = sorted((c for c in comments_by_author.get(q["author"], []) if after < c["created_utc"] < before
                       or c["created_utc"] == after), key=lambda c: c["created_utc"])
        return rows[:int(q["limit"])]

    return get, calls


def comment(i, author, t, body):
    return {"id": f"{author}{i}", "author": author, "subreddit": "nba", "body": body, "created_utc": t}


class Panel(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.log = []
        heavy = [comment(i, "heavy", WEEK0 + i * 600, "they will win" if i % 2 else "nice dunk")
                 for i in range(150)]  # 75 pass the filter, spread over the first day; needs two pages
        light = [comment(i, "light", WEEK0 + i * 3600, "probably traded soon") for i in range(3)]
        bot = [comment(i, "StatsBot", WEEK0 + i * 60, "will") for i in range(500)]
        mod = [comment(i, "nba-ModTeam", WEEK0 + i * 60, "will") for i in range(300)]
        self.get, self.calls = fake_archive({"heavy": heavy, "light": light, "StatsBot": bot, "nba-ModTeam": mod},
                                            timeout_days={0})

    def test_pick_skips_bots_and_splits_timeouts(self):
        added = panel.pick(self.conn, ["nba"], 5, WEEK0, get=self.get, pause=0, out=self.log.append)
        members = [r[0] for r in self.conn.execute("SELECT author FROM panel ORDER BY weekly_comments DESC")]
        self.assertEqual(members, ["heavy", "light"])
        self.assertEqual(added, 2)
        # Day 0 timed out at full size and was split into smaller windows.
        day0 = [c for c in self.calls if int(c["after"]) < WEEK0 + 86400]
        self.assertGreater(len(day0), 1)

    def test_fetch_caps_samples_and_skips_done_weeks(self):
        panel.pick(self.conn, ["nba"], 5, WEEK0, get=self.get, pause=0, out=self.log.append)
        panel.fetch(self.conn, WEEK0, WEEK0 + panel.WEEK, cap_per_month=30, get=self.get, pause=0,
                    out=self.log.append)
        kept = {r[0]: r[1] for r in self.conn.execute(
            "SELECT author, COUNT(*) FROM comments WHERE source = 'panel' GROUP BY author")}
        self.assertEqual(kept, {"heavy": 7, "light": 3})  # ceil(30 * 7 / 30) = 7 per week
        bodies = [r[0] for r in self.conn.execute("SELECT body FROM comments WHERE source = 'panel'")]
        self.assertTrue(all(prefilter.passes(b) for b in bodies))
        seen = self.conn.execute("SELECT seen, passed, kept FROM panel_fetches WHERE author = 'heavy'").fetchone()
        self.assertEqual(tuple(seen), (150, 75, 7))
        # A second run doesn't fetch the same week again.
        before = len(self.calls)
        panel.fetch(self.conn, WEEK0, WEEK0 + panel.WEEK, get=self.get, pause=0, out=self.log.append)
        self.assertEqual(len(self.calls), before)

    def test_weeks_end_before_until(self):
        self.assertEqual(panel.weeks(WEEK0, WEEK0 + 3 * panel.WEEK + 86400),
                         [WEEK0, WEEK0 + panel.WEEK, WEEK0 + 2 * panel.WEEK])

    def test_filter_handles_curly_apostrophes(self):
        self.assertTrue(prefilter.passes("He won’t run"))
        self.assertFalse(prefilter.passes("nice dunk"))


if __name__ == "__main__":
    unittest.main()
