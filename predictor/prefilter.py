"""Free first pass: keep only comments with prediction-sounding words.

Measured on the 504 unfiltered pilot comments (Claude's extraction as the reference):
- BROAD keeps 37% of comments and 74 of the 76 that contain a forecast (97%).
- STRICT keeps 20% and 57 of 76 (75%). Among comments that pass BROAD it keeps
  57% and catches 81%, beating the local phi3:mini model as a screen.

The panel funnel uses STRICT: its per-person cap means heavy posters hit the cap
either way, so the stricter filter fills the cap with denser, more forecast-rich
comments. See PLAN.md, Findings.
"""

import re

STRICT = re.compile(
    r"\b(will|won't|wont|gonna|going to|bet|predict\w*|calling it|mark my words|no way|"
    r"probably|likely|chance|odds|doubt|guarantee\w*|expect\w*|bound to|about to)\b|\w'll\b", re.I)

BROAD = re.compile(
    r"\b(will|won't|wont|gonna|going to|bet|predict\w*|calling it|mark my words|no way|"
    r"probably|likely|unlikely|chance|odds|doubt|guarantee\w*|expect\w*|bound to|about to|"
    r"might|could|would|if|unrealistic|i don't see|ain't happening|certain)\b|\w'll\b", re.I)


def passes(body, pattern=STRICT):
    # Phone keyboards type curly apostrophes ("won’t"), which a plain ' wouldn't match.
    return bool(pattern.search((body or "").replace("’", "'")))
