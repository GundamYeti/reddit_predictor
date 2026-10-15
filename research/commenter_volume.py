"""Commenter volume per subreddit for one week, via Arctic Shift author aggregates.

Usage: python research/commenter_volume.py politics,neoliberal,... volume.json
"""
import collections, json, sys, time, urllib.parse, urllib.request

BASE = "https://arctic-shift.photon-reddit.com/api/comments/search/aggregate"
UA = "reddit_predictor/0.2 (research; github.com/GundamYeti/reddit_predictor)"
SUBS = sys.argv[1].split(",")
import calendar, os
# The week sampled: RESEARCH_WEEK=YYYY-MM-DD (UTC), default the political samples' 2024-07-08.
START = calendar.timegm(time.strptime(os.environ.get("RESEARCH_WEEK", "2024-07-08"), "%Y-%m-%d"))
DAYS = int(os.environ.get("RESEARCH_DAYS", "7"))  # how many days from RESEARCH_WEEK
SKIP = {"[deleted]", "AutoModerator"}


def agg(sub, after, before):
    q = urllib.parse.urlencode({"aggregate": "author", "subreddit": sub, "after": after,
                                "before": before, "limit": 10000})
    for attempt in range(4):
        time.sleep(3)
        try:
            req = urllib.request.Request(f"{BASE}?{q}", headers={"User-Agent": UA})
            d = json.load(urllib.request.urlopen(req, timeout=120))
        except Exception as e:
            d = {"error": str(e)}
        if d.get("data") is not None:
            return d["data"]
        if before - after > 3600 * 3:  # split the window on timeouts
            mid = (after + before) // 2
            a, b = agg(sub, after, mid), agg(sub, mid, before)
            return a + b
        time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"{sub} {after}-{before}: {d}")


out = {}
for sub in SUBS:
    counts = collections.Counter()
    for d in range(DAYS):
        a = START + d * 86400
        for row in agg(sub, a, a + 86400):
            if row["key"] not in SKIP and not row["key"].lower().endswith("bot") and "modteam" not in row["key"].lower():
                counts[row["key"]] += int(row["count"])
    out[sub] = counts
    total = sum(counts.values())
    print(f"{sub}: {total} comments, {len(counts)} authors", flush=True)
json.dump({s: dict(c) for s, c in out.items()}, open(sys.argv[2], "w"))
