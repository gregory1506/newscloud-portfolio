"""Term-level coverage valence for the Trinidad conversation map.

This mirrors the general sentiment vocabulary used by the scorer, but lives in
the gatherer deployment package so article-level term metrics can carry their
own reproducible horizontal-axis value.
"""

SENTIMENT_LEXICON: dict[str, float] = {
    "excellent": 5, "outstanding": 5, "wonderful": 5, "spectacular": 5, "brilliant": 5,
    "amazing": 4, "fantastic": 4, "superb": 4, "triumph": 4, "victory": 4,
    "celebrate": 4, "peace": 4, "rescue": 4, "freed": 4, "acquitted": 4,
    "good": 3, "great": 3, "success": 3, "win": 3, "won": 3, "award": 3,
    "benefit": 2, "improve": 2, "improved": 2, "safe": 2, "help": 2, "hope": 2,
    "positive": 2, "strong": 2, "progress": 2, "opportunity": 2, "boost": 2,
    "growth": 3, "recovery": 3, "agreement": 2, "approved": 2, "saved": 2,
    "historic": 2, "milestone": 2, "breakthrough": 3, "relief": 2, "support": 1,
    "concern": -1, "difficult": -1, "fall": -1, "cut": -1, "drop": -1,
    "delay": -1, "slow": -1, "struggle": -2, "challenge": -1, "risk": -2,
    "loss": -2, "fail": -2, "failed": -2, "hurt": -2, "decline": -2,
    "problem": -2, "threat": -2, "layoff": -3, "layoffs": -3, "strike": -2,
    "arrested": -3, "charged": -2, "charges": -2, "lawsuit": -2, "trial": -1,
    "bad": -3, "poor": -2, "disaster": -5, "crisis": -4, "tragedy": -5,
    "catastrophe": -5, "collapse": -4, "attack": -3, "murder": -5, "murdered": -5,
    "killed": -4, "dead": -4, "death": -4, "deaths": -4, "fatal": -4,
    "war": -4, "violence": -4, "shooting": -4, "crash": -3, "explosion": -4,
    "scandal": -4, "corruption": -4, "fraud": -4, "abuse": -4,
    "fire": -2, "flood": -3, "earthquake": -3, "storm": -2, "drought": -3,
    "recession": -4, "deficit": -3, "debt": -2, "bankruptcy": -4, "inflation": -3,
    "riot": -4, "protest": -2, "clash": -3, "siege": -4, "hostage": -4,
    "guilty": -3, "convicted": -4, "sentenced": -3, "indicted": -3,
}


def normalized_term_valence(term: str) -> float:
    """Return the lexicon score on the map's -1..1 horizontal scale."""
    return float(SENTIMENT_LEXICON.get(term.lower(), 0.0)) / 5.0
