# Reddit Predictor

Score Reddit users on how well their predictions actually hold up, using the **Brier score**, so that one day you can sort a thread by *who has been right before* instead of by karma.

It is built for the vague, argumentative predictions that fill political threads ("he's never dropping out, mark my words"). A computer can't reliably decide whether those came true, so **you do that part**: you write a clear yes/no question, a model finds the comments that take a side on it, you check its work, and you record the outcome. Every linked comment is then scored at once.

See [PLAN.md](PLAN.md) for the design, status and roadmap.

## How it works

```
 you write a question  ->  collect comments  ->  model tags forecasts  ->  you review tags
 "Will Biden withdraw        Arctic Shift API      yes/no + confidence       accept / flip /
  before the convention?"    or archive dumps      for each comment          reject / re-rate
                                                                                   |
 overlay (planned)  <-  export JSON  <-  Brier score per user  <-  you resolve the question YES/NO
```

**Brier score:** for each forecast, `(p - outcome)^2`, where `p` is the probability the commenter effectively gave to YES and `outcome` is 1 or 0. Lower is better: 0 is perfect, 0.25 is what always saying 50/50 earns, 1 is confidently wrong. Confidence comes from wording ("might" is about 0.55, "probably" about 0.7, "mark my words" about 0.97).

Three rules keep it fair:
- Only comments posted **before the question's close date** count, so no one gets credit for hindsight.
- Several comments by one user on one question count **once** (their average).
- The leaderboard sorts by an **adjusted** score that pulls small samples toward 0.25, so one lucky call doesn't top the board.

## Setup

Needs Python 3.10+. The core uses only the standard library.

```bash
git clone https://github.com/GundamYeti/reddit_predictor.git
cd reddit_predictor
python3 -m venv venv
venv/bin/pip install -r requirements.txt   # optional extras: Claude backend, .zst reading
```

For the model, either:
- **Local (free):** [Ollama](https://ollama.com) running with a model pulled, e.g. `ollama pull phi3:mini`. Slow on a CPU, roughly a minute per comment on a small laptop.
- **Claude (paid, much faster and better with sarcasm):** set `ANTHROPIC_API_KEY`, then pass `--llm claude`.

## Walkthrough

```bash
P="venv/bin/python -m predictor"

# 1. Write a question: a clear yes/no with a date the answer became known.
$P question add "Will Joe Biden withdraw from the 2024 race before the Democratic convention?" \
    --opens 2024-06-27 --closes 2024-07-21 \
    --criteria "YES if he publicly ends his campaign before Aug 19, 2024" \
    --keywords "drop out,dropping out,step aside,withdraw,replace biden,staying in"

# 2. Collect comments from that window.
$P collect arctic -r politics -r PoliticalDiscussion --after 2024-06-27 --before 2024-07-21 --query "drop out"
#    ...or from a downloaded archive file:
$P collect file politics_comments.zst -r politics --after 2024-06-27 --before 2024-07-21 --keywords "drop out,step aside"

# 3. Let the model tag forecasts (try a small --limit first).
$P extract 1 --limit 20
$P extract 1 --llm claude

# 4. Review what it tagged: a = accept, r = reject, f = flip YES/NO, 0.8 = set confidence.
$P review 1

# 5. Record the outcome, then see the scores.
$P question resolve 1 yes
$P scores
$P scores --by subreddit
$P export data/user_scores.json   # for the overlay

$P status          # counts of everything
$P question list   # your questions and progress
```

Everything lives in `data/predictor.db` (SQLite; set `--db` or `PREDICTOR_DB` to change it).

## Settings

| Environment variable | Default | Meaning |
|---|---|---|
| `PREDICTOR_DB` | `data/predictor.db` | database file |
| `PREDICTOR_LLM` | `ollama` | `ollama` or `claude` |
| `PREDICTOR_OLLAMA_MODEL` | `phi3:mini` | local model |
| `PREDICTOR_OLLAMA_URL` | `http://localhost:11434` | Ollama server |
| `PREDICTOR_OLLAMA_TIMEOUT` | `300` | seconds per comment |
| `PREDICTOR_CLAUDE_MODEL` | `claude-opus-5` | Claude model |
| `PREDICTOR_CLAUDE_EFFORT` | `low` | `low` / `medium` / `high`: more is slower and costs more |

## Tests

```bash
python3 -m unittest discover tests
```

The tests use synthetic comments (`tests/fixtures/`) and a scripted stand-in for the model, so they run offline in well under a second.

## Layout

```
predictor/
  __main__.py   command line
  db.py         SQLite schema
  sources.py    Arctic Shift API and archive-file readers
  llm.py        Ollama and Claude backends
  extract.py    prompt + tagging a question's comments
  review.py     terminal review queue
  score.py      Brier scores, leaderboards, JSON export
tests/          offline tests
legacy/         the original Gemini-era scripts (not used; kept for reference)
```
