"""Roadmap step 5: which Claude setup is cheapest without losing accuracy?

Compares other extractors with Opus 5.5 (the reference) on the same comments:
- single: one comment per request, via `python -m predictor pilot extract --model ...`
- packed: N comments per request (run here with --pack N, or through the
  Batch API with `python -m predictor batch submit`), stored as extractor
  "claude:<model>+packedN" in the same tables.

Usage:
  python research/model_compare.py --pack 20 --model claude-sonnet-5-5   # run a packed extractor
  python research/model_compare.py --report                                # compare everything on pilot1
"""
import argparse, json, sqlite3, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from predictor import db, llm, pilot

REFERENCE = "claude:claude-opus-5-5"

def run_packed(conn, model, n, tag):
    backend = llm.get_backend("claude", model)
    name = f"{backend.name}+packed{n}"
    done = {r[0] for r in conn.execute("SELECT comment_id FROM scans WHERE extractor = ?", (name,))}
    todo = [c for c in pilot.sample(conn, tag) if c["id"] not in done]
    print(f"{len(todo)} comments to scan as {name}", flush=True)
    for i in range(0, len(todo), n):
        chunk = todo[i:i + n]
        before = (backend.input_tokens + backend.cache_read_tokens + backend.cache_write_tokens, backend.output_tokens)
        try:
            result = backend.complete_json(pilot.PACKED_SYSTEM, pilot.packed_prompt(chunk), pilot.PACKED_SCHEMA)
        except Exception as e:
            print(f"  chunk {i // n + 1} failed: {e}", flush=True)
            continue
        by_id = {str(r.get("id")): r for r in result.get("comments") or []}
        # Spread the request's tokens evenly over its comments, for per-comment cost figures.
        tin = (backend.input_tokens + backend.cache_read_tokens + backend.cache_write_tokens - before[0]) // len(chunk)
        tout = (backend.output_tokens - before[1]) // len(chunk)
        for c in chunk:
            r = by_id.get(c["id"])
            if r is None:  # the model skipped this comment; leave it for a rerun
                continue
            pilot.store(conn, c["id"], name, r, tin, tout)
        conn.commit()
        missing = len(chunk) - sum(c["id"] in by_id for c in chunk)
        print(f"  chunk {i // n + 1}: {len(chunk)} comments{f', {missing} skipped by the model' if missing else ''},"
              f" cost so far ${backend.cost():.2f}", flush=True)
    if backend.cost():
        db.record_spend(conn, backend.cost(), f"model_compare packed {name} on {tag}")
    print(f"Done. Cost ${backend.cost():.2f}.")


def report(conn, tag):
    ref = dict(conn.execute("""SELECT s.comment_id, s.n_forecasts FROM scans s JOIN comments cm ON cm.id = s.comment_id
                               WHERE cm.source = ? AND s.extractor = ?""", (tag, REFERENCE)).fetchall())
    extractors = [r[0] for r in conn.execute(
        "SELECT DISTINCT s.extractor FROM scans s JOIN comments cm ON cm.id = s.comment_id WHERE cm.source = ?",
        (tag,))]
    print(f"Compared with {REFERENCE} on {len(ref)} comments of {tag!r}; "
          f"Opus found forecasts in {sum(n > 0 for n in ref.values())} of them.\n")
    print(f"{'extractor':42} {'scanned':>7} {'agree':>6} {'catches Opus':>13} {'extra flags':>11} {'forecasts':>9}")
    for ex in sorted(extractors):
        mine = dict(conn.execute("""SELECT s.comment_id, s.n_forecasts FROM scans s JOIN comments cm
                                    ON cm.id = s.comment_id WHERE cm.source = ? AND s.extractor = ?""", (tag, ex)))
        both = [c for c in mine if c in ref]
        pos = [c for c in both if ref[c] > 0]
        caught = sum(mine[c] > 0 for c in pos)
        extra = sum(mine[c] > 0 and ref[c] == 0 for c in both)
        agree = sum((mine[c] > 0) == (ref[c] > 0) for c in both)
        print(f"{ex:42} {len(both):>7} {agree / max(len(both), 1):>6.0%} {caught:>6}/{len(pos):<3} ({caught / max(len(pos), 1):.0%})"
              f" {extra:>5} {sum(mine[c] for c in both):>9}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="pilot1")
    p.add_argument("--model", default="claude-sonnet-5-5")
    p.add_argument("--pack", type=int, help="comments per request")
    p.add_argument("--report", action="store_true")
    a = p.parse_args()
    llm.load_dotenv(str(ROOT / ".env"))
    conn = sqlite3.connect(ROOT / "data" / "predictor.db")
    conn.row_factory = sqlite3.Row
    if a.report:
        report(conn, a.tag)
    elif a.pack:
        run_packed(conn, a.model, a.pack, a.tag)
    else:
        sys.exit("Use --pack N to run a packed extractor, or --report.")


if __name__ == "__main__":
    main()
