"""Tests for the district corpus quality bar."""

from __future__ import annotations

import pytest

from shared.coverage_quality import (
    MIN_DISTINCT_PUBLISHERS,
    MIN_LEANING_DEVIATION,
    MIN_SUPPORTING_HEADLINES,
    assess_corpus,
    assess_leaning,
)


pytestmark = pytest.mark.unit


def _headline(publisher: str, title: str = "District race tightens") -> dict:
    return {"title": title, "excerpt": "…", "source_name": publisher, "provider": "rss"}


def test_a_single_publisher_is_not_enough_to_claim_coverage():
    """The 2026-09-29 measurement: Google News gave 1-2 publishers of 6-9 seen."""
    result = assess_corpus([_headline("Oshkosh Northwestern"), _headline("Oshkosh Northwestern")])

    assert result["distinct_publisher_count"] == 1
    assert result["supporting_headline_count"] == 2
    assert result["ok"] is False


def test_two_distinct_publishers_clear_the_bar():
    result = assess_corpus(
        [_headline("WFRV Local 5"), _headline("Wisconsin Examiner"), _headline("WPR")]
    )

    assert result["ok"] is True
    assert result["publishers"] == ["WFRV Local 5", "WPR", "Wisconsin Examiner"]


def test_one_headline_is_not_enough_even_from_a_real_publisher():
    result = assess_corpus([_headline("jsonline.com")])

    assert result["ok"] is False
    assert MIN_SUPPORTING_HEADLINES == 2


def test_blank_and_missing_publishers_do_not_count():
    result = assess_corpus(
        [_headline("  "), {"title": "no publisher"}, None, _headline("WTAQ")]
    )

    assert result["distinct_publisher_count"] == 1
    assert result["ok"] is False


def test_the_publisher_floor_matches_the_gatherer_fallback_convention():
    assert MIN_DISTINCT_PUBLISHERS == 2


def test_a_neutral_leaning_contributes_nothing_and_is_flagged():
    """`coverage_component(2.5)` is exactly 0.0, so 2.5 is a missing signal."""
    result = assess_leaning(2.5)

    assert result["deviation"] == 0.0
    assert result["ok"] is False
    assert MIN_LEANING_DEVIATION == 0.25


def test_a_leaning_off_the_midpoint_clears_the_bar():
    assert assess_leaning(3.9)["ok"] is True
    assert assess_leaning(1.9)["ok"] is True


def test_a_missing_leaning_is_never_acceptable():
    result = assess_leaning(None)

    assert result["ok"] is False
    assert result["deviation"] is None
