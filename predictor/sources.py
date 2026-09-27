"""Where comments come from.

- Arctic Shift API: free, no key, covers Reddit history (the Pushshift successor
  for researchers). https://github.com/ArthurHeitmann/arctic_shift
- Archive dump files: the monthly or per-subreddit .zst dumps from Academic
  Torrents, or any newline-delimited JSON file in the same format.

Both yield the same normalized dicts that db.insert_comments expects.
"""

import io
import json
import time
import urllib.error
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


def arctic_shift(subreddit, after, before, query=None, limit=None, retries=4, pause=1.0):
    """Page through Arctic Shift oldest-first between two unix times.

    `query` uses Arctic Shift's full-text search on the comment body.
    """
    params = {"subreddit": subreddit, "after": after, "before": before,
              "limit": 100, "sort": "asc"}
    if query:
        params["body"] = query
    yielded = 0
    while True:
        url = ARCTIC_SHIFT + "?" + urllib.parse.urlencode(params)
        batch = _get_json(url, retries)
        if not batch:
            return
        for raw in batch:
            c = normalize(raw)
            if c:
                yield c
                yielded += 1
                if limit and yielded >= limit:
                    return
        last = int(float(batch[-1]["created_utc"]))
        if len(batch) < params["limit"] or last >= before:
            return
        # Resume after the last timestamp seen; INSERT OR IGNORE absorbs any overlap.
        # Step forward a second if a full page shared one timestamp, so we can't loop.
        params["after"] = last if last > params["after"] else last + 1
        time.sleep(pause)


def _get_json(url, retries):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.load(resp)
            if payload.get("error"):
                raise RuntimeError(payload["error"])
            return payload.get("data") or []
        except (urllib.error.URLError, RuntimeError, TimeoutError) as e:
            if attempt == retries:
                raise RuntimeError(f"Arctic Shift request failed after {retries + 1} tries: {e}\n{url}") from e
            time.sleep(2 ** attempt * 5)


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
