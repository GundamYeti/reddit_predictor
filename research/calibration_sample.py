"""Calibration samples (see PLAN.md, Findings).

Usage: python research/calibration_sample.py volume.json politics,neoliberal,... stats.json

Calibration samples: 100 phrase-filtered comments per subreddit from its 15 heaviest commenters
(Jul 8-14, 2024), stored as source calib_<sub> so `pilot extract --tag calib_<sub>` can scan them."""
import json, random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
from predictor import db, sources
from heavy_commenters import RX, comments  # same filter and fetcher as the volume measurement

vol = json.load(open(sys.argv[1]))
conn = db.connect(str(ROOT / "data" / "predictor.db"))
stats = {}
for sub in sys.argv[2].split(","):
    top = sorted(vol[sub].items(), key=lambda kv: -kv[1])[:15]
    passed, total = [], 0
    for author, _ in top:
        for raw in comments(author, sub):
            c = sources.normalize(raw)
            if not c:
                continue
            total += 1
            if RX.search(c["body"].replace("’", "'")):
                passed.append(c)
    random.Random(sub).shuffle(passed)
    db.insert_comments(conn, passed[:100], f"calib_{sub}")
    stats[sub] = {"heavy_comments": total, "passed_filter": len(passed), "sampled": min(100, len(passed))}
    print(sub, stats[sub], flush=True)
json.dump(stats, open(sys.argv[3], "w"), indent=1)
