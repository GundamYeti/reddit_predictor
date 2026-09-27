"""Where comments come from.

- Arctic Shift API: free, no key, covers Reddit history (the Pushshift successor
  for researchers). https://github.com/ArthurHeitmann/arctic_shift
- Archive dump files: the monthly or per-subreddit .zst dumps from Academic
  Torrents, or any newline-delimited JSON file in the same format.

Both yield the same normalized dicts that db.insert_comments expects.
"""

import io
import json
import sys
import time
import urllib.parse
import urllib.request

ARCTIC_SHIFT = "https://arctic-shift.photon-reddit.com/api/comments/search"
USER_AGENT = "reddit_predictor/0.2 (research; github.com/GundamYeti/reddit_predictor)"
SKIP_AUTHORS = {"[deleted]", "[removed]", "AutoModerator", ""}


def normalize(raw):
    """Map a Reddit/Pushshift comment object to our columns, or None to skip it."""
    author = raw.get("author") or ""
    body = raw.get("body") or ""
    if author in SKIP_AUTHORS or body in ("[deleted]", "[removed]") or author.lower().endswith("bot"):
        return None
    permalink = raw.get("permalink") or ""
    if permalink.startswith("/"):
        permalink = "https://www.reddit.com" + permalink
    return {
        "id": str(raw["id"]),
        "author": author,
        "subreddit": raw.get("subreddit") or "",
        "body": body,
        "created_utc": int(float(raw["created_utc"])),
        "score": raw.get("score"),
        "link_id": raw.get("link_id"),
        "parent_id": raw.get("parent_id"),
        "permalink": permalink,
    }


def matches(body, keywords):
    if not keywords:
        return True
    low = body.lower()
    return any(k in low for k in keywords)


class SearchTimeout(RuntimeError):
    """Arctic Shift gave up on a query; a smaller time window usually works."""


DAY = 86400
MIN_WINDOW = 900  # don't split windows below 15 minutes


def arctic_shift(subreddit, after, before, query=None, limit=None, per_day=None, pause=2.0,
                 warn=lambda msg: print(msg, file=sys.stderr)):
    """Comments from Arctic Shift between two unix times, oldest first.

    `query` uses Arctic Shift's full-text search on the comment body. Keyword
    searches time out on long ranges, so the range is walked one day at a time
    and any window that times out is split in half and retried.
    `per_day` caps comments per day so a sample covers the whole range.
    """
    seen = set()
    for day in range(after, before, DAY):
        day_end = min(day + DAY, before)
        if per_day:
            # One comment from each of per_day evenly spaced slots, so the sample
            # covers the whole day rather than the minutes after midnight.
            slot = max(MIN_WINDOW, DAY // per_day)
            windows = [(t, min(t + slot, day_end)) for t in range(day, day_end, slot)][:per_day]
            per_window, page_size = 1, 10
        else:
            windows, per_window, page_size = [(day, day_end)], None, 100
        for w_after, w_before in windows:
            taken = 0
            for c in _window(subreddit, w_after, w_before, query, pause, warn, page_size):
                if c["id"] in seen:
                    continue
                seen.add(c["id"])
                yield c
                taken += 1
                if limit and len(seen) >= limit:
                    return
                if per_window and taken >= per_window:
                    break


def _window(subreddit, after, before, query, pause, warn, page_size=100):
    try:
        yield from _pages(subreddit, after, before, query, pause, page_size)
    except SearchTimeout:
        if before - after <= MIN_WINDOW:
            warn(f"  skipped {_ts(after)}-{_ts(before)}: archive search kept timing out")
            return
        mid = (after + before) // 2
        yield from _window(subreddit, after, mid, query, pause, warn, page_size)
        yield from _window(subreddit, mid, before, query, pause, warn, page_size)
    except RuntimeError as e:  # still failing after retries: skip this window, keep going
        warn(f"  skipped {_ts(after)}-{_ts(before)}: {str(e).splitlines()[0]}")


def _pages(subreddit, after, before, query, pause, page_size=100):
    params = {"subreddit": subreddit, "after": after, "before": before,
              "limit": page_size, "sort": "asc"}
    if query:
        params["body"] = query
    while True:
        time.sleep(pause)
        batch = _get_json(ARCTIC_SHIFT + "?" + urllib.parse.urlencode(params))
        if not batch:
            return
        for raw in batch:
            c = normalize(raw)
            if c:
                yield c
        last = int(float(batch[-1]["created_utc"]))
        if len(batch) < params["limit"] or last >= before:
            return
        # Resume after the last timestamp seen; duplicates are dropped by the caller.
        # Step forward a second if a full page shared one timestamp, so we can't loop.
        params["after"] = last if last > params["after"] else last + 1


def _get_json(url, retries=4):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.load(resp)
            error = payload.get("error")
            if error and "timeout" in error.lower():
                raise SearchTimeout(error)
            if error:
                raise RuntimeError(error)
            return payload.get("data") or []
        except SearchTimeout:
            if attempt >= 1:
                raise
            time.sleep(5)
        except (OSError, RuntimeError, ValueError) as e:  # network errors, HTTP 5xx, bad JSON
            if attempt == retries:
                raise RuntimeError(f"Arctic Shift request failed after {retries + 1} tries: {e}\n{url}") from e
            time.sleep(2 ** attempt * 5)


def _ts(t):
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(t))


def dump_file(path, subreddits=None, after=None, before=None, keywords=None):
    """Stream comments from a .zst dump or a plain .jsonl/.ndjson file."""
    subs = {s.lower() for s in subreddits} if subreddits else None
    keywords = [k.lower() for k in keywords] if keywords else None
    for line in _lines(path):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if subs and (raw.get("subreddit") or "").lower() not in subs:
            continue
        created = int(float(raw.get("created_utc", 0)))
        if (after and created < after) or (before and created >= before):
            continue
        c = normalize(raw)
        if c and matches(c["body"], keywords):
            yield c


def _lines(path):
    if path.endswith(".zst"):
        try:
            import zstandard
        except ImportError:
            raise SystemExit("Reading .zst dumps needs the zstandard package: pip install zstandard")
        with open(path, "rb") as fh:
            # The Reddit dumps are compressed with a 2 GB window.
            reader = zstandard.ZstdDecompressor(max_window_size=2**31).stream_reader(fh)
            yield from io.TextIOWrapper(reader, encoding="utf-8", errors="replace")
    else:
        with open(path, encoding="utf-8") as fh:
            yield from fh
