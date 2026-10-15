"""Scan comments through the Batch API: half price, results within 24 hours.

Comments are packed several per request (pilot.PACKED_SYSTEM), so the fixed
instructions are paid for once per request. Measured on the pilot, packed
Sonnet 5.5 cost $0.83 per 1,000 comments before the batch discount.

  submit:  pick unscanned comments from a sample, refuse if the estimate would
           take this month's spend over the budget, send one batch
  collect: once the batch has ended, store every comment's forecasts and record
           the actual cost; comments the model skipped or that failed stay
           unscanned, so the next submit picks them up again

The monthly budget is PREDICTOR_MONTHLY_BUDGET dollars (default 10), counted
across everything recorded in the spend table, not just batches.
"""

import json
import os
import time

from . import db, llm, pilot
from .activity_log import log_call

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_PACK = 20
MAX_TOKENS = 16000  # room for 20 comments' worth of forecasts plus thinking

# Conservative per-comment token estimate for budgeting: the instructions
# (~1,300 tokens) shared by a request's comments, plus ~120 tokens of comment
# and ~90 tokens of answer each. Assumes no cache hits, so real costs come in lower.
EST_INSTRUCTIONS, EST_IN_PER_COMMENT, EST_OUT_PER_COMMENT = 1300, 120, 90


def budget():
    return float(os.environ.get("PREDICTOR_MONTHLY_BUDGET", "10"))


def extractor_name(model, pack):
    return f"claude:{model}+packed{pack}"


def estimate(model, n_comments, pack):
    per_comment_in = EST_INSTRUCTIONS / pack + EST_IN_PER_COMMENT
    return llm.cost_of(model, per_comment_in * n_comments, EST_OUT_PER_COMMENT * n_comments, batch=True) or 0.0


def pending_ids(conn, extractor):
    """Comments already sent in a batch that hasn't been collected yet."""
    ids = set()
    for (comment_ids,) in conn.execute(
            """SELECT r.comment_ids FROM batch_requests r JOIN batches b ON b.id = r.batch_id
               WHERE b.status = 'submitted' AND b.extractor = ?""", (extractor,)):
        ids.update(json.loads(comment_ids))
    return ids


def submit(conn, client, tag, model=DEFAULT_MODEL, pack=DEFAULT_PACK, limit=None, out=print):
    """Send one batch of unscanned comments from the sample; returns the batch id or None."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    name = extractor_name(model, pack)
    done = {r[0] for r in conn.execute("SELECT comment_id FROM scans WHERE extractor = ?", (name,))}
    skip = done | pending_ids(conn, name)
    todo = [c for c in pilot.sample(conn, tag) if c["id"] not in skip][:limit]
    if not todo:
        out(f"Nothing to send: every comment in {tag!r} is scanned or waiting in a batch.")
        return None
    est = estimate(model, len(todo), pack)
    spent, cap = db.month_spend(conn), budget()
    if spent + est > cap:
        out(f"Not sent: {len(todo)} comments would cost about ${est:.2f}, and ${spent:.2f} of this month's "
            f"${cap:.2f} budget is already spent. Use --limit, or raise PREDICTOR_MONTHLY_BUDGET.")
        return None

    chunks = [todo[i:i + pack] for i in range(0, len(todo), pack)]
    requests = [Request(custom_id=f"r{i}",
                        params=MessageCreateParamsNonStreaming(**llm.request_params(
                            model, pilot.PACKED_SYSTEM, pilot.packed_prompt(chunk), pilot.PACKED_SCHEMA, MAX_TOKENS)))
                for i, chunk in enumerate(chunks)]
    created = client.messages.batches.create(requests=requests)
    conn.execute("INSERT INTO batches (id, extractor, tag, n_comments, est_cost) VALUES (?, ?, ?, ?, ?)",
                 (created.id, name, tag, len(todo), est))
    conn.executemany("INSERT INTO batch_requests (batch_id, custom_id, comment_ids) VALUES (?, ?, ?)",
                     [(created.id, f"r{i}", json.dumps([c["id"] for c in chunk])) for i, chunk in enumerate(chunks)])
    conn.commit()
    out(f"Sent batch {created.id}: {len(todo)} comments in {len(chunks)} requests with {name}, "
        f"estimated ${est:.2f} (this month so far: ${spent:.2f} of ${cap:.2f}).")
    return created.id


def collect(conn, client, batch_id, out=print):
    """Store a finished batch's results. Returns False if it's still running."""
    row = conn.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if row is None or row["status"] != "submitted":
        out(f"{batch_id}: nothing to collect.")
        return True
    remote = client.messages.batches.retrieve(batch_id)
    if remote.processing_status != "ended":
        c = remote.request_counts
        out(f"{batch_id}: still {remote.processing_status} ({c.processing} requests to go, {c.succeeded} done).")
        return False

    model = row["extractor"].split(":", 1)[1].split("+", 1)[0]
    chunks = {r["custom_id"]: json.loads(r["comment_ids"])
              for r in conn.execute("SELECT * FROM batch_requests WHERE batch_id = ?", (batch_id,))}
    comments = {c["id"]: c for c in conn.execute(
        f"SELECT id FROM comments WHERE id IN ({','.join('?' * sum(map(len, chunks.values())))})",
        [i for ids in chunks.values() for i in ids])}
    already = {r[0] for r in conn.execute("SELECT comment_id FROM scans WHERE extractor = ?", (row["extractor"],))}
    tokens = {"in": 0, "out": 0, "read": 0, "write": 0}
    stored = forecasts = skipped = failed = 0
    for result in client.messages.batches.results(batch_id):
        ids = chunks.get(result.custom_id, [])
        if result.result.type != "succeeded":
            failed += len(ids)  # errored, canceled or expired: these comments get resent next time
            continue
        message = result.result.message
        u = message.usage
        tokens["in"] += u.input_tokens
        tokens["out"] += u.output_tokens
        tokens["read"] += u.cache_read_input_tokens or 0
        tokens["write"] += u.cache_creation_input_tokens or 0
        try:
            answer = llm.message_json(message)
        except Exception:
            failed += len(ids)
            continue
        by_id = {str(r.get("id")): r for r in answer.get("comments") or []}
        total_in = u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
        for cid in ids:
            if cid not in by_id:
                skipped += 1
                continue
            if cid in already or cid not in comments:
                continue
            forecasts += len(pilot.store(conn, cid, row["extractor"], by_id[cid],
                                         total_in // len(ids), u.output_tokens // len(ids)))
            stored += 1
    cost = llm.cost_of(model, tokens["in"], tokens["out"], tokens["read"], tokens["write"], batch=True) or 0.0
    conn.execute("UPDATE batches SET status = 'collected', cost = ?, collected_at = ? WHERE id = ?",
                 (cost, int(time.time()), batch_id))
    conn.commit()
    db.record_spend(conn, cost, f"batch {batch_id} ({row['extractor']}, {row['tag']})")
    log_call("reddit_predictor", "claude-batch", model, 0, preview=f"batch {batch_id}",
             input_tokens=tokens["in"], output_tokens=tokens["out"], cache_read_tokens=tokens["read"] or None,
             cache_write_tokens=tokens["write"] or None, cost_usd=round(cost, 5))
    out(f"{batch_id}: stored {stored} comments ({forecasts} forecasts); "
        f"{skipped} skipped by the model and {failed} failed, to be resent. "
        f"Cost ${cost:.2f} (estimated ${row['est_cost']:.2f}); this month ${db.month_spend(conn):.2f} of ${budget():.2f}.")
    return True


def collect_all(conn, client, wait=False, poll=60, out=print):
    """Collect every submitted batch; with wait, keep polling until all have ended."""
    while True:
        ids = [r[0] for r in conn.execute("SELECT id FROM batches WHERE status = 'submitted' ORDER BY created_at")]
        if not ids:
            out("No batches waiting.")
            return
        unfinished = [b for b in ids if not collect(conn, client, b, out)]
        if not unfinished or not wait:
            return
        time.sleep(poll)
