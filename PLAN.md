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

**Budget: about $10/month of Claude API, hard ceiling** (set 2026-10-15). Everything below is designed to fit that. At $10/month the project can scan roughly 10,000-25,000 comments a month, so it follows a fixed **panel** of a few hundred heavy commenters rather than everyone (see "What $10/month buys").

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
- **Cost is the problem.** Scanning everyone with ≥20 comments/week across these subreddits, after the filter, the way the pilot ran (Opus, one comment per request): **~$2,800/month**, about 280x the budget.
- This was a busy news week (debate fallout, the July 13 assassination attempt), so typical weeks are probably lighter.

### What $10/month buys
Each scan so far sent ~1,370 tokens in and got ~90 back, and most of the input is the same fixed instructions repeated for every comment. Estimated cost per filtered comment (only the first row is measured):

| Setup | $/comment | Comments for $10 |
|---|---|---|
| Opus 5.5, one comment per request (the pilot, measured) | $0.0069 | ~1,450 |
| Opus + cache the fixed instructions + Batch API | ~$0.0014 | ~7,300 |
| Sonnet 5.5 + cache + Batch | ~$0.00075 | ~13,000 |
| Sonnet 5.5 + Batch + ~20 comments per request | ~$0.0004 (rough guess) | ~25,000 |
| Haiku 4.5 + Batch (its prompt is too short to cache) | ~$0.0009 | ~11,000 |

Caching (cached input costs ~10%) and Batch (half price) don't change results. Switching model or packing comments together might, so both need checking against Opus on the pilot first.

**A panel instead of everyone.** Commenting is concentrated, so a small panel covers a lot:

| Panel | People | Share of all comments in each subreddit | Filtered comments/month at 50 per person |
|---|---|---|---|
| Top 25 per subreddit | 150 | politics 3%, Conservative 7%, Destiny 7%, LSC 12%, neoliberal 13%, Hasan_Piker 23% | ~7,200 |
| Top 50 per subreddit | 300 | politics 4%, Conservative 11%, Destiny 12%, LSC 17%, neoliberal 21%, Hasan_Piker 32% | ~13,000 |
| Top 100 per subreddit | 600 | politics 6%, Conservative 17%, Destiny 18%, LSC 23%, neoliberal 31%, Hasan_Piker 42% | ~25,000 |

At the measured forecast rates, 50 filtered comments a month yields ~12-27 forecasts per person, of which about half can be scored (see the classification below): enough for a record within a few months. r/politics is too big for a panel to cover much; the smaller, tighter communities are where this works best.

**Other ways to stay under budget:**
- **Questions first, once there's a question bank.** Instead of scanning everything a panel member writes, search their comments for keywords tied to questions we can resolve. Much cheaper per *scorable* forecast, since about half of all forecasts can never be scored anyway.
- **One-time vs. monthly.** Backfilling a panel's history is a one-off cost; after that only new comments are scanned.
- **The free local model: tested, not worth it on this laptop** (2026-10-15, [research/local_screen.py](research/local_screen.py)). As a yes/no screen ("could this contain a prediction?") on the 188 pilot comments that pass the broad filter, phi3:mini flagged 47% and caught only 42 of the 74 comments where Claude found a forecast (57%). The free strict phrase filter does better on the same comments: keeps 57%, catches 60 of 74 (81%), instantly. phi3:mini took a median 9 s per comment (up to 77 s), and its memory crept up until the kernel killed Ollama after ~25 comments; unloading it every 15 comments fixed that. Revisit with a bigger model on a future GPU desktop.
- **So the free first pass is the strict phrase filter**, and Claude does all the reading. Maintenance becomes: a quarterly refresh, strict filter, then Claude via Batch. For a 300-person panel that's roughly 25,000 comments a quarter, about $6/month at the Sonnet + cache + Batch estimate (to be confirmed by step 5).

### What kinds of predictions people make (2026-10-14, $0.99)
An open-ended classification of all 477 forecasts found so far (pilot, calibration samples, doomer sample): Claude proposed its own categories from the data, then labeled each forecast. Script and results: [research/classify_forecasts.py](research/classify_forecasts.py), [forecast_taxonomy.json](research/forecast_taxonomy.json), [forecast_labels.json](research/forecast_labels.json) (labels are keyed by forecast id in the local database).

| Dimension | Breakdown |
|---|---|
| Can it be scored? | 40% crisp, 15% fuzzy threshold ("landslide"), 25% interpretive, 8% sweeping, 12% unresolvable |
| Topic | 25% election outcome, 19% campaign dynamics, 13% nominations, 11% what the winner does in office, 9% economy/culture/niche, 6% violence or regime collapse, 5% foreign affairs, 5% courts, 4% other races |
| Conditional? | 56% unconditional, 29% on a real trigger ("if Trump wins"), 9% on a vague trigger, 6% on a hypothetical that never gets tested ("Michelle Obama would beat Trump") |
| Confidence | 43% stated flatly, 27% "probably", 19% emphatic, 10% "might", 1% sarcastic |
| Kind of claim | 31% who wins, 25% a specific action, 20% a broad trend, 12% how a group votes or reacts, 6% rhetoric, 6% a number |
| Time horizon | 53% the 2024 cycle (because that's when we sampled), 19% next term, 19% none stated, 5% decades, 4% days to weeks |

Differences between subreddits (22-54 forecasts each, so leads rather than findings):
- **r/LateStageCapitalism and r/socialism** make mostly sweeping, long-range systemic predictions (r/LateStageCapitalism: 36% sweeping, 36% beyond 2028). Their regulars will barely build records: not for lack of forecasting, but because the forecasts can't be checked.
- **r/neoliberal** hedges most: 24% "might/could", only 16% stated flatly (the lowest), 80% unconditional.
- **r/politics and r/Destiny** state things flatly (53% and 46%) and focus on election outcomes.
- **r/Conservative** has the most unresolvable forecasts (23%) and the most about courts and political violence.
- **The doomer sample** is 44% conditional and 44% about the next term, so it resolves now.

What it means:
- Scoring needs a rule for the 43% stated with no hedge. The planned "about 90%" assumption covers almost half the data, so it needs checking.
- A community's forecasting *style* is a signal in itself: predictions that can't be checked should rank differently from ones that came true or failed.
- Drop the unresolvable 12% and the untested hypotheticals early, before spending money scoring them.
- Only ~55% of forecasts are scorable, so cost per *useful* forecast is about double the cost per forecast.
- Sampling only around 2024 skews everything toward elections. Questions from other periods and topics are needed (see roadmap step 2).

### Informal accuracy check (calibration samples, Jul 8-14, 2024)
Clean right/wrong calls by Claude on the resolvable forecasts only, ignoring confidence and crowd comparison: r/Hasan_Piker 14/16, r/Destiny 8/9, r/politics 6/8, r/neoliberal 6/10, r/socialism 3/4, r/Conservative 2/4, r/LateStageCapitalism 3/3. Mostly measures one question (who saw the Biden withdrawal coming that week); 3-16 forecasts per subreddit is far too few to rank anyone.

### Second-term "doomer" predictions (2026-10-14, $2.28)
The question that started this research: how did fears about a second Trump term hold up? About 280 comments from r/neoliberal and r/politics, Oct 1 – Nov 4, 2024, found by searching "second term" and "if Trump wins". Claude found 151 forecasts; about 50 were about what a second term would bring, the rest mostly about who would win.

Resolved informally by Claude in chat from its own knowledge (which runs to about mid-2026 and is thinner for recent months), not entered as resolutions. These need your check and your rules before they count.

| | Predictions |
|---|---|
| **Came true** | Pardons loyalists ("just about guaranteed"): the Jan 6 pardons on day one. Tries to prosecute enemies ("just about guaranteed"): Comey and Letitia James indicted in fall 2025 (reportedly later dismissed over how the prosecutor was appointed). The Justice Department doesn't stop it; retaliation against opponents (law firms, security clearances). Tax breaks extended (2017 cuts made permanent, July 2025). Third-term / term-limit talk becomes prominent. |
| **Did not happen (so far)** | US leaves NATO ("no ifs or buts"). Removed under the 25th Amendment, or Vance becomes president. Liz Cheney flees the country. Trump pardons Musk. The open internet ends. Thousands of US troops die in a war with Iran. |
| **Partly** | "Starts a war with Iran": US strikes on Iran's nuclear sites, June 2025, but not the predicted war. "Strips citizens of citizenship and deports them": the birthright-citizenship order and a denaturalization push, not the scale predicted. Musk "kicked out": left after about four months, then a public feud. |
| **Pending** | Democrats sweep the 2026 midterms (Nov 3, 2026). Trump dies in office. |
| **Can't score without a written rule** | "Establishes a dictatorship", Orban-style vs. Modi-style, "the US doesn't survive", "far more harmful than the first term", "bad for everyone". About a third of the second-term forecasts. |

Pattern: specific predictions that he would use power *for allies and against enemies* mostly came true; predictions of *institutional collapse or catastrophe* mostly haven't; the most common kind was too vague to score. This sample was chosen by keyword, so it shows what people predicted, not who was accurate.

For the project: second-term predictions are a good question bank. There are many of them, they resolve gradually through 2029, and concrete markers ("the 2026 midterms happen on schedule", "a federal court order is openly defied") can stand in for unscoreable words like "dictatorship".

## Roadmap

### A. Validate the core
1. **Label the pilot (you).** `python -m predictor pilot label` (~110 comments), then `pilot report`. Measures model-vs-you agreement; decides whether the model can be trusted at scale.
2. **Group forecasts into claims (build), and widen the questions.** Merge near-duplicates into "Biden withdraws before the DNC: 7 comments, 2 yes / 5 no"; drop context-less and unresolvable ones. Add sample windows before other resolved events so it isn't all one question: Harris's running-mate pick, 2024 Senate/House control, the first Fed rate cut (Sept 2024), tariffs and recession talk, Gaza and Ukraine ceasefires, the NYC mayoral race, the fall 2025 shutdown, plus non-political ones (console launches, game delays, box office).
3. **Fix the scoring (build).** Crowd-relative score next to raw Brier, a measured confidence table instead of the hand-made one, a both-sides penalty, a decision on conditionals.

### B. Make the funnel affordable
4. ~~**Calibrate per subreddit.**~~ Done for the seven political subreddits (see Findings); repeat for each new one (~$0.75 each).
5. **Cut cost per comment (~$1-2 to test).** Cache the fixed instructions; then re-run the 504 pilot comments with Sonnet 5.5, Haiku 4.5, and ~20 comments per request, and compare each to Opus's results (and to your labels). Pick the cheapest setup that holds up.
6. **Build the panel funnel within $10/month.** Pick the panel (start with the top 25-50 per subreddit), phrase filter, the chosen model via Batch, 50 filtered comments per person per month, and a running monthly spend total that stops at the budget. Drop people who rarely forecast; keep rescanning those who do.

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
| Tech, AI | r/technology (18M), r/singularity (3.6M), r/accelerate (432k comments so far; the archive's subscriber count of 4k looks stale), r/MachineLearning (3M), r/hardware (4.3M) |
| Videogames | ★ r/GamingLeaksAndRumours (488k), r/Games (3.4M), r/pcgaming (3.8M), r/NintendoSwitch (7.7M), r/PS5 (8M) |
| Film, TV | ★ r/boxoffice (1.1M), ★ r/oscarrace (82k), r/movies (34M), r/television (17.5M) |
| Sports | ★ r/sportsbook (490k), ★ r/nba (15M), ★ r/nfl (11.9M), ★ r/soccer (8.4M), ★ r/formula1 (4.9M) |
| Science, space | ★ r/SpaceX (3.6M), r/space (27.6M) |
| Pessimism as a topic | r/collapse (524k): a natural place to test whether doom predictions come true |

r/singularity and r/accelerate make a natural pair, like r/collapse on the other side: AI optimists versus a more mixed crowd, making checkable claims about model releases, benchmarks and timelines.

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
