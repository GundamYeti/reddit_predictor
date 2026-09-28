"""Tag comments against a question: is this a forecast, which side, how sure?"""

import sys
import time

SYSTEM = """You read Reddit comments and decide whether each one is a forecast about a specific yes/no question.

A forecast says what the author EXPECTS to happen. Most political comments instead say what the author WANTS to happen. Those are not forecasts.

NOT forecasts (the author's wish, advice or judgment):
- "He needs to drop out." / "He should step aside." / "He must go." / "I hope he drops out."
- "If he stays, we lose." (a warning about a hypothetical, not a prediction of what he will do)
- Questions, jokes, news reports, or things that already happened.

Forecasts (the author's expectation):
- "He'll stay in and lose." / "He's not going anywhere." / "Biden is not dropping out." (expects NO)
- "He'll be gone by August." / "Calling it now, he drops out within two weeks." (expects YES)

Watch for sarcasm, which is common in political threads. "Oh sure, he'll definitely drop out, any day now" means the author expects NO. If you cannot tell which way the author leans, mark it not relevant.

Confidence is the probability the author seems to put on their own stance, from 0.5 to 0.99. Read it from their wording:
- "might", "could", "wouldn't be surprised": 0.55-0.6
- "I think", "probably", "likely": 0.65-0.75
- "very likely", "I'd bet", "almost certainly": 0.8-0.9
- plain statements ("He'll stay in"), "definitely", "guaranteed", "mark my words": 0.9-0.99"""

SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "stance": {"type": "string", "enum": ["yes", "no", "none"]},
        "confidence": {"type": "number"},
        "quote": {"type": "string"},
        "rationale": {"type": "string"},
    },
    "required": ["relevant", "stance", "confidence", "quote", "rationale"],
    "additionalProperties": False,
}


def build_prompt(question, comment):
    from datetime import datetime, timezone
    when = datetime.fromtimestamp(comment["created_utc"], timezone.utc).strftime("%Y-%m-%d")
    return f"""Question: {question['text']}
How it resolves: {question['criteria'] or '(not specified)'}

Comment posted {when} in r/{comment['subreddit']}:
<comment>
{comment['body'][:2500]}
</comment>

Return JSON:
- relevant: true only if the comment forecasts this question
- stance: "yes" if the author expects the answer to be YES, "no" if they expect NO, "none" if not relevant
- confidence: 0.5-0.99 (use 0.5 if not relevant)
- quote: the shortest exact excerpt that shows the forecast ("" if not relevant)
- rationale: one short sentence"""


def clean(result):
    """Clamp model output into values the database accepts."""
    relevant = bool(result.get("relevant")) and result.get("stance") in ("yes", "no")
    conf = result.get("confidence")
    try:
        conf = min(0.99, max(0.5, float(conf)))
    except (TypeError, ValueError):
        conf = 0.6
    return {
        "relevant": int(relevant),
        "stance": result["stance"] if relevant else None,
        "confidence": conf if relevant else None,
        "quote": (result.get("quote") or "")[:1000] if relevant else "",
        "rationale": (result.get("rationale") or "")[:500],
    }


def candidates(conn, question, limit=None):
    """Comments in the question's time window, matching its keywords, not yet classified."""
    sql = """SELECT c.* FROM comments c
             WHERE c.created_utc < ?
               AND (? IS NULL OR c.created_utc >= ?)
               AND NOT EXISTS (SELECT 1 FROM predictions p
                               WHERE p.comment_id = c.id AND p.question_id = ?)"""
    args = [question["closes_at"], question["opens_at"], question["opens_at"], question["id"]]
    keywords = [k.strip().lower() for k in question["keywords"].split(",") if k.strip()]
    if keywords:
        sql += " AND (" + " OR ".join("instr(lower(c.body), ?) > 0" for _ in keywords) + ")"
        args += keywords
    sql += " ORDER BY c.created_utc"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, args).fetchall()


def run(conn, backend, question, limit=None, out=sys.stdout):
    rows = candidates(conn, question, limit)
    print(f"Question #{question['id']}: {len(rows)} comments to classify with {backend.name}", file=out)
    found = failed = 0
    for i, c in enumerate(rows, 1):
        start = time.monotonic()
        try:
            result = clean(backend.complete_json(SYSTEM, build_prompt(question, c), SCHEMA))
        except Exception as e:  # one bad comment shouldn't stop an overnight run
            failed += 1
            print(f"  [{i}/{len(rows)}] {c['id']}: failed ({e})", file=out)
            continue
        conn.execute(
            """INSERT INTO predictions (comment_id, question_id, relevant, stance, confidence,
                                        quote, rationale, extractor)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (c["id"], question["id"], result["relevant"], result["stance"], result["confidence"],
             result["quote"], result["rationale"], backend.name),
        )
        conn.commit()
        found += result["relevant"]
        tag = f"{result['stance'].upper()} @ {result['confidence']:.2f}" if result["relevant"] else "not a forecast"
        print(f"  [{i}/{len(rows)}] u/{c['author']}: {tag} ({time.monotonic() - start:.1f}s)", file=out)
    print(f"Done: {found} forecasts found, {failed} failed (failed ones are retried next run).", file=out)
    cost = getattr(backend, "cost", lambda: None)()
    if cost is not None:
        print(f"Estimated cost: ${cost:.2f} for {len(rows) - failed} comments "
              f"(${cost / max(1, len(rows) - failed) * 1000:.2f} per 1,000).", file=out)
    return found, failed
