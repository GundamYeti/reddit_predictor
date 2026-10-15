"""Roadmap step 5: which Claude setup is cheapest without losing accuracy?

Compares other extractors with Opus 5.5 (the reference) on the same comments:
- single: one comment per request, via `python -m predictor pilot extract --model ...`
- packed: N comments per request (run here with --pack N), stored as
  extractor "claude:<model>+packedN" in the same tables.

Usage:
  python research/model_compare.py --pack 20 --model claude-sonnet-5-5   # run a packed extractor
  python research/model_compare.py --report                                # compare everything on pilot1
"""
import argparse, json, sqlite3, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from predictor import llm, pilot

REFERENCE = "claude:claude-opus-5-5"

PACKED_SYSTEM = pilot.SYSTEM + """

You will get several comments at once, each with an id. Treat each comment on its own, as if it were the only one: never carry names or context from one comment to another. Return one entry per comment id, in any order, with an empty forecast list for comments that contain none."""

PACKED_SCHEMA = {
    "type": "object",
    "properties": {"comments": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "string"},
                       "forecasts": pilot.SCHEMA["properties"]["forecasts"],
                       "note": {"type": "string"}},
        "required": ["id", "forecasts", "note"], "additionalProperties": False}}},
    "required": ["comments"], "additionalProperties": False}


def packed_prompt(comments):
    parts = []
    for c in comments:
        when = time.strftime("%Y-%m-%d", time.gmtime(c["created_utc"]))
        parts.append(f'<comment id="{c["id"]}" posted="{when}" subreddit="r/{c["subreddit"]}">\n'
                     f'{c["body"][:2500]}\n</comment>')
    return "\n\n".join(parts) + "\n\nFor each comment id, list every forecast (usually none), plus a one-sentence note."


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
            result = backend.complete_json(PACKED_SYSTEM, packed_prompt(chunk), PACKED_SCHEMA)
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
            items = [f for f in map(pilot._clean, r.get("forecasts") or []) if f["proposition"] and f["direction"]]
            conn.executemany(
                """INSERT INTO forecasts (comment_id, extractor, proposition, direction, deadline,
                                          hedge_phrase, condition, sarcastic, quote)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(c["id"], name, f["proposition"], f["direction"], f["deadline"], f["hedge_phrase"],
                  f["condition"], f["sarcastic"], f["quote"]) for f in items])
            conn.execute("INSERT INTO scans (comment_id, extractor, n_forecasts, note, tokens_in, tokens_out)"
                         " VALUES (?, ?, ?, ?, ?, ?)",
                         (c["id"], name, len(items), str(r.get("note") or "")[:500], tin, tout))
        conn.commit()
        missing = len(chunk) - sum(c["id"] in by_id for c in chunk)
        print(f"  chunk {i // n + 1}: {len(chunk)} comments{f', {missing} skipped by the model' if missing else ''},"
              f" cost so far ${backend.cost():.2f}", flush=True)
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
