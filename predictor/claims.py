"""Claims: group discovered forecasts into yes/no questions you can resolve.

Roadmap step 2. Nobody gets a score until forecasts are tied to questions with
an outcome, so this turns a sample's forecasts into a list of candidate
questions, each with the forecasts that answer it YES or NO.

  group:   per subreddit, a model drops forecasts that can never be checked
           (personal lives, unclear referents, sweeping claims) and groups the
           rest into self-contained yes/no questions; then claims asking the
           same question across subreddits are merged
  promote: you pick a claim and it becomes a question (yours, or a prediction
           market's: see markets.py); its forecasts become predictions in the
           review queue, and scoring works as for any question
"""

import collections
import json
import time

from . import db, hedges

GROUP_SYSTEM = """You turn forecasts found in Reddit comments into yes/no questions that can be checked later.

You get forecasts from one subreddit: id, the claim, which way the author expects it to go, any condition and deadline, and when it was posted.

Drop forecasts that can never be checked:
- about the commenter's own life or someone in the thread ("she'll make an excuse", "you'll regret it")
- unclear referents the forecast doesn't name ("the film", "he", "the bill") when you can't tell what it is
- opinions and sweeping, open-ended claims with no checkable event ("democracy goes out of style", "things get worse")
- about the subreddit itself or its moderators

Group the rest into claims. A claim is one self-contained yes/no question about a public event: name the people, teams, products and places; include the time frame the forecasts give ("by December 31, 2026", "in the 2026 midterms", "this season"). Forecasts that predict the same event belong to one claim even when they disagree; record for each the answer it expects (stance "yes" or "no"). A conditional forecast ("if A, then B") joins the claim about B; its condition is kept separately.

For each claim also give:
- deadline: the time frame in words, or "" if none was given
- search: 3-6 words to find a prediction market on it (names and key nouns, no filler)

Every forecast id must appear exactly once: in one claim's members, or in dropped."""

GROUP_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "deadline": {"type": "string"},
                "search": {"type": "string"},
                "members": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "stance": {"type": "string", "enum": ["yes", "no"]}},
                    "required": ["id", "stance"], "additionalProperties": False}},
            },
            "required": ["question", "deadline", "search", "members"], "additionalProperties": False}},
        "dropped": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["claims", "dropped"], "additionalProperties": False,
}

MERGE_SYSTEM = """You get yes/no questions written from different Reddit communities' forecasts. Find questions that ask about the same event in roughly the same time frame, so one answer settles both.

For each such group return:
- keep: the id whose wording is clearest
- merge: the other ids, each with same_direction true if YES on it means YES on the kept question, false if it means NO ("Will X win?" vs "Will X lose?")

Only return groups of two or more. Leave everything else out."""

MERGE_SCHEMA = {
    "type": "object",
    "properties": {"groups": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "keep": {"type": "integer"},
            "merge": {"type": "array", "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "same_direction": {"type": "boolean"}},
                "required": ["id", "same_direction"], "additionalProperties": False}},
        },
        "required": ["keep", "merge"], "additionalProperties": False}}},
    "required": ["groups"], "additionalProperties": False,
}

CHUNK = 120  # forecasts per grouping request


def _forecast_line(f):
    when = time.strftime("%Y-%m-%d", time.gmtime(f["created_utc"]))
    s = f"{f['id']} | {when} | {'EXPECTS' if f['direction'] == 'happens' else 'EXPECTS NOT'}: {f['proposition']}"
    if f["condition"]:
        s += f" | IF: {f['condition']}"
    if f["deadline"]:
        s += f" | BY: {f['deadline']}"
    return s


def ungrouped(conn, tag):
    """Forecasts from a sample that aren't in any claim yet (and weren't dropped)."""
    return conn.execute("""
        SELECT f.*, c.subreddit, c.created_utc FROM forecasts f JOIN comments c ON c.id = f.comment_id
        WHERE c.source = ? AND f.id NOT IN (SELECT forecast_id FROM claim_members)
          AND f.id NOT IN (SELECT forecast_id FROM claim_drops)
        ORDER BY c.subreddit, c.created_utc""", (tag,)).fetchall()


def group(conn, backend, tag, out=print):
    """Group a sample's forecasts into claims, subreddit by subreddit, then merge across subreddits."""
    todo = ungrouped(conn, tag)
    by_sub = collections.defaultdict(list)
    for f in todo:
        by_sub[f["subreddit"]].append(f)
    out(f"{len(todo)} forecasts to group from {len(by_sub)} subreddits with {backend.name}")
    new_claims = []
    for sub, fs in sorted(by_sub.items()):
        for i in range(0, len(fs), CHUNK):
            chunk = fs[i:i + CHUNK]
            valid = {f["id"] for f in chunk}
            try:
                result = backend.complete_json(GROUP_SYSTEM, f"Forecasts from r/{sub}:\n"
                                               + "\n".join(map(_forecast_line, chunk)), GROUP_SCHEMA, 16000)
            except Exception as e:
                out(f"  r/{sub} chunk {i // CHUNK + 1}: failed ({e}); rerun to retry")
                continue
            seen = set()
            for cl in result.get("claims") or []:
                members = [(m["id"], m["stance"]) for m in cl.get("members") or []
                           if m.get("id") in valid and m["id"] not in seen and m.get("stance") in ("yes", "no")]
                if not members or not str(cl.get("question") or "").strip():
                    continue
                seen.update(m for m, _ in members)
                cur = conn.execute("INSERT INTO claims (question, deadline, search, tag) VALUES (?, ?, ?, ?)",
                                   (cl["question"].strip()[:500], str(cl.get("deadline") or "")[:200],
                                    str(cl.get("search") or "")[:200], tag))
                conn.executemany("INSERT INTO claim_members (claim_id, forecast_id, stance) VALUES (?, ?, ?)",
                                 [(cur.lastrowid, m, s) for m, s in members])
                new_claims.append(cur.lastrowid)
            dropped = [d for d in result.get("dropped") or [] if d in valid and d not in seen]
            conn.executemany("INSERT OR IGNORE INTO claim_drops (forecast_id) VALUES (?)", [(d,) for d in dropped])
            conn.commit()
            missing = len(valid - seen - set(dropped))
            out(f"  r/{sub}: {len(chunk)} forecasts -> {len([c for c in result.get('claims') or []])} claims,"
                f" {len(dropped)} dropped" + (f", {missing} left out by the model (rerun to retry)" if missing else ""))
    if new_claims:
        merge(conn, backend, tag, out)
    _record_cost(conn, backend, f"claims group {tag}")


def merge(conn, backend, tag, out=print):
    """Fold claims that ask the same question into one."""
    rows = conn.execute("SELECT id, question, deadline FROM claims WHERE tag = ? AND merged_into IS NULL",
                        (tag,)).fetchall()
    if len(rows) < 2:
        return 0
    listing = "\n".join(f"{r['id']} | {r['question']}" + (f" | {r['deadline']}" if r["deadline"] else "") for r in rows)
    result = backend.complete_json(MERGE_SYSTEM, "Questions:\n" + listing, MERGE_SCHEMA, 16000)
    live = {r["id"] for r in rows}
    merged = 0
    for g in result.get("groups") or []:
        keep = g.get("keep")
        if keep not in live:
            continue
        for m in g.get("merge") or []:
            mid = m.get("id")
            if mid not in live or mid == keep:
                continue
            flip = not m.get("same_direction", True)
            for fid, stance in conn.execute("SELECT forecast_id, stance FROM claim_members WHERE claim_id = ?",
                                            (mid,)).fetchall():
                new = {"yes": "no", "no": "yes"}[stance] if flip else stance
                conn.execute("INSERT OR IGNORE INTO claim_members (claim_id, forecast_id, stance) VALUES (?, ?, ?)",
                             (keep, fid, new))
            conn.execute("DELETE FROM claim_members WHERE claim_id = ?", (mid,))
            conn.execute("UPDATE claims SET merged_into = ? WHERE id = ?", (keep, mid))
            live.discard(mid)
            merged += 1
    conn.commit()
    out(f"Merged {merged} duplicate claims across subreddits; {len(live)} claims remain.")
    return merged


def _record_cost(conn, backend, what):
    cost = getattr(backend, "cost", lambda: None)()
    if cost:
        db.record_spend(conn, cost, what)


def listing(conn, tag=None, min_authors=1, top=30):
    """Claims with their support: authors, forecasts, YES/NO split, subreddits, market match."""
    return conn.execute("""
        SELECT cl.id, cl.question, cl.deadline, cl.question_id, cl.market_id, m.question AS market_question,
               m.price_yes, m.outcome,
               COUNT(DISTINCT c.author) AS authors, COUNT(*) AS forecasts,
               SUM(cm.stance = 'yes') AS yes, SUM(cm.stance = 'no') AS no,
               GROUP_CONCAT(DISTINCT c.subreddit) AS subreddits
        FROM claims cl
        JOIN claim_members cm ON cm.claim_id = cl.id
        JOIN forecasts f ON f.id = cm.forecast_id
        JOIN comments c ON c.id = f.comment_id
        LEFT JOIN markets m ON m.id = cl.market_id
        WHERE cl.merged_into IS NULL AND (? IS NULL OR cl.tag = ?)
        GROUP BY cl.id HAVING authors >= ?
        ORDER BY authors DESC, forecasts DESC LIMIT ?""", (tag, tag, min_authors, top)).fetchall()


def promote(conn, claim_id, closes_at=None, text=None, criteria=None, use_market=True):
    """Make a claim a question and its forecasts predictions awaiting review. Returns the question id.

    With a matched market (and use_market), the question takes the market's wording,
    rules and end date, and `markets sync` resolves it when the market does.
    Otherwise closes_at (when the answer became known) is required.
    """
    cl = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if cl is None or cl["merged_into"]:
        raise ValueError(f"No claim #{claim_id}" + (f" (merged into #{cl['merged_into']})" if cl else ""))
    if cl["question_id"]:
        raise ValueError(f"Claim #{claim_id} is already question #{cl['question_id']}")
    market = None
    if use_market and cl["market_id"]:
        market = conn.execute("SELECT * FROM markets WHERE id = ?", (cl["market_id"],)).fetchone()
    if market:
        text = text or market["question"]
        criteria = criteria or (market["rules"][:2000] + f"\n\nResolves with Polymarket: {market['url']}")
        closes_at = closes_at or market["closed_at"] or market["end_date"]
        flip = cl["market_same"] == 0
    else:
        if not closes_at:
            raise ValueError("This claim has no matched market: give the date the answer became (or becomes) known")
        flip = False
    cur = conn.execute("INSERT INTO questions (text, criteria, closes_at, market_id) VALUES (?, ?, ?, ?)",
                       (text or cl["question"], criteria or "", closes_at, market["id"] if market else None))
    qid = cur.lastrowid
    rows = conn.execute("""SELECT cm.stance, f.* FROM claim_members cm JOIN forecasts f ON f.id = cm.forecast_id
                           WHERE cm.claim_id = ? ORDER BY f.id""", (claim_id,)).fetchall()
    for r in rows:
        stance = {"yes": "no", "no": "yes"}[r["stance"]] if flip else r["stance"]
        # One prediction per comment and question: a second forecast in the same comment is skipped.
        conn.execute("""INSERT OR IGNORE INTO predictions (comment_id, question_id, relevant, stance, confidence,
                            hedge_phrase, condition, quote, rationale, extractor)
                        VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
                     (r["comment_id"], qid, stance, hedges.confidence(r["hedge_phrase"]), r["hedge_phrase"],
                      r["condition"], r["quote"], f"from claim #{claim_id}: {r['proposition']}"[:500], r["extractor"]))
    conn.execute("UPDATE claims SET question_id = ? WHERE id = ?", (qid, claim_id))
    conn.commit()
    return qid
