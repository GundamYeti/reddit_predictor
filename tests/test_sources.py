"""Arctic Shift walking and splitting, against a fake archive (no network)."""

import unittest
import urllib.parse
from unittest import mock

from predictor import sources

START = 1720569600  # 2024-07-10 00:00 UTC


def fake_archive(max_span):
    """Times out on windows longer than max_span; otherwise returns one comment per hour."""
    def get_json(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        after, before = int(q["after"]), int(q["before"])
        if before - after > max_span:
            raise sources.SearchTimeout("Timeout. Maybe slow down a bit")
        first = -(-after // 3600) * 3600  # next whole hour
        return [{"id": f"h{t}", "author": "synthetic_user", "subreddit": "politics",
                 "body": "text", "created_utc": t} for t in range(first, before, 3600)]
    return get_json


class ArcticShift(unittest.TestCase):
    def collect(self, max_span, **kw):
        warnings = []
        with mock.patch.object(sources, "_get_json", fake_archive(max_span)):
            got = list(sources.arctic_shift("politics", START, START + 2 * sources.DAY, pause=0,
                                            warn=warnings.append, **kw))
        return got, warnings

    def test_splits_windows_that_time_out(self):
        got, warnings = self.collect(max_span=6 * 3600)
        self.assertEqual(len(got), 48)                      # every hour of both days
        self.assertEqual(len({c["id"] for c in got}), 48)   # no duplicates
        self.assertEqual(warnings, [])

    def test_gives_up_on_tiny_windows_with_a_warning(self):
        got, warnings = self.collect(max_span=60)
        self.assertEqual(got, [])
        self.assertTrue(warnings and "skipped" in warnings[0])

    def test_skips_a_window_that_keeps_failing(self):
        def flaky(url):
            if "after=%d&" % START in url or url.endswith("after=%d" % START):
                raise RuntimeError("Arctic Shift request failed after 5 tries: reset")
            return fake_archive(sources.DAY)(url)
        warnings = []
        with mock.patch.object(sources, "_get_json", flaky):
            got = list(sources.arctic_shift("politics", START, START + 2 * sources.DAY, pause=0,
                                            warn=warnings.append))
        self.assertEqual(len(got), 24)  # day 1 lost, day 2 kept
        self.assertEqual(len(warnings), 1)

    def test_per_day_and_limit(self):
        got, _ = self.collect(max_span=sources.DAY, per_day=5)
        self.assertEqual(len(got), 10)
        day1 = [c["created_utc"] - START for c in got if c["created_utc"] < START + sources.DAY]
        self.assertEqual(len(day1), 5)
        self.assertGreater(max(day1), 15 * 3600)  # spread across the day, not bunched at midnight
        got, _ = self.collect(max_span=sources.DAY, limit=7)
        self.assertEqual(len(got), 7)


if __name__ == "__main__":
    unittest.main()
