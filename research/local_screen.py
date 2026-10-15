"""Can the free local model work as a yes/no screen before Claude?

Runs the local Ollama model on every pilot comment that passes the broad phrase
filter, asking only "could this contain a prediction?", and compares its answer
with Claude's full extraction of the same comments.

Usage: python research/local_screen.py [--tag pilot1] [--report]
Results go to data/local_screen_<tag>.json and are resumed if interrupted.
"""
import argparse, json, sqlite3, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "research"))
from heavy_commenters import RX
from predictor.llm import get_backend

SYSTEM = """You screen Reddit comments for predictions.

Answer true if the author states their OWN expectation about a future event that could be checked later (an election result, someone resigning, a bill passing, a ruling, a price, a war ending), including "if X then Y" forecasts and sarcastic ones.

Answer false for wishes and demands ("he should drop out", "I hope she wins"), opinions, questions, jokes, things that already happened, the present, and other people's predictions the author doesn't share.

When unsure, answer true."""

SCHEMA = {"type": "object", "properties": {"prediction": {"type": "boolean"}}, "required": ["prediction"]}


def report(rows, res):
    truth = {cid: n > 0 for cid, _, n in rows}
    done = [cid for cid, _, _ in rows if cid in res and "prediction" in res[cid]]
    tp = sum(res[c]["prediction"] and truth[c] for c in done)
    fp = sum(res[c]["prediction"] and not truth[c] for c in done)
    fn = sum(not res[c]["prediction"] and truth[c] for c in done)
    pos = sum(truth[c] for c in done)
    secs = sorted(res[c]["seconds"] for c in done)
    print(f"Screened {len(done)}/{len(rows)} filtered comments.")
    if not done:
        return
    print(f"Flagged {tp + fp} ({(tp + fp) / len(done):.0%}) to send on to Claude.")
    print(f"Catches {tp}/{pos} of the comments where Claude found a forecast ({tp / max(pos, 1):.0%}); misses {fn}.")
    print(f"Median {secs[len(secs) // 2]:.0f} s per comment (slowest {secs[-1]:.0f} s).")


def unload(backend):
    """Unload the model so Ollama frees its memory. On the 7.5 GB laptop its memory
    crept up to 3.8 GB over ~25 comments and the kernel killed it (2026-10-15)."""
    import urllib.request
    body = json.dumps({"model": backend.model, "keep_alive": 0}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(backend.url + "/api/generate", data=body,
                               headers={"Content-Type": "application/json"}), timeout=60).read()
    except Exception:
        pass


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tag", default="pilot1")
    p.add_argument("--report", action="store_true", help="only print results so far")
    a = p.parse_args()

    conn = sqlite3.connect(ROOT / "data" / "predictor.db")
    rows = [(cid, body, n) for cid, body, n in conn.execute("""
        SELECT cm.id, cm.body, s.n_forecasts FROM comments cm JOIN scans s ON s.comment_id = cm.id
        WHERE cm.source = ? AND s.extractor LIKE 'claude:%' ORDER BY cm.id""", (a.tag,))
        if RX.search(body.replace("’", "'"))]
    out = ROOT / "data" / f"local_screen_{a.tag}.json"
    res = json.loads(out.read_text()) if out.exists() else {}
    if a.report:
        return report(rows, res)

    backend = get_backend("ollama")
    todo = [r for r in rows if r[0] not in res]
    print(f"{len(rows)} filtered comments, {len(todo)} to screen with {backend.name}", flush=True)
    for i, (cid, body, _) in enumerate(todo, 1):
        if i % 15 == 0:
            unload(backend)
        for attempt in range(5):
            start = time.monotonic()
            try:
                answer = backend.complete_json(SYSTEM, "Comment:\n" + body[:3000], SCHEMA)
                res[cid] = {"prediction": bool(answer.get("prediction")), "seconds": time.monotonic() - start}
                break
            except Exception as e:  # Ollama restarting (e.g. after running out of memory): wait and retry
                print(f"  [{i}] failed: {e}; retrying in 30 s", flush=True)
                time.sleep(30)
        else:
            sys.exit("Ollama keeps failing; rerun later to resume.")
        out.write_text(json.dumps(res))
        if i % 10 == 0 or i == len(todo):
            print(f"  [{i}/{len(todo)}]", flush=True)
            report(rows, res)
    report(rows, res)


if __name__ == "__main__":
    main()
