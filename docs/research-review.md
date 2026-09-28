# Research review: finding and scoring predictions in Reddit comments

*September 2026. Written after the first real test run, to decide how to find predictions before building more.*

## 1. Where we are and what went wrong

**How comments are selected today** (three filters in a row):

1. **Topic search.** Arctic Shift's full-text search for topic words ("drop out", "step aside", "stay in"), about 10 comments per day.
2. **Keyword filter.** A comment must contain one of the question's keywords.
3. **Model judgment.** A model decides whether the comment forecasts *this* question, which side it takes, and how sure it sounds. Confidence comes from a phrase-to-probability table I wrote by hand.

**What the first 20 real comments showed:**
- Only **1 in 20** was an actual forecast ("He'll stay in and lose the election"). Most were arguments about what Biden *should* do.
- phi3:mini tagged 4 "he needs to step aside" comments as forecasts and missed the real one.

**Three weaknesses in the current design:**
- **Topic words find arguments, not predictions.** Searching "drop out" surfaces people *demanding* he drop out.
- **The confidence table isn't grounded in evidence.** I made it up; the research below has measured tables.
- **Question-first only finds what you thought to ask.** You'd never learn what Redditors actually predict on their own.

The user's instinct, to look for predictions without a preset question and to lean on Tetlock's work on verbal probability, matches what the literature suggests.

## 2. What the research says

### 2a. Scoring forecasters: Tetlock and the Good Judgment Project

- **Expert Political Judgment** (Tetlock, 2005): tracked about 28,000 predictions from political experts over two decades. Experts barely beat simple baselines. "Foxes" (many ideas, comfortable with uncertainty) beat "hedgehogs" (one big idea, confident). Scoring used the Brier score, as this project does.
- **Good Judgment Project / IARPA ACE tournament, 2011-2015** ([Mellers et al., 2014](https://journals.sagepub.com/doi/10.1177/0956797614524255); [Mellers et al., 2015](https://journals.sagepub.com/doi/abs/10.1177/1745691615577794)): some people ("superforecasters") stay accurate across hundreds of questions and don't regress to the mean. **Skill is real and persistent, so a per-user score can mean something.**
- **Why it worked:** questions were written to pass a "clairvoyance test": a clear resolution rule and a deadline, so nobody could argue afterwards about whether it came true. **This supports keeping you in charge of question wording and resolution.**
- **Pundits in the wild:** [Hamilton College (2011)](https://www.hamilton.edu/documents/an-analysis-of-the-accuracy-of-forecasts-in-the-political-media.pdf) coded 472 predictions by 26 newspaper and TV pundits. Only 9 beat a coin flip. **Conditional predictions ("if A, then B") were less accurate**, which is worth tracking separately.

### 2b. What verbal phrases mean as probabilities

- **Sherman Kent (CIA, 1964), "Words of Estimative Probability":** a 1951 intelligence estimate called a Soviet attack on Yugoslavia a "serious possibility". Kent meant about 65%; colleagues who signed it read it as anything from 20% to 80%. This started the whole research area.
- **[Mosteller & Youtz (1990)](https://projecteuclid.org/euclid.ss/1177012242):** pooled 20 studies covering 52 phrases. **The average meaning of each phrase is fairly stable across groups** (students, doctors, science writers), so a lookup table is reasonable.
- **[Mauboussin & Mauboussin (2018, HBR)](https://hbr.org/2018/07/if-you-say-something-is-likely-how-likely-do-people-think-it-is):** 1,700 people. The average is stable, but **individuals vary a lot**: the middle 90% of people read "likely" as anywhere from 55% to 90%.
- **Reddit's own version:** [u/zonination's 2015 survey](https://github.com/zonination/perceptions) on r/samplesize (about 50 respondents, open data) and a [2019 follow-up by Fagen-Ulmschneider](https://waf.cs.illinois.edu/visualizations/Perception-of-Probability-Words/) (123 people). Median readings from the follow-up:

  | Phrase | Median | Phrase | Median |
  |---|---|---|---|
  | almost certain | 95% | about even | 50% |
  | highly likely | 90% | probably not | 25% |
  | very good chance | 80% | unlikely / we doubt | 20% |
  | we believe | 75% | little chance / improbable | 10% |
  | probably / likely | 70% | highly unlikely | 5% |
  | better than even | 60% | almost no chance | 2% |

- **Directionality ([Teigen & Brun, 1999](https://pubmed.ncbi.nlm.nih.gov/10527815/)):** "there's a chance he drops out" and "it's not certain he stays" can mean the same probability but point opposite ways. **Negative phrasing ("doubtful", "not sure") points toward the event *not* happening.** The model has to get the direction right, not just the number.
- **Words cost accuracy ([Friedman, Baker, Mellers, Tetlock & Zeckhauser, 2018](https://academic.oup.com/isq/article-abstract/62/2/410/4944059)):** across 888,328 tournament forecasts, rounding numbers into verbal categories consistently made them less accurate. **Implication for us:** scores built from verbal forecasts are noisier, so users need more resolved forecasts before their score means much. The small-sample adjustment already handles this; it may need to be stronger.
- **Intelligence community practice ([Dhami & Mandel, 2021](https://pubmed.ncbi.nlm.nih.gov/32700939/)):** standard phrase-to-range tables help but don't remove the ambiguity.
- **Language models on these phrases ([Tang, Shen & Kejriwal, 2024; npj Complexity 2026](https://arxiv.org/abs/2405.15185)):** GPT-4-class models match human readings for some phrases but not others. **Better to have the model extract the exact phrase and look up its probability in a human-measured table than to let the model guess a number.**

### 2c. Finding predictions in text automatically

- **Closest precedent: [Swamy, Ritter & de Marneffe (2017), "i have a feeling trump will win..."](https://aclweb.org/anthology/D17-1166)** (EMNLP). They collected tweets about contests (elections, awards, sports) and annotated each for **veridicality**: how certain the author is that an outcome will happen ("X will win" vs "X may win" vs "no way X wins"). A classifier found confident predictions with high precision. **They also measured the reliability of individual accounts**, which is essentially this project's idea, validated on Twitter.
- **Future-oriented text:** Jatowt & Au Yeung (2011, CIKM) pulled "collective expectations about the future" from large news collections, the ancestor of the discovery idea. [Prashar, Shukla & Jatowt (2025)](https://arxiv.org/abs/2502.15332) detect future-oriented mentions of people and organizations: a fine-tuned Llama 3 reached F1 0.93, and RoBERTa 0.91. **This step (does the comment talk about the future?) is largely solved.** Separating prediction from wish is the harder part.
- **Certainty and hedging** (standard NLP resources): FactBank (Saurí & Pustejovsky, 2009) labels how certain a writer is that an event happens (certain / probable / possible, positive or negative). The CoNLL-2010 shared task detected hedges ("might", "suggests"). de Marneffe, Manning & Potts (2012) showed readers' certainty judgments depend on context and speaker, not just the words. **These give tested label schemes to copy rather than inventing our own.**
- **Sarcasm on Reddit:** the SARC corpus (Khodak et al., 2018) uses Reddit's own "/s" tag to label over a million sarcastic comments. It's useful for testing whether the tagger reads sarcastic predictions the right way round.

### 2d. Judging forecasters from their words

- **[Zong, Ritter & Hovy (2020)](https://aclanthology.org/2020.acl-main.473/):** using Good Judgment Open rationales and analyst earnings forecasts, **language alone predicted forecasting skill.** Better forecasters were more tentative, quoted outside sources, referred to the past more than the future, and used "I" more than "they".
- **[Karvetski, Huang, … Tetlock & Karger (June 2026)](https://arxiv.org/html/2606.30987):** an LLM scored 55,000 forecast rationales from the ACE tournament on 60 reasoning-quality markers. Scores correlated with forecaster-level accuracy at **r = 0.51** (0.46 on new data), versus 0.39 for older text methods. Prior-season accuracy was still the best predictor (r = 0.70). **A track record beats writing style, but style gives a usable early signal for users with no track record**, which is most users in any thread.

### 2e. Scoring self-selected forecasts fairly

- **The problem:** tournament forecasters answer questions they're assigned. Redditors choose when to speak: often when the answer is already obvious, or after the news broke. A raw Brier score rewards easy, late calls.
- **What platforms do:** [Metaculus](https://www.metaculus.com/help/scores-faq/) reports a **Peer score** (you vs. everyone else forecasting the same question at the same time) alongside a **Baseline score** (you vs. a coin flip). Good Judgment scored forecasts relative to the crowd and averaged over the days a question was open.
- **Implication:** score each Redditor **relative to what others in the same thread or week expected.** Saying "he'll drop out" on July 20 should earn much less than saying it on June 28.
- **Hindsight bias** (Fischhoff, 1975): once people know an outcome, they overrate how predictable it was. Keep strict posting-time cutoffs; the current code already does this.

## 3. How this changes the method

| Current method | Evidence-based change | Why |
|---|---|---|
| Search topic words ("drop out") | Search **prediction language** ("will", "won't", "gonna", "no way", "mark my words", "calling it", "bet", "RemindMe!") | Topic words find arguments; prediction markers find predictions (Swamy 2017) |
| Start from your question | **Discover first**: find forecasts on any topic, group similar ones, then you turn popular groups into questions | Shows what people predict unprompted (Jatowt 2011), and each question you write covers more forecasts |
| Model guesses a confidence number | Model copies the **exact phrase**; a **measured table** turns it into a probability | Phrase meanings are stable on average (Mosteller & Youtz 1990); models are inconsistent (Tang 2024) |
| Yes/no relevant + stance | Record **proposition, direction, deadline, hedge phrase, conditional?, sarcasm?** | Directionality (Teigen), conditionals are less accurate (Hamilton), sarcasm is common (SARC) |
| Raw Brier per user | Brier **plus a peer-relative score** against the crowd at the same time | Unprompted forecasters pick easy and late calls (Metaculus, GJP) |
| Nothing for new users | Later: a **reasoning-quality signal** shown separately from the track record | Language predicts skill at r ≈ 0.5 (Karvetski 2026), but a record is better |

## 4. Recommendation

### Step 1: A discovery pilot (small, cheap, answers the key questions)
Take an **unfiltered random sample of about 500 r/politics comments** from the June 27 - July 21 window. For each comment, have a strong model (Claude; phi3:mini isn't good enough) record:
- **Is it a forecast?** It must be an expectation about a future, checkable event, not a wish, advice or a hypothetical.
- If so: **the proposition in plain words** ("Biden will withdraw before the DNC"), **direction** (happens / doesn't), **deadline** if stated, **the exact hedge phrase**, **conditional?**, **sarcasm?**.

You hand-label about 100 of the same comments. That gives an answer key to measure the model against, since reading these comments is the one step that must be trustworthy.

The pilot answers:
- How common are real forecasts in unfiltered comments? (We saw 1 in 20 among topic-searched ones.)
- **What do people naturally predict about?** This is the discovery question you asked.
- Which hedge phrases do Redditors actually use, and does the model find them reliably?
- Does searching prediction language find a richer set than topic words?

Rough cost: a few dollars on the Claude API at my estimate. I'll measure the real cost on the first 50.

### Step 2: Group, then promote to questions
Group the pilot's propositions by meaning (embeddings plus clustering, or have the model merge near-duplicates). You get a list like "83 comments: Biden withdraws before the DNC (61 yes / 22 no); 40 comments: Harris is the nominee; …". **You pick which groups become questions**, write the resolution rule, and resolve them. Human resolution stays, but the questions come from the data.

### Step 3: Fix the scoring
- Replace the hand-made confidence table with the measured one. Treat plain assertions ("He'll stay in") as about 90%, and flag that as an assumption to check against Reddit's own data later.
- Add the peer-relative score next to the raw Brier.
- Report conditional forecasts separately.

### Step 4 (later): the overlay and reasoning-quality signals
Build the overlay only once a meaningful number of users have 3 or more resolved forecasts. Reasoning-quality markers could fill in for users without a record, clearly labeled as a different kind of signal.

### What stays the same
The database, collection, review queue, resolution and export all carry over. The changes are in *what* gets extracted and *how* it's scored, not the plumbing.

## References

- Brier, G. W. (1950). Verification of forecasts expressed in terms of probability. *Monthly Weather Review*, 78(1).
- de Marneffe, M.-C., Manning, C. D., & Potts, C. (2012). Did it happen? The pragmatic complexity of veridicality assessment. *Computational Linguistics*, 38(2).
- Dhami, M. K., & Mandel, D. R. (2021). [Words or numbers? Communicating probability in intelligence analysis](https://pubmed.ncbi.nlm.nih.gov/32700939/). *American Psychologist*, 76, 549-560.
- Fagen-Ulmschneider, W. (2019). [Perception of probability words](https://waf.cs.illinois.edu/visualizations/Perception-of-Probability-Words/).
- Farkas, R., et al. (2010). The CoNLL-2010 shared task: Learning to detect hedges and their scope in natural language text.
- Fischhoff, B. (1975). Hindsight ≠ foresight. *Journal of Experimental Psychology: Human Perception and Performance*, 1(3).
- Friedman, J. A., Baker, J. D., Mellers, B. A., Tetlock, P. E., & Zeckhauser, R. (2018). [The value of precision in probability assessment](https://academic.oup.com/isq/article-abstract/62/2/410/4944059). *International Studies Quarterly*, 62(2).
- Hamilton College (Wyckoff et al.) (2011). [Are talking heads blowing hot air?](https://www.hamilton.edu/documents/an-analysis-of-the-accuracy-of-forecasts-in-the-political-media.pdf)
- Jatowt, A., & Au Yeung, C.-M. (2011). Extracting collective expectations about the future from large text collections. *CIKM*.
- Karvetski, C., Huang, …, Tetlock, P. E., & Karger, E. (2026). [Measuring judgment quality in natural-language explanations: Evidence from forecasting tournaments](https://arxiv.org/html/2606.30987). arXiv.
- Kent, S. (1964). Words of estimative probability. *Studies in Intelligence*.
- Khodak, M., Saunshi, N., & Vodrahalli, K. (2018). A large self-annotated corpus for sarcasm (SARC). *LREC*.
- Mauboussin, A., & Mauboussin, M. J. (2018). [If you say something is "likely," how likely do people think it is?](https://hbr.org/2018/07/if-you-say-something-is-likely-how-likely-do-people-think-it-is) *Harvard Business Review*.
- Mellers, B., et al. (2014). [Psychological strategies for winning a geopolitical forecasting tournament](https://journals.sagepub.com/doi/10.1177/0956797614524255). *Psychological Science*.
- Mellers, B., et al. (2015). [Identifying and cultivating superforecasters](https://journals.sagepub.com/doi/abs/10.1177/1745691615577794). *Perspectives on Psychological Science*.
- Metaculus. [Scores FAQ](https://www.metaculus.com/help/scores-faq/).
- Mosteller, F., & Youtz, C. (1990). [Quantifying probabilistic expressions](https://projecteuclid.org/euclid.ss/1177012242). *Statistical Science*, 5(1), 2-34.
- Prashar, P., Shukla, K. M., & Jatowt, A. (2025). [Detecting future-related contexts of entity mentions](https://arxiv.org/abs/2502.15332). arXiv.
- Saurí, R., & Pustejovsky, J. (2009). FactBank: A corpus annotated with event factuality. *Language Resources and Evaluation*, 43.
- Swamy, S., Ritter, A., & de Marneffe, M.-C. (2017). ["i have a feeling trump will win...": Forecasting winners and losers from user predictions on Twitter](https://aclweb.org/anthology/D17-1166). *EMNLP*.
- Tang, Z., Shen, K., & Kejriwal, M. (2024/2026). [An evaluation of estimative uncertainty in large language models](https://arxiv.org/abs/2405.15185). *npj Complexity*.
- Teigen, K. H., & Brun, W. (1999). [The directionality of verbal probability expressions](https://pubmed.ncbi.nlm.nih.gov/10527815/). *Organizational Behavior and Human Decision Processes*, 80(2).
- Tetlock, P. E. (2005). *Expert Political Judgment: How Good Is It? How Can We Know?* Princeton University Press.
- Tetlock, P. E., & Gardner, D. (2015). *Superforecasting: The Art and Science of Prediction.* Crown.
- zonination (2015). [Perceptions of probability and numbers](https://github.com/zonination/perceptions). r/samplesize survey data.
