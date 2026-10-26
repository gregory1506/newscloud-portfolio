"""
Deeper NLP analysis module for NewsCloud scorer.

Computes emotional profile, entity categorization, topic scores,
and lexical diversity stats from a word frequency dictionary.

Designed to be imported by functions/scorer/main.py with zero
external dependencies beyond Python stdlib.
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# NRC-style Emotion Lexicon — maps words to emotion categories
# Each word can belong to multiple emotions (e.g. "fire" → anger, fear)
# ---------------------------------------------------------------------------
EMOTION_LEXICON: dict[str, set[str]] = {}

_emotion_map: dict[str, list[str]] = {
    "anger": [
        "fire", "killed", "crash", "fraud", "guilty", "accused",
        "violence", "chaotic", "banned", "ban", "faced", "massive",
        "attack", "murder", "murdered", "shooting", "riot", "clash",
        "explosion", "scandal", "corruption", "abuse", "protest",
        "arrested", "charged", "lawsuit", "strike", "layoff", "layoffs",
        "war", "siege", "hostage", "deficit", "inflation",
    ],
    "fear": [
        "killed", "crash", "fraud", "guilty", "accused", "violence",
        "chaotic", "sinkhole", "crashed", "massive", "fire",
        "disaster", "crisis", "tragedy", "catastrophe", "collapse",
        "attack", "murder", "murdered", "death", "deaths", "fatal",
        "shooting", "explosion", "flood", "earthquake", "storm",
        "drought", "recession", "bankruptcy", "hostage", "siege",
        "threat", "risk", "concern",
    ],
    "sadness": [
        "killed", "guilty", "crash", "violence", "sinkhole",
        "crashed", "faced", "ends", "lost", "loss", "decline",
        "tragedy", "catastrophe", "murder", "murdered", "death",
        "deaths", "fatal", "bankruptcy", "layoff", "layoffs",
        "collapse", "disaster",
    ],
    "disgust": [
        "fraud", "guilty", "accused", "violence", "scandal",
        "corruption", "abuse", "riot", "murder", "crisis",
    ],
    "surprise": [
        "crash", "sinkhole", "massive", "chaotic", "crashed",
        "impacted", "billionaire", "breakthrough", "historic",
        "milestone", "collapse", "explosion", "earthquake",
    ],
    "joy": [
        "star", "young", "graduates", "jingle", "art", "show",
        "book", "sale", "earnings", "results", "future",
        "prepares", "readiness", "excellent", "outstanding",
        "wonderful", "spectacular", "brilliant", "amazing",
        "fantastic", "superb", "triumph", "victory", "celebrate",
        "peace", "rescue", "freed", "acquitted", "good", "great",
        "success", "win", "won", "award", "benefit", "improve",
        "improved", "safe", "help", "hope", "positive", "strong",
        "progress", "opportunity", "boost", "growth", "recovery",
        "agreement", "approved", "saved", "relief", "support",
    ],
    "trust": [
        "police", "attorney", "general", "mayor", "lawmakers",
        "government", "representative", "elected", "deputy",
        "rules", "policy", "university", "school", "campus",
        "court", "approved", "agreement", "peace", "rescue",
        "safe", "help", "support", "elected", "progress",
        "recovery", "milestone", "historic",
    ],
    "anticipation": [
        "future", "prepares", "readiness", "bid", "campaign",
        "draft", "search", "running", "takes", "take",
        "ahead", "annual", "weekend", "returns", "goes",
        "election", "elections", "vote", "voting", "ballot",
        "primary", "primaries", "poll", "polls", "opportunity",
        "progress", "growth", "breakthrough", "milestone",
    ],
}

for emotion, words in _emotion_map.items():
    for w in words:
        EMOTION_LEXICON.setdefault(w, set()).add(emotion)

EMOTIONS_ORDERED = [
    "anger", "fear", "trust", "anticipation",
    "joy", "sadness", "surprise", "disgust",
]

# ---------------------------------------------------------------------------
# Entity categorization — known person/place/org names
# Frequencies arrive lowercased, so all entries here are lowercase.
# ---------------------------------------------------------------------------
KNOWN_PERSONS: set[str] = {
    "trump", "biden", "harris", "newsom", "gavin", "schlossberg",
    "myers", "dokoupil", "jack", "thomas", "tony", "kean", "aiden",
    "giuliani", "penn", "desantis", "haley", "ramaswamy", "christie",
    "scott", "hutchinson", "burgum", "elders", "fauci", "pelosi",
    "schumer", "mcconnell", "mccarthy", "jeffries", "ocasio",
    "cortez", "sanders", "warren", "buttigieg", "klobuchar",
    "cruz", "rubio", "hawley", "cotton", "greene", "boebert",
    "gaetz", "jordan", "cheney", "kinzinger", "romney", "murkowski",
    "adams", "hochul", "baseman", "lightfoot", "whitmer",
    "abbott", "dewald",
}

KNOWN_PLACES: set[str] = {
    "california", "brooklyn", "bronx", "hollywood", "broadway",
    "los", "angeles", "china", "jersey", "riverside", "east",
    "bay", "island", "town", "village", "eton", "neue",
    "manhattan", "queens", "staten", "longisland", "buffalo",
    "albany", "syracuse", "rochester", "chicago", "houston",
    "phoenix", "philadelphia", "sanantonio", "sandiego", "dallas",
    "austin", "jacksonville", "fortworth", "columbus", "charlotte",
    "indianapolis", "sanfrancisco", "seattle", "denver", "nashville",
    "oklahoma", "elpaso", "washington", "boston", "memphis",
    "portland", "louisville", "baltimore", "milwaukee", "albuquerque",
    "tucson", "fresno", "sacramento", "mesa", "atlanta", "kansascity",
    "omaha", "colorado", "miami", "oakland", "tampa", "minneapolis",
    "cleveland", "pittsburgh", "cincinnati", "newark", "orlando",
    "detroit", "arizona", "nevada", "georgia", "michigan",
    "pennsylvania", "wisconsin", "northcarolina", "ohio", "florida",
    "texas", "newyork", "newjersey", "virginia", "massachusetts", "indiana", "tennessee", "missouri", "maryland",
    "minnesota", "alabama", "kentucky", "oregon",
    "connecticut", "utah", "iowa", "arkansas",
    "mississippi", "kansas", "newmexico", "nebraska", "westvirginia",
    "idaho", "hawaii", "maine", "newhampshire", "rhodeisland",
    "montana", "delaware", "southdakota", "northdakota", "alaska",
    "vermont", "wyoming", "southcarolina", "louisiana",
    "ukraine", "russia", "taiwan", "israel", "gaza",
    "iran", "iraq", "japan", "korea", "germany", "france", "uk",
    "britain", "canada", "mexico", "afghanistan", "syria",
}

KNOWN_ORGANIZATIONS: set[str] = {
    "cbs", "nbc", "abc", "fox", "cnn", "msnbc", "bbc", "npr",
    "nytimes", "washingtonpost", "wsj", "politico", "ap",
    "reuters", "bloomberg", "forbes", "axios", "buzzfeed",
    "vice", "vox", "thehill", "theguardian",
    "nasdaq", "nyse", "dowjones", "sec",
    "lirr", "mta", "chabad", "knicks", "nba", "nfl", "mlb", "nhl",
    "google", "meta", "apple", "amazon", "microsoft", "tesla",
    "spacex", "openai", "twitter", "facebook", "instagram",
    "youtube", "tiktok", "netflix", "disney", "walmart",
    "gop", "dnc", "rnc", "un", "nato", "fbi", "cia", "nsa",
    "dhs", "irs", "epa", "fda", "hhs", "dod", "state", "doj",
    "supremecourt", "congress", "senate", "house", "whitehouse",
    "pentagon", "navy", "army", "marines", "airforce",
}

# ---------------------------------------------------------------------------
# Topic clusters — keyword-based scoring aligned with ISSUE_TAXONOMY
# ---------------------------------------------------------------------------
TOPIC_CLUSTERS: dict[str, set[str]] = {
    "Economy": {
        "economy", "economic", "inflation", "tariff", "tariffs",
        "jobs", "job", "wages", "wage", "business", "businesses",
        "market", "markets", "budget", "budgets", "tax", "taxes",
        "housing", "rent", "mortgage", "mortgages", "prices",
        "spending", "manufacturing", "labor", "labour", "union",
        "unions", "earnings", "nasdaq", "stock", "stocks",
        "recession", "deficit", "debt", "bankruptcy",
    },
    "Immigration": {
        "immigration", "immigrant", "immigrants", "migrant", "migrants",
        "asylum", "visa", "visas", "refugee", "refugees", "citizenship",
        "undocumented", "sanctuary", "illegal",
    },
    "Border Security": {
        "border", "wall", "deportation", "deportations", "deport",
        "cartel", "cartels", "smuggling", "checkpoint", "customs",
    },
    "Crime": {
        "crime", "police", "shooting", "shootings", "murder", "murdered",
        "killed", "arrest", "arrested", "assault", "robbery", "gun", "guns",
        "fentanyl", "drug", "drugs", "trafficking", "prison", "sentenced",
        "fraud", "guilty", "violence", "accused", "theft", "burglary",
        "criminal", "criminals", "prosecutor", "indicted", "convicted",
    },
    "Education": {
        "education", "school", "schools", "student", "students",
        "teacher", "teachers", "classroom", "classrooms", "district",
        "districts", "college", "colleges", "university", "universities",
        "campus", "curriculum", "graduates", "graduation",
    },
    "Abortion": {
        "abortion", "abortions", "reproductive", "pregnancy",
        "pregnancies", "fetal", "fetus", "roe", "prolife", "prochoice",
        "planned", "parenthood",
    },
    "Elections": {
        "election", "elections", "vote", "votes", "voting", "voter",
        "voters", "ballot", "ballots", "campaign", "campaigns", "primary",
        "primaries", "poll", "polls", "legislature", "legislative",
        "governor", "senate", "house", "congress", "democrat", "democrats",
        "democratic", "republican", "republicans", "candidate",
        "candidates", "incumbent", "debate", "debates", "fundraising",
        "donor", "donors", "pac", "superpac",
    },
    "Disaster & Accidents": {
        "disaster", "crisis", "catastrophe", "tragedy", "collapse",
        "earthquake", "flood", "flooding", "hurricane", "tornado",
        "storm", "wildfire", "fire", "fires", "drought", "heatwave",
        "sinkhole", "crash", "crashed", "explosion", "fatal", "fatality",
        "emergency", "evacuation", "rescue", "firstresponder",
    },
    "Environment": {
        "environment", "environmental", "climate", "renewable", "emissions",
        "carbon", "pollution", "energy", "solar", "wind", "green",
        "sustainability", "conservation", "wildlife", "forest",
    },
    "Healthcare": {
        "healthcare", "health", "medicare", "medicaid", "hospital",
        "hospitals", "doctor", "doctors", "nurse", "nurses", "patient",
        "patients", "vaccine", "vaccines", "pandemic", "covid",
        "mentalhealth", "insurance", "pharmaceutical", "pharmaceuticals",
        "drug", "prescription",
    },
    "Infrastructure": {
        "infrastructure", "bridge", "bridges", "road", "roads", "highway",
        "highways", "expressway", "tunnel", "tunnels", "transit",
        "commute", "commuter", "rail", "railway", "lirr", "subway",
        "bus", "airport", "construction", "building", "buildings",
        "electrical", "power", "water", "internet", "broadband",
    },
    "Energy Independence": {
        "oil", "drilling", "pipeline", "fracking", "petroleum",
        "coal", "opec", "refinery",
    },
    "Religious Liberty": {
        "religious", "religion", "church", "churches", "faith",
        "christian", "prayer",
    },
}

# ---------------------------------------------------------------------------
# Analysis functions
# ---------------------------------------------------------------------------


def compute_emotional_profile(frequencies: dict[str, int]) -> dict[str, float]:
    """Compute NRC-style emotion magnitudes from word frequencies.

    Returns dict mapping emotion → weighted sum (frequency × presence).
    """
    emotion_scores: dict[str, float] = {emo: 0.0 for emo in EMOTIONS_ORDERED}
    for word, count in frequencies.items():
        word_lower = word.lower()
        if word_lower in EMOTION_LEXICON:
            for emotion in EMOTION_LEXICON[word_lower]:
                emotion_scores[emotion] += count
    return emotion_scores


def compute_entity_profile(frequencies: dict[str, int]) -> dict[str, dict[str, int]]:
    """Categorize known entities by type.

    Returns {"persons": {name: count}, "places": {name: count}, "organizations": {name: count}}.
    """
    entities: dict[str, dict[str, int]] = {
        "persons": {},
        "places": {},
        "organizations": {},
    }
    for word, count in frequencies.items():
        word_lower = word.lower()
        if word_lower in KNOWN_PERSONS:
            entities["persons"][word_lower] = entities["persons"].get(word_lower, 0) + count
        if word_lower in KNOWN_PLACES:
            entities["places"][word_lower] = entities["places"].get(word_lower, 0) + count
        if word_lower in KNOWN_ORGANIZATIONS:
            entities["organizations"][word_lower] = entities["organizations"].get(word_lower, 0) + count
    # Sort each category by count descending
    for cat in entities:
        entities[cat] = dict(
            sorted(entities[cat].items(), key=lambda x: -x[1])
        )
    return entities


def compute_topic_scores(frequencies: dict[str, int]) -> dict[str, float]:
    """Score each topic cluster by summing keyword frequencies.

    Returns dict mapping topic label → total frequency score.
    """
    scores: dict[str, float] = {}
    for topic, keywords in TOPIC_CLUSTERS.items():
        score = sum(count for word, count in frequencies.items() if word.lower() in keywords)
        if score > 0:
            scores[topic] = round(score, 1)
    return dict(sorted(scores.items(), key=lambda x: -x[1]))


def compute_lexical_stats(frequencies: dict[str, int]) -> dict[str, float]:
    """Compute lexical diversity / dispersion metrics.

    Returns dict with ttr, entropy, gini, top20_coverage_pct, total_tokens, unique_types.
    """
    if not frequencies:
        return {
            "total_tokens": 0,
            "unique_types": 0,
            "ttr": 0.0,
            "entropy": 0.0,
            "gini": 0.0,
            "top20_coverage_pct": 0.0,
        }

    total_tokens = sum(frequencies.values())
    unique_types = len(frequencies)

    # Type-Token Ratio
    ttr = round(unique_types / total_tokens, 4) if total_tokens else 0.0

    # Shannon Entropy
    entropy = -sum(
        (f / total_tokens) * math.log2(f / total_tokens)
        for f in frequencies.values()
    )
    entropy = round(entropy, 2)

    # Top-20 coverage percentage
    sorted_freqs = sorted(frequencies.values(), reverse=True)
    top20_sum = sum(sorted_freqs[:20])
    top20_coverage_pct = round(top20_sum / total_tokens * 100, 1)

    # Gini coefficient
    n = len(sorted_freqs)
    total = sum(sorted_freqs)
    gini_numer = 0
    for i, f in enumerate(sorted_freqs):
        gini_numer += (i + 1) * f
    if n > 0 and total > 0:
        gini = round((2 * gini_numer) / (n * total) - (n + 1) / n, 4)
    else:
        gini = 0.0

    return {
        "total_tokens": total_tokens,
        "unique_types": unique_types,
        "ttr": ttr,
        "entropy": entropy,
        "gini": gini,
        "top20_coverage_pct": top20_coverage_pct,
    }


def analyze_frequencies(frequencies: dict[str, int]) -> dict[str, object]:
    """Run all deeper NLP analyses on a frequency dict.

    Returns a dict suitable for upserting into regional_sentiment columns:
        emotional_profile, entity_profile, topic_scores, lexical_stats
    """
    return {
        "emotional_profile": compute_emotional_profile(frequencies),
        "entity_profile": compute_entity_profile(frequencies),
        "topic_scores": compute_topic_scores(frequencies),
        "lexical_stats": compute_lexical_stats(frequencies),
    }
