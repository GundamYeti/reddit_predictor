"""Discovery pilot: find forecasts in unfiltered comments, without a preset question.

1. extract: a model lists every forecast in each comment of a sample, recording
   the claim, its direction, any deadline, the exact hedge phrase, whether it's
   conditional and whether it's sarcastic.
2. label:   you mark comments by hand, without seeing the model's answer. The
   set is a fixed random slice of the sample plus every comment the model
   flagged, shuffled together, so you can't tell which is which.
3. report:  how common forecasts are, how well the model matches you, which
   hedge phrases people use, and what they predict about.

See docs/research-review.md for why it's built this way.
"""

import collections
import hashlib
import sys
import textwrap
import time

SYSTEM = """You find forecasts in Reddit comments.

A forecast is the author's own expectation about a future event that could, at least in principle, be checked later: an election result, whether someone resigns, a bill passing, a court ruling, a price, a war ending.

These are NOT forecasts:
- Wishes, demands and advice: "He needs to drop out." "He should step aside." "I hope she wins."
- Moral or quality judgments: "He'd be a terrible nominee."
- Questions, jokes, and descriptions of what already happened.
- Statements about the present: "He's losing support."
- Other people's forecasts reported without agreement: "Pundits say he'll drop out."

These ARE forecasts:
- "He'll stay in and lose." (two forecasts: he stays in; he loses)
- "No way he's the nominee in November." (expects it NOT to happen)
- "Calling it now: Harris is the nominee within a month."
- Conditional forecasts: "If he stays in, Trump wins." Record the condition separately.

Sarcasm is common. "Oh sure, he'll definitely drop out, any day now" expects him NOT to drop out; record the real expectation and mark it sarcastic. If you can't tell which way the author leans, leave it out.

For each forecast:
- proposition: the event in plain words, stated POSITIVELY and self-contained, e.g. "Biden withdraws from the 2024 presidential race" (never "Biden does not withdraw"; use direction for that). Name people and things instead of "he" or "it" when the comment makes them clear.
- direction: "happens" if the author expects the proposition to come true, "does_not_happen" if they expect it not to.
- deadline: the time frame if stated ("by November", "this week"), else "".
- hedge_phrase: the author's EXACT words that show how sure they are ("probably", "no way", "I'd bet", "mark my words", "might"). Use "" if they simply state it as fact.
- condition: for "if A, then B" forecasts, A in plain words; else "".
- sarcastic: true or false.
- quote: the shortest exact excerpt containing the forecast.

Most comments contain no forecast. Return an empty list for those."""

SCHEMA = {
    "type": "object",
    "properties": {
        "forecasts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "proposition": {"type": "string"},
                    "direction": {"type": "string", "enum": ["happens", "does_not_happen"]},
                    "deadline": {"type": "string"},
                    "hedge_phrase": {"type": "string"},
                    "condition": {"type": "string"},
                    "sarcastic": {"type": "boolean"},
                    "quote": {"type": "string"},
                },
                "required": ["proposition", "direction", "deadline", "hedge_phrase",
                             "condition", "sarcastic", "quote"],
                "additionalProperties": False,
            },
        },
        "note": {"type": "string"},
    },
    "required": ["forecasts", "note"],
    "additionalProperties": False,
}

LABEL_KEYS = {"f": "forecast", "c": "conditional", "n": "not", "u": "unsure"}
LABEL_HELP = """  f = forecast   c = conditional forecast ("if A, then B")   n = not a forecast   u = can't tell
  add a note after the letter if you like, e.g.  f expects him to stay in
  s = skip for now   q = quit (progress is saved)"""


def build_prompt(comment):
    when = time.strftime("%Y-%m-%d", time.gmtime(comment["created_utc"]))
    return f"""Comment posted {when} in r/{comment['subreddit']}:
<comment>
{comment['body'][:2500]}
</comment>

List every forecast in this comment (usually none), plus a one-sentence note."""


def _order(comment_id, salt=""):
    """A stable pseudo-random order, so 'the random 100' is the same every run."""
    return hashlib.md5((salt + comment_id).encode()).hexdigest()


def sample(conn, tag):
    rows = conn.execute("SELECT * FROM comments WHERE source = ?", (tag,)).fetchall()
    return sorted(rows, key=lambda r: _order(r["id"]))


def _clean(f):
    text = lambda k, n=500: str(f.get(k) or "").strip()[:n]
    return {
        "proposition": text("proposition"),
        "direction": f.get("direction") if f.get("direction") in ("happens", "does_not_happen") else None,
        "deadline": text("deadline", 200),
        "hedge_phrase": text("hedge_phrase", 200),
        "condition": text("condition"),
        "sarcastic": int(bool(f.get("sarcastic"))),
        "quote": text("quote", 1000),
    }


def extract(conn, backend, tag, limit=None, out=sys.stdout):
    """Scan the sample in its fixed random order, skipping comments already scanned."""
    done = {r[0] for r in conn.execute("SELECT comment_id FROM scans WHERE extractor = ?", (backend.name,))}
    todo = [c for c in sample(conn, tag) if c["id"] not in done][:limit]
    print(f"{len(todo)} comments to scan with {backend.name} ({len(done)} already done)", file=out)
    found = failed = 0
    for i, c in enumerate(todo, 1):
        before = (getattr(backend, "input_tokens", 0), getattr(backend, "output_tokens", 0))
        start = time.monotonic()
        try:
            result = backend.complete_json(SYSTEM, build_prompt(c), SCHEMA)
        except Exception as e:  # keep going; failures are retried next run
            failed += 1
            print(f"  [{i}/{len(todo)}] {c['id']}: failed ({e})", file=out)
            continue
        items = [f for f in map(_clean, result.get("forecasts") or []) if f["proposition"] and f["direction"]]
        conn.executemany(
            """INSERT INTO forecasts (comment_id, extractor, proposition, direction, deadline,
                                      hedge_phrase, condition, sarcastic, quote)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(c["id"], backend.name, f["proposition"], f["direction"], f["deadline"],
              f["hedge_phrase"], f["condition"], f["sarcastic"], f["quote"]) for f in items])
        conn.execute(
            "INSERT INTO scans (comment_id, extractor, n_forecasts, note, tokens_in, tokens_out) VALUES (?, ?, ?, ?, ?, ?)",
            (c["id"], backend.name, len(items), str(result.get("note") or "")[:500],
             getattr(backend, "input_tokens", 0) - before[0], getattr(backend, "output_tokens", 0) - before[1]))
        conn.commit()
        found += len(items)
        summary = "; ".join(f"{'' if f['direction'] == 'happens' else 'NOT '}{f['proposition']}" for f in items)
        print(f"  [{i}/{len(todo)}] {len(items)} forecast(s) ({time.monotonic() - start:.1f}s) {summary[:120]}", file=out)
    print(f"Done: {found} forecasts in {len(todo) - failed} comments, {failed} failed.", file=out)
    cost = getattr(backend, "cost", lambda: None)()
    if cost is not None and len(todo) > failed:
        print(f"Estimated cost: ${cost:.2f} (${cost / (len(todo) - failed) * 1000:.2f} per 1,000 comments).", file=out)
    return found, failed


def label_set(conn, tag, n_random=100):
    """The first n_random of the sample plus every comment any model flagged."""
    comments = sample(conn, tag)
    flagged = {r[0] for r in conn.execute("SELECT DISTINCT comment_id FROM forecasts")}
    chosen = comments[:n_random] + [c for c in comments[n_random:] if c["id"] in flagged]
    return sorted(chosen, key=lambda r: _order(r["id"], "label"))


def label(conn, tag, n_random=100, read=input, write=print):
    labeled = {r[0] for r in conn.execute("SELECT comment_id FROM labels")}
    todo = [c for c in label_set(conn, tag, n_random) if c["id"] not in labeled]
    if not todo:
        write("Nothing left to label.")
        return 0
    write(f"{len(todo)} comments to label ({len(labeled)} done). You won't see the model's answer.\n"
          f"Reply comments are shown without the comment they reply to.\n{LABEL_HELP}")
    done = 0
    for i, c in enumerate(todo, 1):
        when = time.strftime("%Y-%m-%d", time.gmtime(c["created_utc"]))
        paragraphs = [textwrap.fill(line, 90) for line in c["body"][:2500].splitlines() if line.strip()]
        body = textwrap.indent("\n".join(paragraphs), "    ")
        write(f"\n{'-' * 90}\n[{i}/{len(todo)}] u/{c['author']} on {when}  {c['permalink']}\n{body}")
        while True:
            answer = read("> ").strip()
            key, _, note = answer.partition(" ")
            key = key.lower()
            if key == "q":
                write(f"Labeled {done}.")
                return done
            if key == "s":
                break
            if key in LABEL_KEYS:
                conn.execute("INSERT OR REPLACE INTO labels (comment_id, label, note) VALUES (?, ?, ?)",
                             (c["id"], LABEL_KEYS[key], note.strip()))
                conn.commit()
                done += 1
                break
            write(LABEL_HELP)
    write(f"\nLabeled {done}.")
    return done


def report(conn, tag, extractor=None, n_random=100, write=print):
    comments = sample(conn, tag)
    ids = {c["id"] for c in comments}
    if not comments:
        write(f"No comments tagged {tag!r}. Collect with: python -m predictor collect arctic ... --tag {tag}")
        return
    extractors = [r[0] for r in conn.execute("SELECT DISTINCT extractor FROM scans")]
    extractor = extractor or (extractors[-1] if extractors else None)
    scans = {r["comment_id"]: r for r in conn.execute("SELECT * FROM scans WHERE extractor = ?", (extractor,))
             if r["comment_id"] in ids}
    fc = [r for r in conn.execute("SELECT * FROM forecasts WHERE extractor = ?", (extractor,)) if r["comment_id"] in ids]
    labels = {r["comment_id"]: r["label"] for r in conn.execute("SELECT * FROM labels") if r["comment_id"] in ids}
    flagged = {r["comment_id"] for r in fc}
    positive = lambda cid: labels.get(cid) in ("forecast", "conditional")

    write(f"Sample {tag!r}: {len(comments)} comments. Model: {extractor or '(none yet)'}, scanned {len(scans)}.")

    # Your labels on the fixed random slice: the honest base rate and the model's recall.
    random_ids = [c["id"] for c in comments[:n_random]]
    rl = [cid for cid in random_ids if labels.get(cid) in ("forecast", "conditional", "not")]
    if rl:
        pos = [cid for cid in rl if positive(cid)]
        write(f"\nYour labels on the random slice: {len(rl)} labeled, {len(pos)} contain a forecast "
              f"({len(pos) / len(rl):.0%}).")
        caught = [cid for cid in pos if cid in flagged and cid in scans]
        scanned_pos = [cid for cid in pos if cid in scans]
        if scanned_pos:
            write(f"  Model found {len(caught)} of the {len(scanned_pos)} you marked (recall {len(caught) / len(scanned_pos):.0%}).")
    labeled_flagged = [cid for cid in flagged if labels.get(cid) in ("forecast", "conditional", "not")]
    if labeled_flagged:
        right = [cid for cid in labeled_flagged if positive(cid)]
        write(f"  Of {len(labeled_flagged)} comments the model flagged that you labeled, you agreed on "
              f"{len(right)} (precision {len(right) / len(labeled_flagged):.0%}).")
    if not labels:
        write("\nNo hand labels yet: run  python -m predictor pilot label")

    if scans:
        write(f"\nModel: {len(fc)} forecasts in {len(flagged)} of {len(scans)} comments "
              f"({len(flagged) / len(scans):.0%} of comments).")
        cond = sum(1 for f in fc if f["condition"])
        sarc = sum(1 for f in fc if f["sarcastic"])
        dead = sum(1 for f in fc if f["deadline"])
        bare = sum(1 for f in fc if not f["hedge_phrase"])
        n = max(1, len(fc))
        write(f"  conditional {cond} ({cond / n:.0%}), sarcastic {sarc} ({sarc / n:.0%}), "
              f"with a deadline {dead} ({dead / n:.0%}), stated as plain fact {bare} ({bare / n:.0%})")
        hedges = collections.Counter(f["hedge_phrase"].lower() for f in fc if f["hedge_phrase"])
        if hedges:
            write("\nHedge phrases used:")
            for phrase, k in hedges.most_common(25):
                write(f"  {k:>3}  {phrase}")
        write("\nWhat people predicted (NOT = expects it not to happen):")
        for f in sorted(fc, key=lambda f: f["proposition"].lower()):
            flags = "".join([" [if]" if f["condition"] else "", " [sarcastic]" if f["sarcastic"] else ""])
            write(f"  {'NOT ' if f['direction'] == 'does_not_happen' else '    '}{f['proposition']}"
                  f"{' (' + f['deadline'] + ')' if f['deadline'] else ''}"
                  f"{' «' + f['hedge_phrase'] + '»' if f['hedge_phrase'] else ''}{flags}")
        tin = sum(s["tokens_in"] for s in scans.values())
        tout = sum(s["tokens_out"] for s in scans.values())
        if tin:
            from .llm import PRICES
            model = extractor.split(":", 1)[-1]
            if model in PRICES:
                cost = (tin * PRICES[model][0] + tout * PRICES[model][1]) / 1e6
                write(f"\nTokens: {tin:,} in, {tout:,} out. Estimated cost so far: ${cost:.2f}.")
