"""Prediction markets as ground truth (roadmap step 7).

Writing and resolving every question yourself doesn't scale. Polymarket already
has thousands of yes/no questions with written resolution rules, and resolves
them. This matches claims (claims.py) to Polymarket markets, so a promoted claim
takes the market's wording, rules and outcome, and resolves itself.

  match: for each claim, search Polymarket with the claim's search words, then
         a model checks which candidate (if any) asks the same question, and
         whether YES on the claim means YES or NO on the market
  sync:  refresh linked markets; when one resolves, its question resolves too
         (the cutoff moves to when the market actually closed, so later
         comments don't count as forecasts)

Polymarket's public API needs no key. Its rules are Polymarket's, not yours:
that's the trade-off for not resolving everything by hand.
"""

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime

from . import db

API = "https://gamma-api.polymarket.com"
USER_AGENT = "reddit_predictor/0.2 (research; github.com/GundamYeti/reddit_predictor)"
CANDIDATES = 8      # markets shown to the model per claim
CLAIMS_PER_REQUEST = 15

MATCH_SYSTEM = """You match yes/no questions written from Reddit forecasts to prediction-market questions.

For each claim you get candidate markets. Pick the market that asks the same question: the same event, and a deadline close enough that one answer settles both. A market about a related but different event (another threshold, another person, a much later date) is not a match. If none fits, answer "" for market.

same_direction is true if YES on the claim means YES on the market, false if it means NO (claim "Will X lose?" vs market "Will X win?")."""

MATCH_SCHEMA = {
    "type": "object",
    "properties": {"matches": {"type": "array", "items": {
        "type": "object",
        "properties": {"claim": {"type": "integer"},
                       "market": {"type": "string"},
                       "same_direction": {"type": "boolean"}},
        "required": ["claim", "market", "same_direction"], "additionalProperties": False}}},
    "required": ["matches"], "additionalProperties": False,
}


def _get(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except (OSError, ValueError):
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)


def _ts(s):
    if not s:
        return None
    return int(datetime.fromisoformat(str(s).replace("Z", "+00:00").replace(" ", "T")).timestamp())


def parse(m):
    """A Polymarket market as a row for the markets table, or None if it isn't a plain Yes/No market."""
    try:
        outcomes = json.loads(m.get("outcomes") or "[]")
        prices = [float(p) for p in json.loads(m.get("outcomePrices") or "[]")]
    except (TypeError, ValueError):
        return None
    if outcomes != ["Yes", "No"] or len(prices) != 2:
        return None
    outcome = None
    if m.get("closed") and m.get("umaResolutionStatus") == "resolved":
        outcome = "yes" if prices[0] >= 0.99 else "no" if prices[0] <= 0.01 else "void"
    slug = (m.get("events") or [{}])[0].get("slug") or m.get("slug") or ""
    return {"id": str(m["id"]), "source": "polymarket", "question": m.get("question") or "",
            "rules": m.get("description") or "", "url": f"https://polymarket.com/event/{slug}",
            "end_date": _ts(m.get("endDate")), "closed_at": _ts(m.get("closedTime")) if m.get("closed") else None,
            "outcome": outcome, "price_yes": prices[0]}


def save(conn, row):
    conn.execute("""INSERT INTO markets (id, source, question, rules, url, end_date, closed_at, outcome, price_yes, fetched_at)
                    VALUES (:id, :source, :question, :rules, :url, :end_date, :closed_at, :outcome, :price_yes, unixepoch())
                    ON CONFLICT(id) DO UPDATE SET question = excluded.question, rules = excluded.rules,
                        end_date = excluded.end_date, closed_at = excluded.closed_at, outcome = excluded.outcome,
                        price_yes = excluded.price_yes, fetched_at = excluded.fetched_at""", row)


def search(query, get=_get):
    """Plain Yes/No markets matching a query, open or closed."""
    q = urllib.parse.urlencode({"q": query, "limit_per_type": 6})
    found = []
    for event in (get(f"{API}/public-search?{q}") or {}).get("events") or []:
        for m in event.get("markets") or []:
            m.setdefault("events", [event])
            row = parse(m)
            if row:
                found.append(row)
    return found[:CANDIDATES]


def match(conn, backend, tag=None, min_authors=1, limit=None, get=_get, out=print):
    """Find a market for each unmatched, unpromoted claim."""
    claims = conn.execute("""
        SELECT cl.id, cl.question, cl.deadline, cl.search, COUNT(DISTINCT c.author) AS authors
        FROM claims cl JOIN claim_members cm ON cm.claim_id = cl.id
        JOIN forecasts f ON f.id = cm.forecast_id JOIN comments c ON c.id = f.comment_id
        WHERE cl.merged_into IS NULL AND cl.market_id IS NULL AND cl.question_id IS NULL
          AND cl.id NOT IN (SELECT claim_id FROM market_checks) AND (? IS NULL OR cl.tag = ?)
        GROUP BY cl.id HAVING authors >= ? ORDER BY authors DESC, cl.id LIMIT ?""",
        (tag, tag, min_authors, limit or -1)).fetchall()
    out(f"{len(claims)} claims to match against Polymarket with {backend.name}")
    matched = 0
    for i in range(0, len(claims), CLAIMS_PER_REQUEST):
        chunk = claims[i:i + CLAIMS_PER_REQUEST]
        blocks, offered = [], {}
        for cl in chunk:
            try:
                cands = search(cl["search"] or cl["question"], get)
            except Exception as e:
                out(f"  claim #{cl['id']}: search failed ({e}); rerun to retry")
                continue
            for row in cands:
                save(conn, row)
            offered[cl["id"]] = {row["id"] for row in cands}
            lines = [f'Claim {cl["id"]}: {cl["question"]}' + (f' (time frame: {cl["deadline"]})' if cl["deadline"] else "")]
            for row in cands:
                end = time.strftime("%Y-%m-%d", time.gmtime(row["end_date"])) if row["end_date"] else "?"
                lines.append(f'  market {row["id"]}: {row["question"]} (ends {end})')
            if not cands:
                lines.append("  (no candidates)")
            blocks.append("\n".join(lines))
        conn.commit()
        asked = [cl for cl in chunk if offered.get(cl["id"])]
        answers = {}
        if asked:
            result = backend.complete_json(MATCH_SYSTEM, "\n\n".join(blocks), MATCH_SCHEMA)
            answers = {a.get("claim"): a for a in result.get("matches") or []}
        for cl in chunk:
            if cl["id"] not in offered:
                continue  # search failed: try again next run
            a = answers.get(cl["id"]) or {}
            market = a.get("market")
            if market and str(market) in offered[cl["id"]]:
                conn.execute("UPDATE claims SET market_id = ?, market_same = ? WHERE id = ?",
                             (str(market), int(bool(a.get("same_direction", True))), cl["id"]))
                matched += 1
            conn.execute("INSERT OR IGNORE INTO market_checks (claim_id) VALUES (?)", (cl["id"],))
        conn.commit()
        out(f"  claims {i + 1}-{i + len(chunk)}: {matched} matched so far")
    cost = getattr(backend, "cost", lambda: None)()
    if cost:
        db.record_spend(conn, cost, "markets match")
    out(f"Matched {matched} of {len(claims)} claims to a Polymarket market.")
    return matched


def sync(conn, get=_get, out=print):
    """Refresh markets tied to open questions; resolve those questions when their market resolves."""
    rows = conn.execute("""SELECT q.id AS question_id, q.market_id FROM questions q
                           WHERE q.market_id IS NOT NULL AND q.status = 'open'""").fetchall()
    resolved = 0
    for r in rows:
        try:
            row = parse(get(f"{API}/markets/{urllib.parse.quote(r['market_id'])}"))
        except Exception as e:
            out(f"  market {r['market_id']}: fetch failed ({e})")
            continue
        if not row:
            continue
        save(conn, row)
        if row["outcome"]:
            # The answer was known when the market closed: comments after that are hindsight.
            conn.execute("UPDATE questions SET status = ?, closes_at = COALESCE(?, closes_at), resolved_at = unixepoch(),"
                         " notes = notes || ? WHERE id = ?",
                         (row["outcome"], row["closed_at"], f" Resolved {row['outcome'].upper()} by Polymarket.",
                          r["question_id"]))
            resolved += 1
            out(f"  question #{r['question_id']}: {row['outcome'].upper()} ({row['question']})")
    conn.commit()
    out(f"Checked {len(rows)} market-linked questions; {resolved} resolved.")
    return resolved
