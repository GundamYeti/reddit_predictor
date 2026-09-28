"""Discovery pilot: extraction, blind labeling set, and report, with a scripted model."""

import os
import unittest

from predictor import db, pilot, sources

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_comments.jsonl")

# What the scripted model "finds" in each synthetic comment, keyed by a phrase in its body.
SCRIPT = {
    "definitely staying": [{"proposition": "Biden withdraws from the 2024 race", "direction": "does_not_happen",
                            "deadline": "", "hedge_phrase": "definitely", "condition": "", "sarcastic": False,
                            "quote": "He's definitely staying"}],
    "Calling it now": [{"proposition": "Biden withdraws from the 2024 race", "direction": "happens",
                        "deadline": "within two weeks", "hedge_phrase": "Calling it now", "condition": "",
                        "sarcastic": False, "quote": "Calling it now"}],
    "any day now": [{"proposition": "Biden withdraws from the 2024 race", "direction": "does_not_happen",
                     "deadline": "", "hedge_phrase": "", "condition": "", "sarcastic": True, "quote": "any day now"},
                    {"proposition": "", "direction": "happens", "deadline": "", "hedge_phrase": "",
                     "condition": "", "sarcastic": False, "quote": ""}],  # junk: must be dropped
}


class FakeBackend:
    name = "fake"

    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.input_tokens = self.output_tokens = 0

    def complete_json(self, system, prompt, schema):
        if self.fail_on and self.fail_on in prompt:
            raise RuntimeError("simulated API error")
        self.input_tokens += 100
        self.output_tokens += 10
        return {"forecasts": next((v for k, v in SCRIPT.items() if k in prompt), []), "note": ""}


class Pilot(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        db.insert_comments(self.conn, sources.dump_file(FIXTURE), "pilotX")
        self.out = open(os.devnull, "w")

    def tearDown(self):
        self.conn.close()
        self.out.close()

    def test_sample_order_is_stable(self):
        a = [c["id"] for c in pilot.sample(self.conn, "pilotX")]
        self.assertEqual(len(a), 8)
        self.assertEqual(a, [c["id"] for c in pilot.sample(self.conn, "pilotX")])
        self.assertNotEqual(a, sorted(a))  # shuffled, not in id order

    def test_extract_stores_forecasts_and_skips_done(self):
        found, failed = pilot.extract(self.conn, FakeBackend(fail_on="Pizza"), "pilotX", out=self.out)
        self.assertEqual((found, failed), (3, 1))
        rows = self.conn.execute("SELECT * FROM forecasts").fetchall()
        self.assertEqual(sorted(r["comment_id"] for r in rows), ["c1", "c4", "c8"])
        self.assertEqual(self.conn.execute("SELECT sarcastic FROM forecasts WHERE comment_id='c8'").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0], 7)
        # Second run only retries the failed one.
        found, failed = pilot.extract(self.conn, FakeBackend(), "pilotX", out=self.out)
        self.assertEqual((found, failed), (0, 0))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0], 8)

    def test_label_set_is_random_slice_plus_flagged(self):
        pilot.extract(self.conn, FakeBackend(), "pilotX", out=self.out)
        ids = {c["id"] for c in pilot.label_set(self.conn, "pilotX", n_random=2)}
        first_two = {c["id"] for c in pilot.sample(self.conn, "pilotX")[:2]}
        self.assertEqual(ids, first_two | {"c1", "c4", "c8"})

    def test_label_and_report(self):
        pilot.extract(self.conn, FakeBackend(), "pilotX", out=self.out)
        truth = {"c1": "f", "c4": "f", "c8": "n", "c2": "f", "c3": "n", "c5": "n", "c9": "n", "c10": "c"}
        todo = pilot.label_set(self.conn, "pilotX", n_random=8)
        answers = iter([truth[c["id"]] + " note" for c in todo])
        self.assertEqual(pilot.label(self.conn, "pilotX", 8, read=lambda _: next(answers), write=lambda *_: None), 8)
        self.assertEqual(self.conn.execute("SELECT note FROM labels WHERE comment_id='c1'").fetchone()[0], "note")

        lines = []
        pilot.report(self.conn, "pilotX", n_random=8, write=lines.append)
        text = "\n".join(lines)
        # You marked c1, c2, c4, c10 (4 of 8); the model caught c1 and c4.
        self.assertIn("4 contain a forecast (50%)", text)
        self.assertIn("found 2 of the 4 you marked (recall 50%)", text)
        # The model flagged c1, c4, c8; you agreed on c1 and c4.
        self.assertIn("you agreed on 2 (precision 67%)", text)
        self.assertIn("definitely", text)
        self.assertIn("[sarcastic]", text)

    def test_label_quit_and_bad_input(self):
        answers = iter(["zzz", "s", "q"])
        n = pilot.label(self.conn, "pilotX", 8, read=lambda _: next(answers), write=lambda *_: None)
        self.assertEqual(n, 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM labels").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
