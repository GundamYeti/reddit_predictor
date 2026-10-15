"""Terminal review queue: check what the model tagged before it counts toward a score."""

import textwrap
import time

HELP = """  a = accept      r = reject (not a forecast)     f = flip YES/NO
  0.5-0.99 = accept with this confidence instead
  for conditional forecasts ("if A, then B"), also:
    m = accept, and A happened (it counts)    x = accept, but A didn't happen (set aside)
  s = skip for now      q = quit"""


def queue(conn, question_id=None):
    sql = """SELECT p.*, c.author, c.body, c.created_utc, c.permalink, c.subreddit,
                    q.text AS question
             FROM predictions p JOIN comments c ON c.id = p.comment_id
             JOIN questions q ON q.id = p.question_id
             WHERE p.relevant = 1 AND p.review = 'unreviewed'"""
    args = []
    if question_id:
        sql += " AND p.question_id = ?"
        args.append(question_id)
    return conn.execute(sql + " ORDER BY p.question_id, c.created_utc", args).fetchall()


def set_review(conn, row, review, stance=None, confidence=None, condition_met=None):
    conn.execute(
        """UPDATE predictions SET review = ?, stance = COALESCE(?, stance),
                  confidence = COALESCE(?, confidence), condition_met = COALESCE(?, condition_met),
                  reviewed_at = ?
           WHERE comment_id = ? AND question_id = ?""",
        (review, stance, confidence, condition_met, int(time.time()), row["comment_id"], row["question_id"]),
    )
    conn.commit()


def run(conn, question_id=None, read=input, write=print):
    rows = queue(conn, question_id)
    if not rows:
        write("Nothing to review.")
        return 0
    write(f"{len(rows)} tagged comments to review.\n{HELP}")
    done = 0
    for i, row in enumerate(rows, 1):
        when = time.strftime("%Y-%m-%d", time.gmtime(row["created_utc"]))
        body = textwrap.indent(textwrap.fill(row["body"][:1500], 90), "    ")
        write(f"\n{'-' * 90}\n[{i}/{len(rows)}] Q#{row['question_id']}: {row['question']}\n"
              f"u/{row['author']} in r/{row['subreddit']} on {when}  {row['permalink']}\n{body}\n"
              f"  Model says: {row['stance'].upper()} at {row['confidence']:.2f}"
              + (f" from \"{row['hedge_phrase']}\"" if row["hedge_phrase"] else " (stated flatly)")
              + f"  ({row['rationale']})"
              + (f"\n  CONDITIONAL, only if: {row['condition']}" if row["condition"] else ""))
        while True:
            answer = read("> ").strip().lower()
            if answer == "a":
                set_review(conn, row, "accepted")
            elif answer == "r":
                set_review(conn, row, "rejected")
            elif answer in ("m", "x") and row["condition"]:
                set_review(conn, row, "accepted", condition_met=1 if answer == "m" else 0)
            elif answer == "f":
                set_review(conn, row, "accepted", stance="no" if row["stance"] == "yes" else "yes")
            elif answer == "s":
                break
            elif answer == "q":
                write(f"Reviewed {done}.")
                return done
            else:
                try:
                    conf = float(answer)
                except ValueError:
                    write(HELP)
                    continue
                if not 0.5 <= conf <= 0.99:
                    write("Confidence must be between 0.5 and 0.99.")
                    continue
                set_review(conn, row, "accepted", confidence=conf)
            done += 1
            break
    write(f"\nReviewed {done}.")
    return done
