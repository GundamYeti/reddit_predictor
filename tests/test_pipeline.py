"""End-to-end tests on synthetic comments with a scripted stand-in for the model.

Run: python -m unittest discover tests
"""

import io
import json
import os
import tempfile
import unittest

from predictor import db, extract, review, score, sources
from predictor.__main__ import date

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_comments.jsonl")

# What a well-behaved model would say about each synthetic comment.
SCRIPTED = {
    "c1": {"relevant": True, "stance": "no", "confidence": 0.97, "quote": "definitely staying", "rationale": ""},
    "c2": {"relevant": True, "stance": "yes", "confidence": 0.7, "quote": "I think he drops out", "rationale": ""},
    "c3": {"relevant": False, "stance": "none", "confidence": 0.5, "quote": "", "rationale": "a hope"},
    "c4": {"relevant": True, "stance": "yes", "confidence": 0.96, "quote": "Calling it now", "rationale": ""},
    "c8": {"relevant": True, "stance": "no", "confidence": 0.8, "quote": "any day now", "rationale": "sarcasm"},
    "c9": {"relevant": False, "stance": "none", "confidence": 0.5, "quote": "", "rationale": "about pizza"},
}


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.seen = []

    def complete_json(self, system, prompt, schema):
        cid = next(c for c, body in BODIES.items() if body in prompt)
        self.seen.append(cid)
        return SCRIPTED[cid]


with open(FIXTURE) as fh:
    BODIES = {raw["id"]: raw["body"] for raw in map(json.loads, fh)}


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.insert_comments(self.conn, sources.dump_file(FIXTURE), "test")
        self.conn.execute(
            "INSERT INTO questions (text, keywords, opens_at, closes_at) VALUES (?, ?, ?, ?)",
            ("Will Biden withdraw from the 2024 race before the convention?",
             "drop, step aside, staying", date("2024-06-27"), date("2024-07-21")))
        self.q = self.conn.execute("SELECT * FROM questions").fetchone()

    def tearDown(self):
        self.conn.close()

    def test_collect_skips_deleted_and_bots(self):
        ids = {r[0] for r in self.conn.execute("SELECT id FROM comments")}
        self.assertNotIn("c6", ids)
        self.assertNotIn("c7", ids)
        self.assertEqual(len(ids), 8)

    def test_file_filters(self):
        got = [c["id"] for c in sources.dump_file(FIXTURE, subreddits=["NEWS"])]
        self.assertEqual(got, ["c8"])
        got = [c["id"] for c in sources.dump_file(FIXTURE, after=date("2024-07-04"), before=date("2024-07-05"),
                                                   keywords=["Pizza"])]
        self.assertEqual(got, ["c9"])

    def test_candidates_respect_window_and_keywords(self):
        ids = {c["id"] for c in extract.candidates(self.conn, self.q)}
        # c5 is after close (hindsight), c10 before open, c3 has no keyword.
        # c9 ("drops prices") matches "drop": keywords are only a coarse filter.
        self.assertEqual(ids, {"c1", "c2", "c4", "c8", "c9"})

    def test_clean_clamps_and_blanks_irrelevant(self):
        self.assertEqual(extract.clean({"relevant": True, "stance": "yes", "confidence": 1.4})["confidence"], 0.99)
        self.assertEqual(extract.clean({"relevant": True, "stance": "yes", "confidence": "x"})["confidence"], 0.6)
        r = extract.clean({"relevant": True, "stance": "none", "confidence": 0.9, "quote": "q"})
        self.assertEqual((r["relevant"], r["stance"], r["quote"]), (0, None, ""))

    def _extract(self):
        backend = FakeBackend()
        found, failed = extract.run(self.conn, backend, self.q, out=io.StringIO())
        return backend, found, failed

    def test_extract_stores_and_is_idempotent(self):
        backend, found, failed = self._extract()
        self.assertEqual((found, failed), (4, 0))
        self.assertEqual(extract.candidates(self.conn, self.q), [])

    def test_review_and_score(self):
        self._extract()
        # Queue order is by time: c1 alice, c2 bob, c8 erin, c4 bob.
        # Accept alice and both of bob's; reject erin's; then resolve YES.
        answers = iter(["a", "a", "r", "a"])
        review.run(self.conn, read=lambda _: next(answers), write=lambda *_: None)
        self.assertEqual(score.by_user(self.conn), [])  # still open: nothing to score
        self.conn.execute("UPDATE questions SET status = 'yes'")

        users = {u["author"]: u for u in score.by_user(self.conn)}
        self.assertEqual(set(users), {"synthetic_alice", "synthetic_bob"})
        # alice: said NO at 0.97 -> p_yes 0.03 -> (0.03 - 1)^2
        self.assertAlmostEqual(users["synthetic_alice"]["brier"], 0.9409, places=4)
        # bob: two comments averaged into one forecast, p_yes (0.7 + 0.96) / 2 = 0.83
        self.assertEqual(users["synthetic_bob"]["n"], 1)
        self.assertAlmostEqual(users["synthetic_bob"]["brier"], (0.83 - 1) ** 2, places=4)
        # shrinkage toward 0.25 with PRIOR_WEIGHT = 5
        self.assertAlmostEqual(users["synthetic_bob"]["adjusted"], ((0.17 ** 2) + 5 * 0.25) / 6, places=4)
        self.assertEqual(score.by_user(self.conn)[0]["author"], "synthetic_bob")

    def test_unreviewed_only_counts_when_asked(self):
        self._extract()
        self.conn.execute("UPDATE questions SET status = 'no'")
        self.assertEqual(score.by_user(self.conn), [])
        users = {u["author"] for u in score.by_user(self.conn, include_unreviewed=True)}
        self.assertEqual(users, {"synthetic_alice", "synthetic_bob", "synthetic_erin"})

    def test_void_questions_do_not_score(self):
        self._extract()
        self.conn.execute("UPDATE predictions SET review = 'accepted'")
        self.conn.execute("UPDATE questions SET status = 'void'")
        self.assertEqual(score.by_user(self.conn), [])

    def test_review_flip_and_confidence(self):
        self._extract()
        answers = iter(["f", "0.6", "nonsense", "1.5", "s", "q"])
        review.run(self.conn, read=lambda _: next(answers), write=lambda *_: None)
        rows = {r["comment_id"]: r for r in self.conn.execute("SELECT * FROM predictions WHERE relevant = 1")}
        self.assertEqual((rows["c1"]["stance"], rows["c1"]["review"]), ("yes", "accepted"))
        self.assertEqual((rows["c2"]["confidence"], rows["c2"]["review"]), (0.6, "accepted"))
        self.assertEqual(rows["c8"]["review"], "unreviewed")  # bad input twice, then skipped
        self.assertEqual(rows["c4"]["review"], "unreviewed")  # quit on it

    def test_subreddit_scores_split_users_across_subreddits(self):
        self._extract()
        self.conn.execute("UPDATE predictions SET review = 'accepted'")
        self.conn.execute("UPDATE comments SET subreddit = 'news' WHERE id = 'c4'")  # bob in two subs
        self.conn.execute("UPDATE questions SET status = 'yes'")
        subs = {s["subreddit"]: s for s in score.by_subreddit(self.conn)}
        self.assertEqual((subs["politics"]["n"], subs["news"]["n"]), (2, 2))  # alice+bob, bob+erin
        self.assertEqual({u["author"]: u["n"] for u in score.by_user(self.conn)}["synthetic_bob"], 1)

    def test_export(self):
        self._extract()
        self.conn.execute("UPDATE predictions SET review = 'accepted'")
        self.conn.execute("UPDATE questions SET status = 'yes'")
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "scores.json")
            self.assertEqual(score.export(self.conn, path), 3)
            with open(path) as fh:
                data = json.load(fh)
        self.assertEqual(data["baseline"], 0.25)
        self.assertIn("synthetic_erin", data["users"])


if __name__ == "__main__":
    unittest.main()
