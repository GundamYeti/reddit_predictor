"""Command line: python -m predictor <command> --help"""

import argparse
import calendar
import sys
import time

from . import batch, db, extract, llm, panel, pilot, review, score, sources


def date(s):
    """YYYY-MM-DD (UTC midnight) to unix time."""
    return calendar.timegm(time.strptime(s, "%Y-%m-%d"))


def show_date(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else "-"


def get_question(conn, qid):
    q = conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
    if not q:
        raise SystemExit(f"No question #{qid}. See: python -m predictor question list")
    return q


def cmd_question_add(conn, a):
    cur = conn.execute(
        "INSERT INTO questions (text, criteria, keywords, opens_at, closes_at) VALUES (?, ?, ?, ?, ?)",
        (a.text, a.criteria, a.keywords, date(a.opens) if a.opens else None, date(a.closes)),
    )
    conn.commit()
    print(f"Added question #{cur.lastrowid}.")


def cmd_question_list(conn, a):
    rows = conn.execute("""
        SELECT q.*, COUNT(p.comment_id) FILTER (WHERE p.relevant = 1) AS tagged,
               COUNT(p.comment_id) FILTER (WHERE p.relevant = 1 AND p.review = 'accepted') AS accepted
        FROM questions q LEFT JOIN predictions p ON p.question_id = q.id
        GROUP BY q.id ORDER BY q.id""").fetchall()
    if not rows:
        print("No questions yet. Add one with: python -m predictor question add --help")
    for q in rows:
        print(f"#{q['id']} [{q['status'].upper()}] {q['text']}\n"
              f"    window {show_date(q['opens_at'])} to {show_date(q['closes_at'])}"
              f" | keywords: {q['keywords'] or '(none)'} | {q['tagged']} tagged, {q['accepted']} accepted")
        if q["criteria"]:
            print(f"    resolves: {q['criteria']}")


def cmd_question_resolve(conn, a):
    get_question(conn, a.id)
    conn.execute("UPDATE questions SET status = ?, resolved_at = ?, notes = ? WHERE id = ?",
                 (a.outcome, int(time.time()), a.notes, a.id))
    conn.commit()
    print(f"Question #{a.id} resolved {a.outcome.upper()}.")


def cmd_collect_arctic(conn, a):
    total = 0
    for sub in a.subreddit:
        print(f"Fetching r/{sub} {a.after} to {a.before}" + (f" matching {a.query!r}" if a.query else "") + "...")
        added = db.insert_comments(
            conn, sources.arctic_shift(sub, date(a.after), date(a.before), a.query, a.limit, a.per_day),
            a.tag or "arctic_shift")
        print(f"  {added} new comments")
        total += added
    print(f"Added {total} comments.")


def cmd_collect_file(conn, a):
    keywords = [k.strip() for k in a.keywords.split(",")] if a.keywords else None
    comments = sources.dump_file(a.path, a.subreddit, date(a.after) if a.after else None,
                                 date(a.before) if a.before else None, keywords)
    print(f"Added {db.insert_comments(conn, comments, 'file:' + a.path)} comments.")


def cmd_extract(conn, a):
    extract.run(conn, llm.get_backend(a.llm, a.model), get_question(conn, a.id), a.limit)


def cmd_review(conn, a):
    review.run(conn, a.id)


def cmd_scores(conn, a):
    rows = (score.by_subreddit if a.by == "subreddit" else score.by_user)(conn, a.include_unreviewed)
    if not rows:
        print("No scores yet: you need at least one resolved question with accepted forecasts.")
        return
    key = "subreddit" if a.by == "subreddit" else "author"
    print(f"{key:<28} {'n':>4} {'brier':>7} {'adjusted':>9} {'vs crowd':>9} {'adj.':>7}")
    for r in rows[:a.top]:
        peer = f"{r['peer']:>+9.3f} {r['peer_adjusted']:>+7.3f}" if r["peer"] is not None else f"{'-':>9} {'-':>7}"
        flag = f"  ({r['both_sides']} both-sides)" if r["both_sides"] else ""
        print(f"{r[key]:<28} {r['n']:>4} {r['brier']:>7.3f} {r['adjusted']:>9.3f} {peer}{flag}")
    print("Lower is better. Brier: 0 perfect, 0.25 = coin flip. 'vs crowd': Brier minus the crowd's\n"
          "Brier on the same questions that week; below 0 = beat the crowd. 'adj.' columns shrink small samples.")


def cmd_export(conn, a):
    print(f"Wrote scores for {score.export(conn, a.path, a.include_unreviewed)} users to {a.path}.")


def cmd_pilot_extract(conn, a):
    pilot.extract(conn, llm.get_backend(a.llm, a.model), a.tag, a.limit)


def cmd_pilot_label(conn, a):
    pilot.label(conn, a.tag, a.random)


def cmd_pilot_report(conn, a):
    pilot.report(conn, a.tag, a.extractor, a.random)


def _client():
    llm.load_dotenv()
    import anthropic
    return anthropic.Anthropic()


def cmd_batch_submit(conn, a):
    batch.submit(conn, _client(), a.tag, a.model, a.pack, a.limit)


def cmd_batch_collect(conn, a):
    batch.collect_all(conn, _client(), wait=a.wait)


FEED_SUBREDDITS = "politics,neoliberal,Destiny,Hasan_Piker,Conservative,LateStageCapitalism,boxoffice,GamingLeaksAndRumours,nba"


def cmd_panel_pick(conn, a):
    if a.week:
        week = date(a.week)
    else:  # the Monday at least two weeks back, so the archive has caught up
        t = int(time.time()) - 14 * 86400
        week = t - t % 86400 - time.gmtime(t).tm_wday * 86400
    print(f"Picking the top {a.top} commenters per subreddit in the week of "
          f"{time.strftime('%Y-%m-%d', time.gmtime(week))}...")
    added = panel.pick(conn, [s.strip() for s in a.subreddits.split(",") if s.strip()], a.top, week)
    print(f"Added {added} members.")


def cmd_panel_fetch(conn, a):
    until = int(time.time()) - 2 * 86400  # the archive lags a little
    until -= until % 86400
    since = until - int(a.months * 30) * 86400
    print(f"Fetching {time.strftime('%Y-%m-%d', time.gmtime(since))} to {time.strftime('%Y-%m-%d', time.gmtime(until))},"
          f" at most {a.cap} filtered comments per member per month...")
    panel.fetch(conn, since, until, a.cap)


def cmd_panel_status(conn, a):
    panel.status(conn, a.extractor)


def cmd_spend(conn, a):
    print(f"This month: ${db.month_spend(conn):.2f} of the ${batch.budget():.2f} budget "
          f"(PREDICTOR_MONTHLY_BUDGET).")
    for r in conn.execute("SELECT * FROM spend ORDER BY at DESC LIMIT ?", (a.last,)):
        print(f"  {time.strftime('%Y-%m-%d %H:%M', time.localtime(r['at']))}  ${r['dollars']:>6.2f}  {r['what']}")
    for r in conn.execute("SELECT * FROM batches WHERE status = 'submitted'"):
        print(f"  waiting: batch {r['id']} ({r['n_comments']} comments, est. ${r['est_cost']:.2f}); "
              f"run `batch collect`")


def cmd_status(conn, a):
    n = conn.execute("""SELECT
        (SELECT COUNT(*) FROM comments) AS comments,
        (SELECT COUNT(DISTINCT author) FROM comments) AS users,
        (SELECT COUNT(*) FROM questions) AS questions,
        (SELECT COUNT(*) FROM questions WHERE status != 'open') AS resolved,
        (SELECT COUNT(*) FROM predictions) AS pairs,
        (SELECT COUNT(*) FROM predictions WHERE relevant = 1) AS forecasts,
        (SELECT COUNT(*) FROM predictions WHERE relevant = 1 AND review = 'unreviewed') AS pending
    """).fetchone()
    print(f"database:   {a.db}")
    print(f"comments:   {n['comments']} from {n['users']} users")
    print(f"questions:  {n['questions']} ({n['resolved']} resolved)")
    print(f"classified: {n['pairs']} comment/question pairs, {n['forecasts']} forecasts, "
          f"{n['pending']} awaiting review")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m predictor",
                                description="Score Reddit users on how well their predictions hold up.")
    p.add_argument("--db", default=db.DEFAULT_DB, help="SQLite file (default %(default)s)")
    sub = p.add_subparsers(dest="command", required=True)

    q = sub.add_parser("question", help="write, list and resolve questions").add_subparsers(dest="action", required=True)
    s = q.add_parser("add", help="add a yes/no question")
    s.add_argument("text", help='e.g. "Will Joe Biden be the Democratic nominee on Election Day 2024?"')
    s.add_argument("--closes", required=True, help="YYYY-MM-DD the answer became known; later comments don't count")
    s.add_argument("--opens", help="YYYY-MM-DD; ignore comments before this")
    s.add_argument("--criteria", default="", help="how you'll decide YES vs NO")
    s.add_argument("--keywords", default="", help="comma-separated words; a comment must contain one to be checked")
    s.set_defaults(fn=cmd_question_add)
    q.add_parser("list", help="show questions and progress").set_defaults(fn=cmd_question_list)
    s = q.add_parser("resolve", help="record the outcome")
    s.add_argument("id", type=int)
    s.add_argument("outcome", choices=["yes", "no", "void"], help="void = too ambiguous to score")
    s.add_argument("--notes", default="")
    s.set_defaults(fn=cmd_question_resolve)

    c = sub.add_parser("collect", help="download comments").add_subparsers(dest="source", required=True)
    s = c.add_parser("arctic", help="from the Arctic Shift archive API")
    s.add_argument("--subreddit", "-r", action="append", required=True, help="repeat for several")
    s.add_argument("--after", required=True, help="YYYY-MM-DD")
    s.add_argument("--before", required=True, help="YYYY-MM-DD")
    s.add_argument("--query", help="only comments containing these words (server-side search)")
    s.add_argument("--limit", type=int, help="stop after this many comments per subreddit")
    s.add_argument("--per-day", type=int, help="at most this many comments per day, to spread a sample out")
    s.add_argument("--tag", help="label these comments as a named sample, e.g. pilot1 (default: arctic_shift)")
    s.set_defaults(fn=cmd_collect_arctic)
    s = c.add_parser("file", help="from a .zst dump or .jsonl file")
    s.add_argument("path")
    s.add_argument("--subreddit", "-r", action="append")
    s.add_argument("--after", help="YYYY-MM-DD")
    s.add_argument("--before", help="YYYY-MM-DD")
    s.add_argument("--keywords", help="comma-separated; keep only comments containing one")
    s.set_defaults(fn=cmd_collect_file)

    s = sub.add_parser("extract", help="have a model tag comments for a question")
    s.add_argument("id", type=int, help="question id")
    s.add_argument("--limit", type=int, help="classify at most this many comments")
    s.add_argument("--llm", choices=["ollama", "claude"], help="default: $PREDICTOR_LLM or ollama")
    s.add_argument("--model", help="override the backend's default model")
    s.set_defaults(fn=cmd_extract)

    s = sub.add_parser("review", help="accept, fix or reject what the model tagged")
    s.add_argument("id", type=int, nargs="?", help="only this question")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("scores", help="leaderboard")
    s.add_argument("--by", choices=["user", "subreddit"], default="user")
    s.add_argument("--top", type=int, default=25)
    s.add_argument("--include-unreviewed", action="store_true", help="count tags you haven't reviewed")
    s.set_defaults(fn=cmd_scores)

    s = sub.add_parser("export", help="write user scores as JSON for the overlay")
    s.add_argument("path", nargs="?", default="data/user_scores.json")
    s.add_argument("--include-unreviewed", action="store_true")
    s.set_defaults(fn=cmd_export)

    pl = sub.add_parser("pilot", help="discover forecasts without a preset question (see docs/research-review.md)")
    pl = pl.add_subparsers(dest="action", required=True)
    s = pl.add_parser("extract", help="have a model list the forecasts in each sampled comment")
    s.add_argument("--tag", default="pilot1", help="which collected sample (default %(default)s)")
    s.add_argument("--limit", type=int, help="scan at most this many comments (try 50 first)")
    s.add_argument("--llm", choices=["ollama", "claude"], help="default: $PREDICTOR_LLM or ollama")
    s.add_argument("--model", help="override the backend's default model")
    s.set_defaults(fn=cmd_pilot_extract)
    s = pl.add_parser("label", help="label comments by hand, without seeing the model's answers")
    s.add_argument("--tag", default="pilot1")
    s.add_argument("--random", type=int, default=100, help="size of the random slice to label (default %(default)s)")
    s.set_defaults(fn=cmd_pilot_label)
    s = pl.add_parser("report", help="base rate, model vs. you, hedge phrases, what people predict")
    s.add_argument("--tag", default="pilot1")
    s.add_argument("--extractor", help="which model's results, e.g. claude:claude-opus-5-5 (default: latest)")
    s.add_argument("--random", type=int, default=100)
    s.set_defaults(fn=cmd_pilot_report)

    bp = sub.add_parser("batch", help="scan comments through the half-price Batch API (results within 24 h)")
    bsub = bp.add_subparsers(dest="batch_command", required=True)
    s = bsub.add_parser("submit", help="send unscanned comments from a sample, within the monthly budget")
    s.add_argument("--tag", required=True, help="which collected sample, e.g. pilot1")
    s.add_argument("--model", default=batch.DEFAULT_MODEL)
    s.add_argument("--pack", type=int, default=batch.DEFAULT_PACK, help="comments per request (default %(default)s)")
    s.add_argument("--limit", type=int, help="send at most this many comments")
    s.set_defaults(fn=cmd_batch_submit)
    s = bsub.add_parser("collect", help="store the results of finished batches")
    s.add_argument("--wait", action="store_true", help="keep checking every minute until all have finished")
    s.set_defaults(fn=cmd_batch_collect)

    pp = sub.add_parser("panel", help="the heavy commenters whose comments are followed (see PLAN.md)")
    psub = pp.add_subparsers(dest="panel_command", required=True)
    s = psub.add_parser("pick", help="add the top commenters of each subreddit")
    s.add_argument("--subreddits", default=FEED_SUBREDDITS, help="comma-separated (default: %(default)s)")
    s.add_argument("--top", type=int, default=20, help="members per subreddit (default %(default)s)")
    s.add_argument("--week", help="YYYY-MM-DD week to rank commenters in (default: the Monday two weeks back)")
    s.set_defaults(fn=cmd_panel_pick)
    s = psub.add_parser("fetch", help="fetch members' recent comments that pass the phrase filter")
    s.add_argument("--months", type=float, default=1, help="how far back (default %(default)s)")
    s.add_argument("--cap", type=int, default=40, help="filtered comments kept per member per month (default %(default)s)")
    s.set_defaults(fn=cmd_panel_fetch)
    s = psub.add_parser("status", help="members, comments, scans and forecasts per subreddit")
    s.add_argument("--extractor", help="count only this extractor's scans")
    s.set_defaults(fn=cmd_panel_status)

    s = sub.add_parser("spend", help="this month's model spending against the budget")
    s.add_argument("--last", type=int, default=10, help="show this many recent entries")
    s.set_defaults(fn=cmd_spend)

    sub.add_parser("status", help="counts of everything").set_defaults(fn=cmd_status)

    a = p.parse_args(argv)
    sys.stdout.reconfigure(line_buffering=True)  # show progress promptly when logged to a file
    conn = db.connect(a.db)
    try:
        a.fn(conn, a)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
