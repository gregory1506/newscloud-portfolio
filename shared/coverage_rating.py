"""Deterministic Coverage Rating for the NewsCloud Race Board.

Version: ``coverage-rating-v1``

A race is placed on a neutral 0-100 axis:

    0   = strongest Democratic position
    50  = tossup
    100 = strongest Republican position

Three signed components, each in ``[-1, 1]``, are combined with documented
weights:

    coverage   = (leaning_score - 2.5) / 2.5       # + toward R
    money      = (rep_money - dem_money) / total   # + toward R
    incumbency = +1 R incumbent, -1 D incumbent, 0 open/unknown

Weights are renormalized over the components that are actually available, so a
missing money signal (no FEC coverage) does not silently count as neutral.
Confidence (source breadth and FEC coverage) pulls the score toward 50.

A band needs at least one **evidence** component — coverage or money. Incumbency
is a structural fact about the seat, not monitored coverage or campaign finance,
so it tilts a race that already has evidence and is reported as an input in its
own right; on its own it never produces a band.

The output is a **coverage rating band**, not a win probability. This module
never produces or implies a probability, forecast, or electoral outcome. Bands
describe where monitored coverage and public campaign finance are running.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

COVERAGE_RATING_VERSION = "coverage-rating-v1"

BASE_SCORE = 50.0
RATING_WEIGHTS: dict[str, float] = {
    "coverage": 0.4,
    "money": 0.4,
    "incumbency": 0.2,
}

# One source for every Python surface that paints a band (the race pages and the
# board email). The board's client-side map keeps its own copy, since it is served
# as static JavaScript.
BAND_COLORS: dict[str, str] = {
    "Safe D": "#123c74",
    "Likely D": "#1c58a6",
    "Lean D": "#6a97d6",
    "Tossup": "#9b84bd",
    "Lean R": "#d98a8a",
    "Likely R": "#ab272c",
    "Safe R": "#78191d",
}

# Transparent, reader-selectable weight presets (Plan B). The default remains
# "balanced"; presets only change how the same inputs are combined.
WEIGHT_PRESETS: dict[str, dict[str, float]] = {
    "balanced": dict(RATING_WEIGHTS),
    "coverage_first": {"coverage": 0.6, "money": 0.3, "incumbency": 0.1},
    "money_first": {"coverage": 0.3, "money": 0.6, "incumbency": 0.1},
}


def normalize_weights(weights: dict | None) -> dict[str, float]:
    """Validate and normalize component weights to sum to 1."""
    if weights is None:
        return dict(RATING_WEIGHTS)
    if set(weights) != set(RATING_WEIGHTS):
        raise ValueError(f"weights must define exactly {sorted(RATING_WEIGHTS)}")
    cleaned = {name: float(value) for name, value in weights.items()}
    if any(value < 0 for value in cleaned.values()):
        raise ValueError("weights must be non-negative")
    total = sum(cleaned.values())
    if total <= 0:
        raise ValueError("weights must sum to a positive number")
    return {name: value / total for name, value in cleaned.items()}

# Source breadth that earns full coverage confidence (mirrors the party scorer:
# 3 distinct sources == full confidence, fewer scale linearly).
MIN_COVERAGE_SOURCES_FOR_FULL_CONFIDENCE = 3

# Ascending upper bounds. A score at or below the bound takes that band.
# 45.0 -> "Lean D", just above -> "Tossup"; 55.0 -> "Tossup".
RATING_BANDS: tuple[tuple[float, str], ...] = (
    (20.0, "Safe D"),
    (35.0, "Likely D"),
    (45.0, "Lean D"),
    (55.0, "Tossup"),
    (65.0, "Lean R"),
    (80.0, "Likely R"),
    (100.0, "Safe R"),
)

_D_BANDS = frozenset({"Safe D", "Likely D", "Lean D"})
_R_BANDS = frozenset({"Safe R", "Likely R", "Lean R"})


@dataclass(frozen=True)
class RatingResult:
    """A single race's rating for one date."""

    rating_score: float
    rating_band: str
    confidence: float
    components: dict[str, float | None]
    available: dict[str, bool]
    weights: dict[str, float]
    methodology_version: str

    def as_dict(self) -> dict:
        return asdict(self)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def band_for_score(score: float) -> str:
    """Return the plain-language band for a 0-100 rating score."""
    for bound, label in RATING_BANDS:
        if score <= bound:
            return label
    return RATING_BANDS[-1][1]


def band_party(band: str) -> str:
    """Return ``"D"``, ``"R"``, or ``"TOSS"`` for map coloring."""
    if band in _D_BANDS:
        return "D"
    if band in _R_BANDS:
        return "R"
    return "TOSS"


def coverage_component(leaning_score: float | None) -> float | None:
    """Signed coverage direction. Positive is toward the Republican position.

    ``leaning_score`` is the NewsCloud 0-5 language-tilt measure (0 far left,
    2.5 neutral, 5 far right). Returns None when leaning is unmeasured
    (non-U.S. regions or missing data).
    """
    if leaning_score is None:
        return None
    return _clamp((float(leaning_score) - 2.5) / 2.5, -1.0, 1.0)


def money_component(dem_money: float | None, rep_money: float | None) -> float | None:
    """Signed money advantage. Positive is toward the Republican position.

    Returns None when there is no measurable money on either side, so the
    caller renormalizes rather than treating absence as a neutral zero.
    """
    dem = max(0.0, float(dem_money or 0.0))
    rep = max(0.0, float(rep_money or 0.0))
    total = dem + rep
    if total <= 0:
        return None
    return _clamp((rep - dem) / total, -1.0, 1.0)


def incumbency_component(incumbent_party: str | None) -> float:
    """+1 for a Republican incumbent, -1 for a Democrat, 0 for open/unknown."""
    if not incumbent_party:
        return 0.0
    party = str(incumbent_party).strip().upper()
    if party.startswith("R"):
        return 1.0
    if party.startswith("D"):
        return -1.0
    return 0.0


def _coverage_confidence(source_count: int | None) -> float:
    if source_count is None:
        return 0.0
    return _clamp(float(source_count) / MIN_COVERAGE_SOURCES_FOR_FULL_CONFIDENCE, 0.0, 1.0)


def rate_race(
    *,
    leaning_score: float | None,
    sentiment_score: float | None = None,
    dem_money: float | None = None,
    rep_money: float | None = None,
    incumbent_party: str | None = None,
    source_count: int | None = None,
    fec_coverage: float | None = None,
    weights: dict | None = None,
) -> RatingResult:
    """Rate one race deterministically.

    ``sentiment_score`` is accepted for continuity but does not set direction;
    tone is not partisan. It is reserved for a future confidence/uncertainty
    term. Money is only used when FEC coverage is present: no coverage, no read.
    """
    coverage = coverage_component(leaning_score)
    money = money_component(dem_money, rep_money) if (fec_coverage or 0) > 0 else None
    incumbency = incumbency_component(incumbent_party)
    resolved_weights = normalize_weights(weights)

    components: dict[str, float | None] = {
        "coverage": coverage,
        "money": money,
        "incumbency": incumbency,
    }
    available: dict[str, bool] = {
        "coverage": coverage is not None,
        "money": money is not None,
        # A known incumbent party (or an explicit open seat) is information;
        # an unknown seat is not, and must lower confidence.
        "incumbency": incumbent_party is not None,
    }
    confidences = {
        "coverage": _coverage_confidence(source_count),
        "money": 1.0 if money is not None else 0.0,
        "incumbency": 1.0,
    }

    active_weight = sum(resolved_weights[name] for name in components if available[name])
    evidence_weight = sum(
        resolved_weights[name] for name in ("coverage", "money") if available[name]
    )
    if active_weight <= 0 or evidence_weight <= 0:
        # A structural fact (who holds the seat) is neither monitored coverage
        # nor campaign finance, so it may tilt a rated race but must never
        # produce a band on its own: "Lean R" for a district with no coverage
        # and no finance read would claim more than the inputs support.
        return RatingResult(
            rating_score=BASE_SCORE,
            rating_band=band_for_score(BASE_SCORE),
            confidence=0.0,
            components=components,
            available=available,
            weights=dict(resolved_weights),
            methodology_version=COVERAGE_RATING_VERSION,
        )

    weighted_component = sum(
        resolved_weights[name] * float(components[name])
        for name in components
        if available[name]
    )
    raw_score = BASE_SCORE + 50.0 * (weighted_component / active_weight)

    # Confidence is measured against the FULL weight, not just the available
    # weight, so a missing component reduces confidence instead of silently
    # being treated as complete information.
    confidence = sum(
        resolved_weights[name] * confidences[name]
        for name in components
        if available[name]
    ) / sum(resolved_weights.values())
    rating_score = _clamp(BASE_SCORE + (raw_score - BASE_SCORE) * confidence, 0.0, 100.0)

    return RatingResult(
        rating_score=round(rating_score, 2),
        rating_band=band_for_score(rating_score),
        confidence=round(confidence, 3),
        components=components,
        available=available,
        weights=dict(resolved_weights),
        methodology_version=COVERAGE_RATING_VERSION,
    )
