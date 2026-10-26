"""Quality bar for a district corpus, so a thin source cannot ship silently.

A district's coverage rating is only as good as the evidence behind it. Measured
on 2026-09-29 (`docs/research/2026-09-29-district-sourcing-plan.md`):

- a headline-only corpus (Google News RSS) kept 1-2 publishers of 6-9 seen and
  produced a leaning of exactly 2.50, the neutral midpoint;
- ``coverage_component(2.50)`` is ``0.0``, so the rating's coverage half
  contributed nothing and the band was decided by incumbency alone;
- a body-sized corpus from curated feeds cleared the bar (4 publishers, leaning
  3.90, coverage component +0.56).

So the values below are the difference between a rating that measures coverage and
one that merely looks like it does. The publisher floor matches the convention
already used for the gatherer's fallback acceptance
(``GEMINI_FALLBACK_DISTINCT_SOURCE_FLOOR``).
"""

from __future__ import annotations

from typing import Any, Iterable

MIN_DISTINCT_PUBLISHERS = 2
MIN_SUPPORTING_HEADLINES = 2
NEUTRAL_LEANING = 2.5
MIN_LEANING_DEVIATION = 0.25


def assess_corpus(
    supporting_headlines: Iterable[dict[str, Any]],
    *,
    min_publishers: int = MIN_DISTINCT_PUBLISHERS,
    min_headlines: int = MIN_SUPPORTING_HEADLINES,
) -> dict[str, Any]:
    """Judge whether a corpus can support a coverage claim.

    Returns the counts and whether they clear the bar. Callers log the result;
    nothing here decides what to publish.
    """
    headlines = [h for h in supporting_headlines if h]
    publishers = {
        str(h.get("source_name")).strip()
        for h in headlines
        if str(h.get("source_name") or "").strip()
    }
    ok = len(headlines) >= min_headlines and len(publishers) >= min_publishers
    return {
        "supporting_headline_count": len(headlines),
        "distinct_publisher_count": len(publishers),
        "publishers": sorted(publishers),
        "min_publishers": min_publishers,
        "min_headlines": min_headlines,
        "ok": ok,
    }


def assess_leaning(
    leaning_score: float | None,
    *,
    neutral: float = NEUTRAL_LEANING,
    min_deviation: float = MIN_LEANING_DEVIATION,
) -> dict[str, Any]:
    """Judge whether a leaning is far enough from the midpoint to mean anything.

    ``coverage_component(neutral)`` is exactly ``0.0``, so a corpus that cannot
    move the leaning has no coverage signal to contribute even though its rating
    still renders.
    """
    if leaning_score is None:
        return {"leaning_score": None, "deviation": None, "min_deviation": min_deviation, "ok": False}
    deviation = abs(float(leaning_score) - neutral)
    return {
        "leaning_score": float(leaning_score),
        "deviation": deviation,
        "min_deviation": min_deviation,
        "ok": deviation >= min_deviation,
    }
