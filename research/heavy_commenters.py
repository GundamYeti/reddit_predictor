"""For the heaviest commenters per subreddit, pull their week of comments and apply the phrase filter.

Usage: python research/heavy_commenters.py volume.json heavy.json
"""
import json, re, sys, time, urllib.parse, urllib.request

BASE = "https://arctic-shift.photon-reddit.com/api/comments/search"
UA = "reddit_predictor/0.2 (research; github.com/GundamYeti/reddit_predictor)"
START, END = 1720396800, 1720396800 + 7 * 86400
TOP = 15

# The broad prefilter: kept 37% of r/politics comments and 74 of 76 with a forecast.
RX = re.compile(r"\b(will|won't|wont|gonna|going to|bet|predict\w*|calling it|mark my words|no way|"
                r"probably|likely|unlikely|chance|odds|doubt|guarantee\w*|expect\w*|bound to|about to|"
                r"might|could|would|if|unrealistic|i don't see|ain't happening|certain)\b|\w'll\b", re.I)


def get(params):
    for attempt in range(4):
        time.sleep(2.5)
        try:
            req = urllib.request.Request(BASE + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
            d = json.load(urllib.request.urlopen(req, timeout=120))
            if d.get("data") is not None:
                return d["data"]
        except Exception:
            pass
        time.sleep(10 * (attempt + 1))
    return []


def comments(author, sub):
    after, out = START, []
    while True:
        batch = get({"author": author, "subreddit": sub, "after": after, "before": END, "limit": 100, "sort": "asc"})
        out += batch
        if len(batch) < 100:
            return out
        after = int(batch[-1]["created_utc"]) + 1


if __name__ == "__main__":
    vol = json.load(open(sys.argv[1]))
    res = {}
    for sub, counts in vol.items():
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:TOP]
        res[sub] = []
        for author, n in top:
            cs = [c for c in comments(author, sub) if c.get("body") not in ("[deleted]", "[removed]")]
            hits = [c for c in cs if RX.search(c["body"].replace("’", "'"))]
            lens = sorted(len(c["body"]) for c in cs) or [0]
            res[sub].append({"author": author, "agg_count": n, "fetched": len(cs), "filtered": len(hits),
                             "median_len": lens[len(lens) // 2]})
            print(sub, author, n, len(cs), len(hits), flush=True)
    json.dump(res, open(sys.argv[2], "w"), indent=1)
