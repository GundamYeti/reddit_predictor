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
Each scan in the pilot sent ~1,370 tokens in and got ~90 back, and ~1,200 of the input was the same fixed instructions repeated for every comment. Caching those instructions (cached input costs a tenth) and packing comments together cut the cost per comment several times over.

**Measured 2026-10-15 on the 504 pilot comments** ([research/model_compare.py](research/model_compare.py), ~$1.80 total). "Catches" = of the 76 comments where Opus found a forecast, how many this setup also flagged. Opus is the reference, not the truth: your labels will settle who's right where they disagree.

| Setup | $ per 1,000 comments | Catches Opus's | Extra flags | Comments for $10 (with Batch, half price) |
|---|---|---|---|---|
| Opus 5.5, one per request, no cache (the pilot) | $6.90 | – | – | ~2,900 |
| Opus 5.5 + cache (from a 3-call check) | ~$1.80 | – | – | ~11,000 |
| Sonnet 5.5 + cache, one per request | $1.34 | 68/76 (89%) | 13 | ~15,000 |
| **Sonnet 5.5 + cache, 20 per request** | **$0.83** | **69/76 (91%)** | 16 | **~24,000** |
| Haiku 4.5, one per request (too short to cache) | $1.29 | 46/76 (61%) | 13 | rejected: misses too much, and no cheaper |

Where packed Sonnet and Opus disagree, it's mostly borderline cases both ways: Sonnet missed some real ones ("the idea of him stepping aside has been so unrealistic", "Texas is so red it won't matter") and added some weak ones ("it would be a great way to lose the black vote"). It also skipped 13 of 504 comments on the first pass (a rerun filled them in), so packed runs need a retry for skipped ids.

**Choice for now: Sonnet 5.5, cached, ~20 comments per request, via Batch.** Built 2026-10-15 (`python -m predictor batch submit | collect`, see README). First real batches: 214 comments for $0.11, i.e. **$0.40-0.60 per 1,000** depending on how forecast-heavy the comments are, so **~17,000-25,000 comments a month fit in $10**. Each batch finished in under 10 minutes. Listing the expected comment ids at the end of each request stopped the model skipping comments (14 of 100 skipped before, 0 of 114 after). Against Opus on the r/neoliberal and r/Destiny calibration samples, the batch results caught 90% and 97% of Opus's forecast comments, with 6 and 9 extra flags. Revisit once your labels show whether its extra flags and misses are worse than Opus's.

**Budget guard.** Every paid run now records its cost in a `spend` table; `batch submit` refuses to send a batch whose estimate would push the calendar month past `PREDICTOR_MONTHLY_BUDGET` (default $10), and `python -m predictor spend` shows the month so far. The ledger started 2026-10-15 at $0: the ~$15 of research before it (pilot, calibration, comparisons) isn't counted. Open question for you: should one-time research count against the monthly $10?

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

### What kinds of predictions people make (re-run 2026-10-15 with non-political subreddits, $2.88)
An open-ended classification: Claude proposes its own categories from the data, then labels each forecast. Second run, over all 726 forecasts Opus has found: the 477 political ones (pilot, calibration samples, doomer sample) plus 100 filtered comments from each of 5 non-political subreddits' 15 heaviest commenters during **June 2-8, 2025** (Switch 2 launch, NBA Finals, Summer Game Fest, early summer box office). Script and results: [research/classify_forecasts.py](research/classify_forecasts.py) (`--report` prints the full table), [forecast_taxonomy.json](research/forecast_taxonomy.json), [forecast_labels.json](research/forecast_labels.json). The categories are re-invented on each run, so the numbers aren't directly comparable with the first run's; locking them is a to-do.

| | Crisply resolvable | Resolvable with judgment | Hard to resolve or unresolvable | Long or no horizon | Unhedged |
|---|---|---|---|---|---|
| r/GamingLeaksAndRumours | **67%** | 33% | **0%** | 5% | 18% |
| r/boxoffice | 54% | 37% | 9% | 5% | 36% |
| r/nba | 41% | 38% | 22% | 5% | 30% |
| r/wallstreetbets | 38% | 24% | 38% | 6% | 41% |
| r/politics | 33% | 32% | 34% | 6% | 55% |
| r/Destiny | 33% | 38% | 28% | 10% | 46% |
| r/Hasan_Piker | 24% | 41% | 36% | 11% | 50% |
| r/accelerate | 5% | 16% | **80%** | **83%** | 36% |
| r/LateStageCapitalism | 9% | 27% | **64%** | 50% | 41% |

(r/neoliberal, r/Conservative and r/socialism have only 21-25 forecasts each; see `--report`.)

What stands out:
- **Gaming and box office are the most scorable communities by far.** r/GamingLeaksAndRumours: 78% of forecasts are a company doing something specific (announce, delay, release), and none are unresolvable. r/boxoffice: 41% are numeric targets (opening weekend, totals). Both resolve within weeks. Ideal testbeds for the scoring, as planned.
- **r/accelerate and r/LateStageCapitalism mirror each other.** AI optimists and anti-capitalists both make sweeping, long-range "structural transformation" predictions (r/accelerate 56% of its forecasts), most with no horizon or a long one, and most hard or impossible to resolve. Their regulars will barely get records, for the same reason.
- **r/wallstreetbets** is 97% markets: numeric price targets and short horizons (35% within days), but 35% unresolvable (no ticker, date or level), and the most sarcasm (9%, with r/nba at 8%).
- **Hedging is cultural.** r/GamingLeaksAndRumours, a rumor community, hedges most ("probably" etc. 64%, flat statements only 18%); r/politics states things flatly most (55%).
- **Politics is in the middle on scorability** (about two-thirds resolvable at least with judgment), and the doomer sample is the most conditional (34% on a plausible condition, 17% on a counterfactual).

Implications:
- Scoring needs a rule for unhedged forecasts (40% of all); the 90% assumption is the biggest single assumption in the system.
- A community's forecasting *style* is a signal in itself; unresolvable-heavy communities need a different signal (reasoning quality) or none.
- Drop unresolvable forecasts and counterfactuals early, before spending money scoring them.
- Start scoring on gaming, box office and sports: fast, crisp outcomes test the machinery without political judgment calls.

### Gender-politics subreddits (research only, 2026-10-15, $1.07)
r/Feminism, r/TwoXChromosomes and r/MensRights: 100 filtered comments each from the 15 heaviest commenters, Oct 28 - Nov 3, 2024 (the week before the election, when the gender gap and abortion were big campaign issues). r/TheRedPill is quarantined and nearly dead (101 comments that week from 53 people), so its sample spans the five weeks before the election instead. These are for curiosity about accuracy, **not for the feed**.

| | Forecasts per 100 filtered comments | Crisply resolvable | Hard to resolve or unresolvable |
|---|---|---|---|
| r/TwoXChromosomes | 14 | 1 | 12 of 14 |
| r/Feminism | 7 | 0 | 6 of 7 |
| r/TheRedPill | 6 | 0 | 6 of 6 |
| r/MensRights | 5 | 1 | 4 of 5 |
| *for comparison: r/politics* | *28* | | |
| *r/Hasan_Piker* | *54* | | |

- **Their accuracy can't really be measured: they barely make checkable predictions.** These are discussion and support communities. Most of their few forecasts are about someone's personal life ("she'll make an excuse not to come back tomorrow", "therapy won't change your husband"), the subreddit itself (moderator bans), or sweeping futures ("World War 3 takes place", "harvested personal data will be used against people").
- **The two scorable ones were both right:** r/TwoXChromosomes, "Texas won't flip to Democrats in 2024" ("I'm not holding my breath"); r/MensRights, "Trump might win the 2024 election" (only a weak "might").
- Their members would almost never get a track record, so for communities like these a reasoning-quality signal is the only kind of score possible.
- The locked categories from the main run have no "personal life" topic, so personal predictions were forced into the nearest topic; another reason to revise the categories before locking them.

### Informal accuracy check, all samples (2026-10-15)
Claude resolved every *crisply resolvable* forecast it could from its own knowledge (not your rules; resolutions in [research/informal_resolutions.json](research/informal_resolutions.json), keyed by forecast id). Skipped: forecasts with no deadline that haven't happened yet (most second-term predictions, "Iran gets nukes"), conditions not met, unknown referents ("the film"), "Biden loses the election" (he wasn't on the ballot), and anything not confidently known. Brier uses the hedge table; 0.25 = always saying 50/50.

| Community (sample week) | Right | Brier |
|---|---|---|
| r/Hasan_Piker (Jul 2024) | 10/10 | 0.04 |
| r/nba (Jun 2025) | 5/6 | 0.08 |
| r/boxoffice (Jun 2025) | 6/7 | 0.12 |
| r/Destiny (Jul 2024) | 6/8 | 0.24 |
| r/politics (Jun-Jul 2024) | 31/46 | 0.25 |
| r/neoliberal (Jul 2024) | 5/8 | 0.26 |
| r/politics, doomer sample (Oct 2024) | 12/23 | 0.34 |
| r/neoliberal, doomer sample (Oct 2024) | 9/25 | 0.41 |
| r/wallstreetbets (Jun 2025) | 0/3 | 0.67 |
| Fewer than 4 resolvable: r/Conservative 2/3, r/GamingLeaksAndRumours 2/2, r/LateStageCapitalism 2/2, r/accelerate 1/2, r/socialism 0/1, r/TwoXChromosomes 1/1, r/MensRights 1/1 | | |

What it shows, and why not to lean on it:
- **Mostly two questions.** The political rows mostly measure "will Biden withdraw?" (July) and "who wins in November?" (October). r/Hasan_Piker's regulars called both; r/neoliberal's October commenters mostly called Harris, at a time when polls were close to 50/50, so confident Harris calls cost them.
- **Easy calls inflate scores.** Many sports and box-office hits are safe "won't" calls ("Superman won't make $2 billion"). The crowd-relative score is built to discount these, but needs more forecasters per question than these samples have.
- **Different weeks, different difficulty.** Calling the election in mid-July is harder than calling it on Nov 4; rows from different weeks aren't comparable.
- **Tiny samples:** 1-46 resolved forecasts per row, one week each.
- A real ranking needs the panel funnel: the same people, many questions, compared against the crowd at the same time.

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
1. ~~**Label the pilot (you).**~~ Done 2026-10-22 (183 of 184, via the spreadsheet). By your labels 20% of random r/politics comments hold a forecast (Opus said 15%). Against your labels: Opus caught 63% of the random slice's forecasts and was right 82% of the time it flagged one (83% overall agreement); **packed Sonnet, the budget pick, caught 74%, right 76% (80% overall)**; single Sonnet 63% / 74%; Haiku 53% / 91%. So the budget setup holds up. Disagreements are mostly where to draw the line: you count hypotheticals ("it would be a great way to lose the black vote") as forecasts, the models count venting ("they're going to fuck it up like they always do"); trolling ("MAGA will have camps…") looks sincere to the models.
2. **Group forecasts into claims (build), and widen the questions.** Merge near-duplicates into "Biden withdraws before the DNC: 7 comments, 2 yes / 5 no"; drop context-less and unresolvable ones. Add sample windows before other resolved events so it isn't all one question: Harris's running-mate pick, 2024 Senate/House control, the first Fed rate cut (Sept 2024), tariffs and recession talk, Gaza and Ukraine ceasefires, the NYC mayoral race, the fall 2025 shutdown, plus non-political ones (console launches, game delays, box office). **Built 2026-10-15, first run 2026-10-20 ($0.91):** the panel's 2,319 forecasts became **427 claims** (537 forecasts); 1,781 were dropped as uncheckable. The first pass dropped too much (1 in 10 drops were checkable, e.g. "The Odyssey's final domestic gross will be $630-660M"), so the prompt now says to keep anything checkable against public records, and `--recheck-drops` re-ran the drops. Only **43 claims have 2+ people** behind them: most panel members predict different things, so per-person records will come mostly from many single-person claims.
3. ~~**Fix the scoring.**~~ Done 2026-10-15 for the question pipeline: confidence now comes from the author's exact hedge phrase via a measured table ([predictor/hedges.py](predictor/hedges.py); plain statements assumed 90%), a crowd-relative score ("vs crowd": your Brier minus the crowd's that week on the same question), a both-sides rule (YES and NO within 7 days: scored on the wrong side), and conditionals that count only once you mark the condition met (`m` / `x` in the review queue). Still to do: use the same rules for forecasts found by discovery once they're grouped into questions.

### B. Make the funnel affordable
4. ~~**Calibrate per subreddit.**~~ Done for the seven political subreddits (see Findings); repeat for each new one (~$0.75 each).
5. ~~**Cut cost per comment.**~~ Done 2026-10-15: caching is on, and packed Sonnet 5.5 is the pick (see "What $10/month buys"). Re-check against your labels.
6. **Build the panel funnel within $10/month.** Built 2026-10-15: `panel pick | fetch | status` (see README), then `batch submit --tag panel`. First panel: the top 20 commenters in each of r/politics, r/neoliberal, r/Destiny, r/Hasan_Piker, r/Conservative, r/LateStageCapitalism, r/boxoffice, r/GamingLeaksAndRumours and r/nba (180 people, ranked by the week of 2026-09-28), backfilled one month at up to 40 strict-filtered comments per person (~7,000 comments, ~$4). A 3-month backfill would be ~$11, over one month's budget, so extend a month at a time. Refreshes continue from each member's last fetched week, and `panel prune` drops members who make fewer than 5 forecasts a month (judged once 20+ of their comments are scanned). Still to do: run the refresh on a schedule. Pick the panel (start with the top 25-50 per subreddit), phrase filter, the chosen model via Batch, 50 filtered comments per person per month, and a running monthly spend total that stops at the budget. Drop people who rarely forecast; keep rescanning those who do.

### C. Ground truth at scale
7. **Import resolved prediction-market questions** and match forecasts to them; your own questions cover the rest. **Built 2026-10-15 for Polymarket** (`markets match | sync`; first run 2026-10-20, $0.42: **34 of 427 claims matched**, 5 already resolved, e.g. Endgame Encore opening at #1, Resident Evil opening under $70M; markets that closed before a claim's first forecast are excluded, after early matches to 2025 markets): a promoted claim with a matched market uses its wording, rules and outcome. Kalshi is reachable but dominated by 15-minute price markets; Metaculus now needs an API token.
8. **Event-triggered search.** When something surprising resolves, search for related comments made before it and *nominate* the people who called it. Their full history then decides; one lucky long shot proves nothing.

### D. The feed
9. **Coverage test.** One snapshot of a current front page: how many commenters have a usable record? Tells us whether the feed works before we build it.
10. **Local web page first** (simpler than a browser extension): fetch the front page via Reddit's API (free personal-use credentials), score posts by their commenters' records, re-rank, and show *why* each post ranked where it did.

### E. Expand
11. **Per-topic scores.** Videogames may be easier than politics: release dates, sales and review scores resolve on their own.
12. **Bluesky**, then other platforms. Each account is scored on its own; cross-platform identity matching is out of scope.

## Subreddits

Two separate lists: subreddits studied for research (how communities predict and how accurate they are) and subreddits that feed your ranked front page. **Studying a subreddit does not put it in the feed.**

**Research only, not for the feed** (you're curious about their accuracy, 2026-10-15): r/Feminism, r/TwoXChromosomes, r/MensRights, r/TheRedPill. Which of the others below end up in the feed is still your call; none are in it yet.

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
- Crowd-relative scoring, hedge-phrase confidence table, both-sides and conditional rules; prompt caching in the Claude backend.
- Batch API scanning with packed requests, a spend ledger and a monthly budget guard.
- Offline tests (38).

## Things to keep in mind
- **Reddit's terms:** keep collected data local and for personal use. Publishing per-user scores of real people is a much bigger step and deserves a closer look first.
- **Model mistakes:** unreviewed tags never count unless you pass `--include-unreviewed`.
- **Volume is not a virtue.** A high comment count is also a bot trait; only accuracy may raise a score.
- **Deleted accounts and bots** are skipped when collecting.
- **Shared laptop:** the local model shares one Ollama server with `~/ai-assistant`; keep `num_ctx` at 2048 and run one heavy model job at a time.
