"""Turn the author's own hedge words into a probability, from a measured table.

The model copies the exact phrase ("I doubt it", "mark my words"); this table
turns it into the probability the author gives their own stance. Research says
models guess these numbers inconsistently, while the average reading of each
phrase is stable across groups (see docs/research-review.md, section 2b).

MEASURED: medians from the 2019 Perception of Probability Words survey
(Fagen-Ulmschneider, 123 people), the follow-up to r/samplesize's 2015 survey.
Phrases that point at the event NOT happening ("unlikely", "we doubt") are
converted to the author's stance: someone who says "I doubt he drops out"
expects NO, and gives NO 1 - 20% = 80%.

ASSUMED: everything marked "assumed" below, including plain statements with no
hedge at all ("He'll stay in"), set to 90%. Plain statements are 43% of the
forecasts found so far, so this assumption matters; check it against Reddit's
own data once enough questions resolve.
"""

import re

PLAIN = 0.9      # assumed: no hedge words at all
UNKNOWN = 0.75   # assumed: a hedge phrase this table doesn't recognize

# (phrase, probability the author gives their own stance, source)
TABLE = [
    # Measured (event-probability medians, converted to the author's stance).
    ("almost certain", 0.95, "measured"),
    ("highly likely", 0.90, "measured"),
    ("very good chance", 0.80, "measured"),
    ("we believe", 0.75, "measured"),
    ("i believe", 0.75, "measured"),
    ("probably not", 0.75, "measured: 25% for the event"),
    ("probably", 0.70, "measured"),
    ("likely", 0.70, "measured"),
    ("better than even", 0.60, "measured"),
    ("about even", 0.50, "measured"),
    ("highly unlikely", 0.95, "measured: 5% for the event"),
    ("unlikely", 0.80, "measured: 20% for the event"),
    ("doubt*", 0.80, "measured ('we doubt'): 20% for the event"),
    ("little chance", 0.90, "measured: 10% for the event"),
    ("improbable", 0.90, "measured: 10% for the event"),
    ("almost no chance", 0.98, "measured: 2% for the event"),
    # Assumed: common Reddit phrasings the survey didn't cover, placed next to
    # the measured phrase they most resemble.
    ("guarantee*", 0.95, "assumed, like 'almost certain'"),
    ("definitely", 0.95, "assumed"),
    ("certainly", 0.95, "assumed"),
    ("absolutely", 0.95, "assumed"),
    ("for sure", 0.95, "assumed"),
    ("no doubt", 0.95, "assumed"),
    ("100%", 0.95, "assumed"),
    ("no way", 0.95, "assumed"),
    ("zero chance", 0.97, "assumed, like 'almost no chance'"),
    ("0% chance", 0.97, "assumed"),
    ("not a chance", 0.97, "assumed"),
    ("inevitabl*", 0.95, "assumed"),
    ("mark my words", 0.95, "assumed"),
    ("calling it", 0.95, "assumed"),
    ("i'd bet", 0.85, "assumed"),
    ("bet", 0.85, "assumed"),
    ("very probably", 0.85, "assumed"),
    ("very likely", 0.85, "assumed"),
    ("pretty sure", 0.80, "assumed"),
    ("i'm confident", 0.80, "assumed"),
    ("good chance", 0.75, "assumed, below 'very good chance'"),
    ("i'd be surprised if", 0.80, "assumed"),
    ("expect*", 0.75, "assumed, like 'we believe'"),
    ("i think", 0.70, "assumed, like 'probably'"),
    ("i suspect", 0.70, "assumed"),
    ("i feel", 0.65, "assumed"),
    ("feeling", 0.65, "assumed"),
    ("seems", 0.65, "assumed"),
    ("i'm not sure", 0.55, "assumed"),
    ("not sure", 0.55, "assumed"),
    ("maybe", 0.55, "assumed"),
    ("might", 0.55, "assumed"),
    ("could", 0.55, "assumed"),
    ("may", 0.55, "assumed"),
    ("possible", 0.55, "assumed"),
    ("wouldn't be surprised", 0.60, "assumed"),
    # Plain future tense is a flat statement, not a hedge.
    ("will", PLAIN, "assumed: plain statement"),
    ("won't", PLAIN, "assumed: plain statement"),
    ("going to", PLAIN, "assumed: plain statement"),
    ("gonna", PLAIN, "assumed: plain statement"),
]

# Longest phrases first, so "highly unlikely" wins over "unlikely" and
# "probably not" over "probably".
# A trailing * matches any ending ("doubt*" covers "doubtful"); other phrases must
# be whole words, so "bet" doesn't match "between".
_PATTERNS = [(re.compile(r"(?<![a-z])" + re.escape(p.rstrip("*")) + ("" if p.endswith("*") else r"(?![a-z])")), prob, p)
             for p, prob, _ in sorted(TABLE, key=lambda t: -len(t[0]))]


def confidence(hedge_phrase):
    """Probability (0.5-0.99) the author gives their own stance, from their exact words."""
    text = (hedge_phrase or "").lower().replace("’", "'").strip()
    if not text:
        return PLAIN
    for pattern, prob, _ in _PATTERNS:
        if pattern.search(text):
            return prob
    return UNKNOWN
