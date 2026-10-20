"""Claims (grouping forecasts into questions) and markets, with scripted stand-ins.

Run: python -m unittest discover tests
"""

import json
import os
import unittest

from predictor import claims, db, markets, score

os.environ.setdefault("AI_ACTIVITY_LOG", os.devnull)
T0 = 1759000000


class Scripted:
    """A model stand-in that answers each kind of request from a script."""
    name = "scripted"

    def __init__(self, group=None, merge=None, match=None):
        self.answers = {"group": group or {}, "merge": merge or {"groups": []}, "match": match or {"matches": []}}
        self.prompts = []

    def complete_json(self, system, prompt, schema, max_tokens=8000):
        self.prompts.append(prompt)
        kind = "group" if system is claims.GROUP_SYSTEM else "merge" if system is claims.MERGE_SYSTEM else "match"
        answer = self.answers[kind]
        return answer(prompt) if callable(answer) else answer


def polymarket(id_, question, yes_price, closed=False, resolved=False, closed_time=None):
    return {"id": id_, "question": question, "description": f"Rules for {question}", "slug": f"m{id_}",
            "outcomes": '["Yes", "No"]', "outcomePrices": json.dumps([str(yes_price), str(1 - yes_price)]),
            "endDate": "2026-12-31T00:00:00Z", "closed": closed, "closedTime": closed_time,
            "umaResolutionStatus": "resolved" if resolved else None}


class Claims(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.add("a1", "alice", "politics", "Fed cuts rates in December", "happens", "probably")
        self.add("b1", "bob", "politics", "Fed cuts rates in December", "does_not_happen", "")
        self.add("c1", "carol", "politics", "my sister quits her job", "happens", "")
        self.add("d1", "dave", "nba", "Fed holds rates in December", "happens", "I think")
        self.fid = {r["comment_id"]: r["id"] for r in self.conn.execute("SELECT * FROM forecasts")}

    def add(self, cid, author, sub, prop, direction, hedge):
        self.conn.execute("INSERT INTO comments (id, author, subreddit, body, created_utc, source)"
                          " VALUES (?, ?, ?, '', ?, 'panel')", (cid, author, sub, T0))
        self.conn.execute("INSERT INTO forecasts (comment_id, extractor, proposition, direction, hedge_phrase)"
                          " VALUES (?, 'm', ?, ?, ?)", (cid, prop, direction, hedge))

    def grouped(self):
        f = self.fid

        def group(prompt):
            if "r/politics" in prompt:
                return {"claims": [{"question": "Will the Fed cut rates at its December 2026 meeting?",
                                    "deadline": "December 2026", "search": "Fed rate cut December",
                                    "members": [{"id": f["a1"], "stance": "yes"}, {"id": f["b1"], "stance": "no"},
                                                {"id": 99999, "stance": "yes"}]}],  # an id that isn't ours
                        "dropped": [f["c1"]]}
            return {"claims": [{"question": "Will the Fed hold rates in December 2026?", "deadline": "December 2026",
                                "search": "Fed December", "members": [{"id": f["d1"], "stance": "yes"}]}],
                    "dropped": []}

        backend = Scripted(group=group)

        def merge(prompt):
            ids = {line.split(" | ")[1]: int(line.split(" | ")[0]) for line in prompt.splitlines()[1:]}
            cut, hold = ids["Will the Fed cut rates at its December 2026 meeting?"], ids["Will the Fed hold rates in December 2026?"]
            return {"groups": [{"keep": cut, "merge": [{"id": hold, "same_direction": False}]}]}

        backend.answers["merge"] = merge
        claims.group(self.conn, backend, "panel", out=lambda *_: None)
        self.cut = self.conn.execute("SELECT id FROM claims WHERE question LIKE '%cut%'").fetchone()[0]
        return backend

    def test_group_drops_merges_and_flips(self):
        self.grouped()
        members = {r["forecast_id"]: (r["claim_id"], r["stance"]) for r in self.conn.execute("SELECT * FROM claim_members")}
        f = self.fid
        # "Fed holds" YES was merged into "Fed cuts" as a NO.
        c = self.cut
        self.assertEqual(members, {f["a1"]: (c, "yes"), f["b1"]: (c, "no"), f["d1"]: (c, "no")})
        self.assertEqual(self.conn.execute("SELECT merged_into FROM claims WHERE id != ?", (c,)).fetchone()[0], c)
        self.assertEqual(claims.ungrouped(self.conn, "panel"), [])  # the dropped one isn't sent again
        row = claims.listing(self.conn)[0]
        self.assertEqual((row["authors"], row["yes"], row["no"]), (3, 1, 2))

    def test_promote_without_market_needs_a_date(self):
        self.grouped()
        with self.assertRaises(ValueError):
            claims.promote(self.conn, self.cut)
        qid = claims.promote(self.conn, self.cut, closes_at=T0 + 86400 * 90)
        preds = {r["comment_id"]: (r["stance"], r["confidence"], r["review"])
                 for r in self.conn.execute("SELECT * FROM predictions WHERE question_id = ?", (qid,))}
        self.assertEqual(preds, {"a1": ("yes", 0.7, "unreviewed"), "b1": ("no", 0.9, "unreviewed"),
                                 "d1": ("no", 0.7, "unreviewed")})
        with self.assertRaises(ValueError):
            claims.promote(self.conn, self.cut, closes_at=T0)  # already promoted

    def test_match_promote_and_sync_with_a_reversed_market(self):
        self.grouped()
        calls = []

        def get(url):
            calls.append(url)
            if "public-search" in url:
                return {"events": [{"slug": "fed-dec", "markets": [
                    polymarket("m1", "Will the Fed hold rates in December 2026?", 0.3),
                    {"id": "m2", "question": "Which month?", "outcomes": '["Jan", "Feb"]', "outcomePrices": "[0.5, 0.5]"},
                ]}]}
            return polymarket("m1", "Will the Fed hold rates in December 2026?", 1, closed=True, resolved=True,
                              closed_time="2026-12-10 19:00:00+00")

        backend = Scripted(match={"matches": [{"claim": self.cut, "market": "m1", "same_direction": False}]})
        self.assertEqual(markets.match(self.conn, backend, get=get, out=lambda *_: None), 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0], 1)  # non Yes/No skipped
        qid = claims.promote(self.conn, self.cut)
        q = self.conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
        self.assertEqual((q["text"], q["market_id"]), ("Will the Fed hold rates in December 2026?", "m1"))
        # Stances flipped to the market's wording: alice expected a cut, so NO on "hold".
        stances = dict(self.conn.execute("SELECT comment_id, stance FROM predictions WHERE question_id = ?", (qid,)))
        self.assertEqual(stances, {"a1": "no", "b1": "yes", "d1": "yes"})

        self.assertEqual(markets.sync(self.conn, get=get, out=lambda *_: None), 1)
        q = self.conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
        self.assertEqual(q["status"], "yes")
        self.assertEqual(q["closes_at"], markets._ts("2026-12-10 19:00:00+00"))
        self.conn.execute("UPDATE predictions SET review = 'accepted'")
        users = {u["author"]: u for u in score.by_user(self.conn)}
        self.assertLess(users["bob"]["brier"], users["alice"]["brier"])  # bob said no cut, and the Fed held
        # Already-checked claims aren't searched again.
        before = len(calls)
        markets.match(self.conn, backend, get=get, out=lambda *_: None)
        self.assertEqual(len([c for c in calls[before:] if "public-search" in c]), 0)

    def test_markets_closed_before_the_forecasts_are_not_offered(self):
        self.grouped()

        def get(url):
            return {"events": [{"slug": "old", "markets": [
                polymarket("old", "Will the Fed cut in early 2025?", 0, closed=True, resolved=True,
                           closed_time="2025-03-19 19:00:00+00")]}]}  # before the forecasts (T0 is Sept 2025)

        backend = Scripted(match={"matches": [{"claim": self.cut, "market": "old", "same_direction": True}]})
        self.assertEqual(markets.match(self.conn, backend, get=get, out=lambda *_: None), 0)
        # An earlier stale match is undone so the claim gets matched again.
        self.conn.execute("UPDATE claims SET market_id = 'old', market_same = 1 WHERE id = ?", (self.cut,))
        self.assertEqual(markets.unmatch_stale(self.conn), 1)
        self.assertIsNone(self.conn.execute("SELECT market_id FROM claims WHERE id = ?", (self.cut,)).fetchone()[0])

    def test_parse_reads_outcomes(self):
        self.assertEqual(markets.parse(polymarket("x", "q", 1, closed=True, resolved=True))["outcome"], "yes")
        self.assertEqual(markets.parse(polymarket("x", "q", 0, closed=True, resolved=True))["outcome"], "no")
        self.assertIsNone(markets.parse(polymarket("x", "q", 0.4))["outcome"])


if __name__ == "__main__":
    unittest.main()
