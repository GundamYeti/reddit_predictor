"""Batch API path, with a fake client standing in for Anthropic's.

Run: python -m unittest discover tests
"""

import json
import os
import unittest
from types import SimpleNamespace as NS

from predictor import batch, db

os.environ.setdefault("AI_ACTIVITY_LOG", os.devnull)


def usage(inp=100, out=50):
    return NS(input_tokens=inp, output_tokens=out, cache_read_input_tokens=0, cache_creation_input_tokens=0)


class FakeBatches:
    def __init__(self):
        self.created = []
        self.status = "in_progress"
        self.answers = {}  # custom_id -> result

    def create(self, requests):
        self.created.append(requests)
        return NS(id=f"batch_{len(self.created)}")

    def retrieve(self, batch_id):
        return NS(processing_status=self.status,
                  request_counts=NS(processing=1, succeeded=0, errored=0))

    def results(self, batch_id):
        return [NS(custom_id=cid, result=r) for cid, r in self.answers.items()]


def succeeded(comments):
    text = json.dumps({"comments": comments})
    return NS(type="succeeded", message=NS(stop_reason="end_turn", usage=usage(),
                                            content=[NS(type="text", text=text)]))


def forecast(prop):
    return {"proposition": prop, "direction": "happens", "deadline": "", "hedge_phrase": "probably",
            "condition": "", "sarcastic": False, "quote": prop}


class Batch(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.insert_comments(self.conn, [
            {"id": f"k{i}", "author": f"user{i}", "subreddit": "politics", "body": f"comment {i}",
             "created_utc": 1720000000 + i, "score": 1, "link_id": None, "parent_id": None, "permalink": ""}
            for i in range(5)], "s1")
        self.fake = FakeBatches()
        self.client = NS(messages=NS(batches=self.fake))
        self.log = []

    def submit(self, **kw):
        return batch.submit(self.conn, self.client, "s1", pack=2, out=self.log.append, **kw)

    def test_submit_packs_comments_and_remembers_them(self):
        bid = self.submit()
        self.assertEqual(bid, "batch_1")
        requests = self.fake.created[0]
        self.assertEqual(len(requests), 3)  # 5 comments, 2 per request
        self.assertEqual(requests[0]["params"]["model"], batch.DEFAULT_MODEL)
        self.assertIn("cache_control", requests[0]["params"]["system"][0])
        # Comments waiting in a batch aren't sent again.
        self.assertIsNone(self.submit())
        self.assertIn("Nothing to send", self.log[-1])

    def test_budget_refuses_and_limit_fits(self):
        db.record_spend(self.conn, 9.99999, "earlier")
        self.assertIsNone(self.submit())
        self.assertIn("Not sent", self.log[-1])
        db.record_spend(self.conn, -9.99999, "refund")
        self.assertEqual(self.submit(limit=2), "batch_1")

    def test_collect_waits_then_stores_and_resends_the_rest(self):
        self.submit()
        self.assertFalse(batch.collect(self.conn, self.client, "batch_1", out=self.log.append))
        self.fake.status = "ended"
        chunks = {cid: json.loads(ids) for cid, ids in self.conn.execute(
            "SELECT custom_id, comment_ids FROM batch_requests WHERE batch_id = 'batch_1'")}
        a, b = chunks["r0"]
        c, skipped = chunks["r1"]
        failed, = chunks["r2"]
        self.fake.answers = {
            "r0": succeeded([{"id": a, "forecasts": [forecast("X wins")], "note": ""},
                             {"id": b, "forecasts": [], "note": ""}]),
            "r1": succeeded([{"id": c, "forecasts": [], "note": ""}]),  # the model skipped one
            "r2": NS(type="errored"),
        }
        self.assertTrue(batch.collect(self.conn, self.client, "batch_1", out=self.log.append))
        name = batch.extractor_name(batch.DEFAULT_MODEL, 2)
        scanned = {r[0] for r in self.conn.execute("SELECT comment_id FROM scans WHERE extractor = ?", (name,))}
        self.assertEqual(scanned, {a, b, c})
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM forecasts").fetchone()[0], 1)
        self.assertGreater(db.month_spend(self.conn), 0)
        # The skipped and failed comments go out in the next batch.
        self.submit()
        sent = [json.loads(r[0]) for r in self.conn.execute(
            "SELECT comment_ids FROM batch_requests WHERE batch_id = 'batch_2'")]
        self.assertEqual(sorted(i for ids in sent for i in ids), sorted([skipped, failed]))

    def test_estimate_is_conservative_against_the_measured_cost(self):
        # Measured: packed Sonnet $0.83 per 1,000 comments, so $0.415 with the batch discount.
        self.assertGreater(batch.estimate("claude-sonnet-5-5", 1000, 20), 0.415)


if __name__ == "__main__":
    unittest.main()
