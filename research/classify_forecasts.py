"""Unstructured look at what kinds of predictions people make.

Step 1: Claude reads every forecast found so far and proposes categories (nothing preset).
Step 2: Claude assigns each forecast to those categories, in chunks.
Output: forecast_taxonomy.json and forecast_labels.json next to this script.
Both are reused if present, so delete them to start over. Cost on 477 forecasts: $0.99.

Only Opus 5.5's forecasts are used, so cheaper-model comparison runs don't add duplicates.

Usage: python research/classify_forecasts.py           # classify (resumes)
       python research/classify_forecasts.py --report  # breakdown per subreddit
"""
import json, os, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from predictor.llm import get_backend

HERE = Path(__file__).parent
conn = sqlite3.connect("data/predictor.db")
rows = conn.execute("""
    SELECT f.id, cm.source, cm.subreddit, f.direction, f.proposition, f.hedge_phrase, f.condition, f.sarcastic
    FROM forecasts f JOIN comments cm ON cm.id = f.comment_id
    WHERE f.extractor = 'claude:claude-opus-5-5' ORDER BY f.id""").fetchall()


def line(r):
    fid, _, sub, direction, prop, hedge, cond, sarc = r
    s = f"{fid} | r/{sub} | {'EXPECTS' if direction == 'happens' else 'EXPECTS NOT'}: {prop}"
    if cond:
        s += f" | IF: {cond}"
    if hedge:
        s += f" | hedge: {hedge}"
    if sarc:
        s += " | sarcastic"
    return s


def report():
    """Each dimension's categories, overall and per subreddit (the doomer sample on its own)."""
    import collections
    tax = json.loads((HERE / "forecast_taxonomy.json").read_text())
    labels = json.loads((HERE / "forecast_labels.json").read_text())
    group = {str(r[0]): ("doomer sample" if r[1].startswith("doom_") else "r/" + r[2]) for r in rows}
    labels = {k: v for k, v in labels.items() if k in group}
    sizes = collections.Counter(group[k] for k in labels)
    groups = sorted(sizes, key=lambda g: -sizes[g])
    print(f"{len(labels)} forecasts: " + ", ".join(f"{g} {sizes[g]}" for g in groups))
    for d in tax["dimensions"]:
        print(f"\n## {d['name']}")
        print(f"{'':40} {'all':>5} " + " ".join(f"{g[:12]:>12}" for g in groups))
        for c in d["categories"]:
            hits = [k for k, l in labels.items() if l.get(d["id"]) == c["id"]]
            per = collections.Counter(group[k] for k in hits)
            print(f"{c['name'][:40]:40} {len(hits) / len(labels):>5.0%} "
                  + " ".join(f"{per[g] / sizes[g]:>12.0%}" for g in groups))


if "--report" in sys.argv:
    report()
    sys.exit()

ALL = "\n".join(line(r) for r in rows)
print(f"{len(rows)} forecasts", file=sys.stderr)

TAX_SYSTEM = """You are helping design a study of the predictions people make in Reddit comments.
You get a list of forecasts already extracted from comments. Propose a classification that emerges from THIS data rather than from a preset scheme.

Give 4 to 6 dimensions. Each dimension is one independent way to sort forecasts (for example what it's about, what kind of claim it is, how checkable it is), with 3 to 9 mutually exclusive categories that together cover every forecast. Pick the dimensions that best reveal how these predictions differ and which ones could ever be scored as right or wrong. For each category give a short id, a name, a one-sentence definition, and two example forecast ids from the list."""

TAX_SCHEMA = {
    "type": "object",
    "properties": {"dimensions": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"}, "name": {"type": "string"}, "why": {"type": "string"},
            "categories": {"type": "array", "items": {
                "type": "object",
                "properties": {"id": {"type": "string"}, "name": {"type": "string"},
                               "definition": {"type": "string"},
                               "examples": {"type": "array", "items": {"type": "integer"}}},
                "required": ["id", "name", "definition", "examples"], "additionalProperties": False}}},
        "required": ["id", "name", "why", "categories"], "additionalProperties": False}}},
    "required": ["dimensions"], "additionalProperties": False}

backend = get_backend("claude")
tax_path = HERE / "forecast_taxonomy.json"
if tax_path.exists():
    tax = json.loads(tax_path.read_text())
else:
    os.environ["PREDICTOR_CLAUDE_EFFORT"] = "medium"
    tax = backend.complete_json(TAX_SYSTEM, "Forecasts:\n" + ALL, TAX_SCHEMA)
    tax_path.write_text(json.dumps(tax, indent=1))
    os.environ["PREDICTOR_CLAUDE_EFFORT"] = "low"
print(f"taxonomy done, cost so far ${backend.cost():.2f}", file=sys.stderr)

dims = tax["dimensions"]
guide = "\n\n".join(
    f"Dimension {d['id']} ({d['name']}):\n" + "\n".join(f"- {c['id']}: {c['definition']}" for c in d["categories"])
    for d in dims)
LABEL_SYSTEM = ("Assign each forecast exactly one category in every dimension below.\n\n" + guide)
LABEL_SCHEMA = {
    "type": "object",
    "properties": {"labels": {"type": "array", "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"},
                       **{d["id"]: {"type": "string", "enum": [c["id"] for c in d["categories"]]} for d in dims}},
        "required": ["id"] + [d["id"] for d in dims], "additionalProperties": False}}},
    "required": ["labels"], "additionalProperties": False}

lab_path = HERE / "forecast_labels.json"
labels = json.loads(lab_path.read_text()) if lab_path.exists() else {}
todo = [r for r in rows if str(r[0]) not in labels]
for i in range(0, len(todo), 60):
    chunk = todo[i:i + 60]
    out = backend.complete_json(LABEL_SYSTEM, "Forecasts:\n" + "\n".join(line(r) for r in chunk), LABEL_SCHEMA)
    for lab in out["labels"]:
        labels[str(lab.pop("id"))] = lab
    lab_path.write_text(json.dumps(labels))
    print(f"labeled {len(labels)}/{len(rows)}, cost so far ${backend.cost():.2f}", file=sys.stderr)
if backend.cost():
    from predictor import db
    db.record_spend(db.connect("data/predictor.db"), backend.cost(), "classify_forecasts")
