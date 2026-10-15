"""Scoring rules: hedge phrases, both sides, conditionals, crowd-relative scores.

Run: python -m unittest discover tests
"""

import sqlite3
import unittest

from predictor import db, hedges, review, score
from predictor.__main__ import date

DAY = 86400


class Hedges(unittest.TestCase):
    def test_measured_phrases(self):
        self.assertEqual(hedges.confidence("probably"), 0.70)
        self.assertEqual(hedges.confidence("almost certain"), 0.95)
        # Negative phrases describe the event as unlikely; the author's stance is NO.
        self.assertEqual(hedges.confidence("I doubt it"), 0.80)
        self.assertEqual(hedges.confidence("highly unlikely"), 0.95)

    def test_longest_phrase_wins(self):
        self.assertEqual(hedges.confidence("probably not"), 0.75)
        self.assertEqual(hedges.confidence("very good chance"), 0.80)

    def test_whole_words_and_curly_apostrophes(self):
        self.assertEqual(hedges.confidence("between you and me"), hedges.UNKNOWN)  # not "bet"
        self.assertEqual(hedges.confidence("I’d bet"), 0.85)
        self.assertEqual(hedges.confidence("doubtful"), 0.80)

    def test_plain_and_unknown(self):
        self.assertEqual(hedges.confidence(""), hedges.PLAIN)
        self.assertEqual(hedges.confidence("*WILL*"), hedges.PLAIN)
        self.assertEqual(hedges.confidence("zzz"), hedges.UNKNOWN)


class Scoring(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.start = date("2024-07-01")
        self.conn.execute("INSERT INTO questions (id, text, closes_at, status) VALUES (1, 'Will X?', ?, 'yes')",
                          (self.start + 30 * DAY,))
        self.n = 0

    def add(self, author, stance, confidence, day, condition="", condition_met=None, sub="politics"):
        self.n += 1
        cid = f"c{self.n}"
        self.conn.execute("INSERT INTO comments (id, author, subreddit, body, created_utc, source)"
                          " VALUES (?, ?, ?, '', ?, 'test')", (cid, author, sub, self.start + day * DAY))
        self.conn.execute("INSERT INTO predictions (comment_id, question_id, relevant, stance, confidence,"
                          " condition, condition_met, extractor, review) VALUES (?, 1, 1, ?, ?, ?, ?, 'test', 'accepted')",
                          (cid, stance, confidence, condition, condition_met))

    def users(self):
        return {u["author"]: u for u in score.by_user(self.conn)}

    def test_both_sides_within_a_week_scores_the_wrong_side(self):
        self.add("hedger", "yes", 0.9, day=1)
        self.add("hedger", "no", 0.9, day=3)
        u = self.users()["hedger"]
        self.assertAlmostEqual(u["brier"], (0.1 - 1) ** 2)  # the NO forecast, which was wrong
        self.assertEqual(u["both_sides"], 1)

    def test_changing_your_mind_later_is_averaged(self):
        self.add("updater", "no", 0.9, day=1)
        self.add("updater", "yes", 0.9, day=20)
        u = self.users()["updater"]
        self.assertAlmostEqual(u["brier"], (0.5 - 1) ** 2)
        self.assertEqual(u["both_sides"], 0)

    def test_conditionals_count_only_when_condition_met(self):
        self.add("cond_open", "yes", 0.9, day=1, condition="polls stay bad")
        self.add("cond_no", "yes", 0.9, day=1, condition="polls stay bad", condition_met=0)
        self.add("cond_yes", "yes", 0.9, day=1, condition="polls stay bad", condition_met=1)
        self.assertEqual(set(self.users()), {"cond_yes"})

    def test_peer_score_against_the_crowd_that_week(self):
        self.add("early_right", "yes", 0.9, day=1)
        self.add("crowd_a", "no", 0.7, day=2)
        self.add("crowd_b", "no", 0.7, day=3)
        self.add("late_easy", "yes", 0.9, day=25)  # nobody else forecast that week
        users = self.users()
        # Crowd for early_right = mean(p_yes 0.3, 0.3) = 0.3: Brier 0.49. Theirs: 0.01.
        self.assertAlmostEqual(users["early_right"]["peer"], 0.01 - 0.49)
        self.assertEqual(users["early_right"]["peer_n"], 1)
        self.assertAlmostEqual(users["early_right"]["peer_adjusted"], (0.01 - 0.49) / (1 + score.PRIOR_WEIGHT), places=4)
        # Crowd for crowd_a = early_right and crowd_b: mean(0.9, 0.3) = 0.6 -> Brier 0.16; theirs 0.49.
        self.assertAlmostEqual(users["crowd_a"]["peer"], 0.49 - 0.16)
        # Same raw Brier as early_right, but no crowd to beat: no peer score, ranked after.
        self.assertIsNone(users["late_easy"]["peer"])
        ranked = [u["author"] for u in score.by_user(self.conn)]
        self.assertEqual(ranked[0], "early_right")
        self.assertEqual(ranked[-1], "late_easy")


class ReviewConditionals(Scoring):
    def test_m_marks_the_condition_met_and_x_sets_it_aside(self):
        self.add("met", "yes", 0.9, day=1, condition="polls stay bad")
        self.add("unmet", "yes", 0.9, day=2, condition="polls stay bad")
        self.conn.execute("UPDATE predictions SET review = 'unreviewed'")
        answers = iter(["m", "x"])
        review.run(self.conn, read=lambda _: next(answers), write=lambda *_: None)
        got = dict(self.conn.execute("SELECT comment_id, condition_met FROM predictions"))
        self.assertEqual(got, {"c1": 1, "c2": 0})
        self.assertEqual(set(self.users()), {"met"})


class Migration(unittest.TestCase):
    def test_old_database_gets_new_columns(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("""CREATE TABLE predictions (comment_id TEXT, question_id INTEGER, relevant INTEGER,
                        stance TEXT, confidence REAL, quote TEXT, rationale TEXT, extractor TEXT,
                        review TEXT, reviewed_at INTEGER, created_at INTEGER,
                        PRIMARY KEY (comment_id, question_id))""")
        db._migrate(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(predictions)")}
        self.assertTrue({"hedge_phrase", "condition", "condition_met"} <= cols)


if __name__ == "__main__":
    unittest.main()
