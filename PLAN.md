# Plan

## Goal

A personal feed ranked by **who is talking**, not by karma, subscriptions or an engagement algorithm.

On a small forum you learn whose comments to trust. Reddit is too big for that, so every comment reads as "what Reddit says". This project automates the reputation:

1. **Score people, not posts.** Give each commenter a track record built from the predictions they made, scored against what actually happened.
2. **Rank the front page by those people.** A post rises when people with good records are commenting on it (comments matter more than who posted it).
3. **Grounding as a second signal.** Most people will never have a track record, so a separately labeled reasoning-quality signal (sources, stated uncertainty, engaging the other side) fills the gap.
4. **Bots filter themselves.** Being right *before* the outcome is known is expensive to fake. Division-stirring accounts without a record sink; an accurate bot just gives away free information.

Order: the general front page first, then per-topic records (someone can be good on videogames and bad on politics), then other sources (Bluesky first because its data is open; X/Twitter later because its API is paid and restrictive).

## Key design decisions

**Questions with written resolution rules.** Predictions are vague, sarcastic and phrased every which way, so the model never decides whether something came true. Its job stays narrow: *is this a forecast, which way, how sure, by when, under what condition.* Resolution comes from questions with a written rule: ones you write, or (proposed, your call) already-resolved questions from prediction markets and forecasting sites (Polymarket, Kalshi, Metaculus), which come with rules of their own.

**Discovery first** (since 2026-09-28). Find forecasts in unfiltered comments, group them into recurring claims, and turn the popular ones into questions. See [docs/research-review.md](docs/research-review.md).

**Score skill, not volume.** Raw Brier rewards easy calls ("Texas goes red"). Score people relative to the crowd on the same question, penalize taking both sides of one question, and require a minimum number of resolved forecasts before anyone counts.

**Funnel, don't scan everything.** Scanning every comment is unaffordable (see Findings). Only heavy commenters, only comments that pass a phrase filter, a cheap model before the expensive one, and then rescans of known people only.

## Findings so far

### Pilot (2026-10-14): 504 unfiltered r/politics comments, Jun 27 – Jul 21, 2024
- Claude Opus 5.5 found **115 forecasts in 76 comments (15%)**, 0 failures, **$3.48** total (~$7 per 1,000 comments), 1-5 s per comment.
- It no longer confuses "he should drop out" with "he will". Weak spot: vague, unresolvable claims ("his base will ignore that") and forecasts that lost their context ("the event under discussion happens").
- About 30 of 115 forecasts are conditional ("if Biden stays in, Trump wins"), so scoring conditionals is a real decision.
- Claims recur: ~15 versions of "Trump wins / Democrats lose", ~7 on whether Biden withdraws (most said no), ~6 on "Harris is the nominee if Biden steps aside".
- **Nearly every author appeared exactly once.** Random samples find forecasts, not track records; collection has to follow authors.

### Phrase prefilter (free, measured on the pilot)
| Filter | Comments kept | Forecast comments caught |
|---|---|---|
| Strict ("will", "gonna", "bet", "no way", "probably"…) | 20% | 75% |
| Broad (adds "might", "would", "if", "I don't see", "ain't happening"…) | 37% | 97% |

Normalize curly apostrophes first (phone keyboards type "won’t"). The two misses were in Spanish and "a possible win without Biden is much better than a certain loss with him".

### Commenter volume, one week (Jul 8-14, 2024) via Arctic Shift author counts
| Subreddit | Comments | Authors | ≥20/wk | ≥50/wk | Top 5% write |
|---|---|---|---|---|---|
| r/politics | 422,110 | 79,919 | 3,819 | 1,005 | 44% |
| r/neoliberal | 116,420 | 6,010 | 1,082 | 541 | 54% |
| r/Destiny | 56,745 | 9,592 | 582 | 134 | 41% |
| r/Conservative | 30,268 | 9,141 | 216 | 31 | 38% |
| r/socialism | 2,613 | 1,266 | 4 | 1 | 28% |
| r/LateStageCapitalism | 9,108 | 4,163 | 26 | 3 | 31% |
| r/Hasan_Piker | 4,869 | 1,592 | 31 | 7 | 38% |

(Deleted accounts, AutoModerator and bots excluded. The r/politics counts may slightly undercount light commenters.)

The 15 heaviest commenters in each, with the broad filter applied:
| Subreddit | Median comments/wk | Pass filter | Median length | Est. forecasts/month* |
|---|---|---|---|---|
| r/neoliberal | 724 | 27% | 68 chars | ~300 |
| r/politics | 473 | 29% | 79 chars | ~260 |
| r/Destiny | 169 | 39% | 110 chars | ~120 |
| r/Conservative | 93 | 32% | 89 chars | ~55 |
| r/socialism | 17 | 41% | 162 chars | ~10 |

\* Filtered comments × 39%, the forecast rate among filtered r/politics pilot comments. Not yet checked in the other subreddits; r/neoliberal's very short comments (daily discussion thread chat) probably make it an overestimate.

### Calibration (2026-10-14, $5.08): Claude on 100 filtered comments from each subreddit's 15 heaviest commenters
| Subreddit | Filtered comments with a forecast | Forecasts per 100 filtered | Filtered comments/wk per heavy commenter | **Measured forecasts/month per heavy commenter** | Earlier guess |
|---|---|---|---|---|---|
| r/neoliberal | 20% | 25 | 207 | **~220** | ~300 |
| r/politics | 20% | 28 | 160 | **~190** | ~260 |
| r/Destiny | 29% | 39 | 74 | **~125** | ~120 |
| r/Hasan_Piker | 34% | 54 | 22 | **~50** | – |
| r/Conservative | 16% | 22 | 33 | **~30** | ~55 |
| r/LateStageCapitalism | 20% | 22 | 16 | **~15** | – |
| r/socialism | 16% | 21 | 10 | **~9** | ~10 |

Samples are 100 comments each, so treat rates as ±10 points. The guess was too high for r/politics, r/neoliberal and r/Conservative. r/Hasan_Piker's heavy commenters forecast the most densely (half a forecast per filtered comment) but there are few of them; r/LateStageCapitalism has the same problem as r/socialism in milder form. Cost per forecast found ranges from about $0.013 (r/Hasan_Piker) to $0.03 (r/Conservative).

What this means:
- **Volume isn't the problem for most subreddits.** Heavy commenters plausibly make dozens to hundreds of forecasts a month, enough for a record within weeks. r/socialism is the exception: too small to build records, so r/LateStageCapitalism replaces it.
- **Cost is the problem.** Scanning everyone with ≥20 comments/week across these five, after the filter, with Opus at list price: **~$3,000/month** (r/politics ~$1,800, r/neoliberal ~$950). Needs to come down 10-50x: Haiku as a middle pass (4x cheaper per token), the Batch API (half price), a cap on comments scanned per person, and dropping people after their first month if they rarely forecast.
- This was a busy news week (debate fallout, the July 13 assassination attempt), so typical weeks are probably lighter.

## Roadmap

### A. Validate the core
1. **Label the pilot (you).** `python -m predictor pilot label` (~110 comments), then `pilot report`. Measures model-vs-you agreement; decides whether the model can be trusted at scale.
2. **Group forecasts into claims (build).** Merge near-duplicates into "Biden withdraws before the DNC: 7 comments, 2 yes / 5 no"; drop context-less and unresolvable ones.
3. **Fix the scoring (build).** Crowd-relative score next to raw Brier, a measured confidence table instead of the hand-made one, a both-sides penalty, a decision on conditionals.

### B. Make the funnel affordable
4. ~~**Calibrate per subreddit.**~~ Done for the seven political subreddits (see Findings); repeat for each new one (~$0.75 each).
5. **Measure a cheap middle pass.** Haiku (or the local model) on the pilot: what share of Claude's forecasts does it keep, at what cost? Free to compare on data already scanned, apart from Haiku's own small cost.
6. **Build the funnel.** Heavy commenters → phrase filter → cheap model → Claude via Batch, with a per-person monthly cap. Then rescan only people who forecast often.

### C. Ground truth at scale
7. **Import resolved prediction-market questions** and match forecasts to them; your own questions cover the rest.
8. **Event-triggered search.** When something surprising resolves, search for related comments made before it and *nominate* the people who called it. Their full history then decides; one lucky long shot proves nothing.

### D. The feed
9. **Coverage test.** One snapshot of a current front page: how many commenters have a usable record? Tells us whether the feed works before we build it.
10. **Local web page first** (simpler than a browser extension): fetch the front page via Reddit's API (free personal-use credentials), score posts by their commenters' records, re-rank, and show *why* each post ranked where it did.

### E. Expand
11. **Per-topic scores.** Videogames may be easier than politics: release dates, sales and review scores resolve on their own.
12. **Bluesky**, then other platforms. Each account is scored on its own; cross-platform identity matching is out of scope.

## Subreddits

**Now (political, across the spectrum):** r/politics, r/neoliberal, r/Destiny, r/Hasan_Piker, r/Conservative, r/LateStageCapitalism (replacing r/socialism, which is too small for track records: 4 people with 20+ comments in a week).

**Later.** All confirmed to exist in the archive (subscriber counts as of the check, 2026-10). ★ = forecasts there tend to resolve on their own, so they're the cheapest to score.

| Area | Subreddits |
|---|---|
| Politics, more leanings | r/moderatepolitics (301k), r/PoliticalDiscussion (2.2M), r/Libertarian (503k), r/centrist (57k), r/AskConservatives (28k), r/AskALiberal (55k) |
| World affairs, war | r/geopolitics (687k), r/worldnews (44M), ★ r/CredibleDefense (103k) |
| Economy, markets | r/Economics (5.2M), ★ r/wallstreetbets (17.7M), ★ r/stocks (8.4M), r/investing (2.9M), ★ r/CryptoCurrency (9.6M), r/REBubble (145k) |
| Tech, AI | r/technology (18M), r/singularity (3.6M), r/MachineLearning (3M), r/hardware (4.3M) |
| Videogames | ★ r/GamingLeaksAndRumours (488k), r/Games (3.4M), r/pcgaming (3.8M), r/NintendoSwitch (7.7M), r/PS5 (8M) |
| Film, TV | ★ r/boxoffice (1.1M), ★ r/oscarrace (82k), r/movies (34M), r/television (17.5M) |
| Sports | ★ r/sportsbook (490k), ★ r/nba (15M), ★ r/nfl (11.9M), ★ r/soccer (8.4M), ★ r/formula1 (4.9M) |
| Science, space | ★ r/SpaceX (3.6M), r/space (27.6M) |
| Pessimism as a topic | r/collapse (524k): a natural place to test whether doom predictions come true |

Sports and box office are worth doing early for a different reason: outcomes are unambiguous and fast, so they're a good testbed for the scoring itself, separate from political judgment.

## Done
- Old scripts moved to `legacy/`; SQLite store for questions, comments, predictions, pilot scans, forecasts and labels.
- Collection from the Arctic Shift API, `.zst` archive dumps and `.jsonl` files. Arctic Shift's keyword search times out on long ranges, so the collector walks one day at a time and splits windows that time out.
- Tagging with a local model (Ollama) or Claude (default `claude-opus-5-5`) using structured JSON output.
- Terminal review queue; Brier scoring per user and subreddit (no-hindsight cutoff, one vote per user per question, small-sample adjustment); JSON export.
- Discovery pilot: `pilot extract | label | report`.
- Offline tests (20).

## Things to keep in mind
- **Reddit's terms:** keep collected data local and for personal use. Publishing per-user scores of real people is a much bigger step and deserves a closer look first.
- **Model mistakes:** unreviewed tags never count unless you pass `--include-unreviewed`.
- **Volume is not a virtue.** A high comment count is also a bot trait; only accuracy may raise a score.
- **Deleted accounts and bots** are skipped when collecting.
- **Shared laptop:** the local model shares one Ollama server with `~/ai-assistant`; keep `num_ctx` at 2048 and run one heavy model job at a time.
