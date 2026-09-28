# Plan

## Goal

1. **Score people, not posts.** Give each Reddit user a Brier score built from predictions they made, especially vague political ones.
2. **Overlay.** A browser extension that shows each commenter's score next to their name and can sort a thread by track record instead of karma.

## Key design decision: questions first

The original pipeline tried to pull predictions out of comments and then work out whether each one came true. For political talk that can't be automated: predictions are vague, sarcastic, and all phrased differently.

So the unit of work is now a **question you write**, such as *"Will Biden withdraw before the convention?"*, with a close date and a rule for how it resolves.
- The model's only job is narrow and checkable: *does this comment take a side on this question, which side, and how sure does it sound?*
- You review those tags and resolve the question **once**. That scores every linked comment.
- One question typically links to hundreds of comments, so your effort stays manageable.

This also matches how forecasting sites like Metaculus and Good Judgment score people, so the numbers mean the same thing.

## Status (2026-09-27)

Done:
- [x] Old scripts moved to `legacy/`; the crash in `manual_spot_check.py` fixed
- [x] SQLite store: questions, comments, predictions
- [x] Comment collection: Arctic Shift API, `.zst` archive dumps, `.jsonl` files
- [x] Tagging with a local model (Ollama) or Claude, using structured JSON output
- [x] Terminal review queue: accept, reject, flip, re-rate confidence
- [x] Brier scoring per user and per subreddit, with no-hindsight cutoff, one vote per user per question, and small-sample adjustment
- [x] JSON export of user scores for the overlay
- [x] Offline tests (10) on synthetic data

Tested so far:
- Local phi3:mini on 5 synthetic comments: 4 of 5 correct (it caught the sarcasm but missed "definitely staying in the race, mark my words"), **70-90 s per comment** on the laptop.
- Claude backend: request format checked against a local stand-in server. **Not yet run against the real API** (no key on this machine).
- Arctic Shift API: was down (HTTP 500) overnight, back 2026-09-27. Its keyword search times out on ranges longer than about an hour, so the collector walks one day at a time, splits any window that times out, and `--per-day` spreads samples evenly across each day.

## Change of direction (2026-09-28)

The first real run (20 comments, question-first) found only 1 real forecast, and phi3:mini
confused "he should drop out" with "he will". After a literature review
([docs/research-review.md](docs/research-review.md)) the plan is now **discovery first**:
find forecasts in unfiltered comments, group them into recurring claims, and turn the
popular ones into questions. `python -m predictor pilot ...` is step 1 of that. The
question-first steps below still apply once questions come out of the pilot.

## Next steps (question-first; see the change of direction above)

### 1. Get real data
- Arctic Shift works again (see the README walkthrough).
- If it goes down again: download the r/politics comments file from the per-subreddit Reddit dumps on Academic Torrents (search "reddit subreddits" there; check the date range covers what you need) and use `collect file`. There are 206 GB free, which is enough.

### 2. First real question, end to end
Good first question, since it's high-volume, had a clear resolution, and ran for weeks of loud argument: **"Will Biden withdraw from the 2024 race before the DNC?"** (debate 2024-06-27, withdrawal 2024-07-21). Collect about 500 comments with keywords, tag them, review them, resolve YES, look at the leaderboard.

### 3. Pick the tagging model for volume
Local tagging at about 1 comment per minute is fine for testing but too slow for thousands of comments. Options:
- Claude at low effort: rough estimate a few dollars per thousand comments (measure on the first 50 before committing).
- Claude Batch API: half price, results within 24 hours. Worth adding once the prompt is settled.
- A bigger local model on a future GPU desktop.

### 4. Build a question bank
Scores only become meaningful once each user has several resolved questions. Aim for 20-50 questions across 2020-2025 (elections, nominations, legislation, court rulings, resignations). Also add a `question add` shortcut for bulk loading from a CSV.

### 5. Overlay (browser extension)
- Content script for `www.reddit.com` (comments are `<shreddit-comment author="...">` elements) and `old.reddit.com`.
- Reads the exported `user_scores.json` (bundled, or from a small local server).
- Shows a badge next to each username: adjusted score plus how many questions it's based on, e.g. `0.14 · 9q`.
- Sorting: reorder sibling comments by adjusted score; users with no score go after scored ones, or keep their original order.
- Honest expectation: most commenters in any thread will have no score for a long time. Coverage grows with the question bank, so the overlay is most useful in threads about topics you've built questions for.

### 6. Later ideas
- Scores per topic (elections vs. economy vs. foreign policy) rather than one number.
- Calibration chart per subreddit (when they say 80%, are they right 80% of the time?).
- Use `RemindMe!` comments to find forecasts automatically.

## Things to keep in mind
- **Reddit's terms:** keep collected data local and for personal research. Publishing per-user scores of real people is a bigger step and deserves a closer look before doing it.
- **Model mistakes:** unreviewed tags never count unless you pass `--include-unreviewed`.
- **Deleted accounts and bots** are skipped when collecting.
