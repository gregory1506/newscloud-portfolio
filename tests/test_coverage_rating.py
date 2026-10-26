"""Unit tests for the deterministic Coverage Rating module."""

from __future__ import annotations

import pytest

from shared.coverage_rating import (
    COVERAGE_RATING_VERSION,
    WEIGHT_PRESETS,
    band_for_score,
    band_party,
    coverage_component,
    incumbency_component,
    money_component,
    normalize_weights,
    rate_race,
)


@pytest.mark.unit
def test_band_for_score_boundaries():
    assert band_for_score(0.0) == "Safe D"
    assert band_for_score(20.0) == "Safe D"
    assert band_for_score(20.1) == "Likely D"
    assert band_for_score(35.0) == "Likely D"
    assert band_for_score(45.0) == "Lean D"
    assert band_for_score(45.1) == "Tossup"
    assert band_for_score(55.0) == "Tossup"
    assert band_for_score(55.1) == "Lean R"
    assert band_for_score(65.0) == "Lean R"
    assert band_for_score(80.0) == "Likely R"
    assert band_for_score(80.1) == "Safe R"
    assert band_for_score(100.0) == "Safe R"


@pytest.mark.unit
def test_band_party_mapping():
    assert band_party("Safe D") == "D"
    assert band_party("Lean D") == "D"
    assert band_party("Tossup") == "TOSS"
    assert band_party("Likely R") == "R"
    assert band_party("Safe R") == "R"


@pytest.mark.unit
def test_coverage_component_direction_and_clamping():
    assert coverage_component(2.5) == pytest.approx(0.0)
    assert coverage_component(0.0) == pytest.approx(-1.0)
    assert coverage_component(5.0) == pytest.approx(1.0)
    assert coverage_component(-3.0) == pytest.approx(-1.0)
    assert coverage_component(9.0) == pytest.approx(1.0)
    assert coverage_component(None) is None


@pytest.mark.unit
def test_money_component_direction_and_empty():
    assert money_component(1_000_000, 1_000_000) == pytest.approx(0.0)
    assert money_component(0, 1_000_000) == pytest.approx(1.0)
    assert money_component(1_000_000, 0) == pytest.approx(-1.0)
    assert money_component(0, 0) is None
    assert money_component(None, None) is None


@pytest.mark.unit
def test_incumbency_component():
    assert incumbency_component("R") == 1.0
    assert incumbency_component("Republican") == 1.0
    assert incumbency_component("D") == -1.0
    assert incumbency_component("DEM") == -1.0
    assert incumbency_component(None) == 0.0
    assert incumbency_component("") == 0.0
    assert incumbency_component("I") == 0.0


@pytest.mark.unit
def test_rate_race_safe_democratic_example():
    result = rate_race(
        leaning_score=1.0,
        dem_money=1_000_000,
        rep_money=200_000,
        incumbent_party="D",
        source_count=5,
        fec_coverage=1.0,
    )
    assert result.rating_band == "Safe D"
    assert result.rating_score == pytest.approx(14.67, abs=0.05)
    assert result.confidence == pytest.approx(1.0)
    assert result.methodology_version == COVERAGE_RATING_VERSION
    assert result.available == {"coverage": True, "money": True, "incumbency": True}


@pytest.mark.unit
def test_rate_race_tossup_example():
    result = rate_race(
        leaning_score=2.6,
        dem_money=1_000_000,
        rep_money=900_000,
        incumbent_party=None,
        source_count=4,
        fec_coverage=1.0,
    )
    assert result.rating_band == "Tossup"
    assert result.rating_score == pytest.approx(49.75, abs=0.1)


@pytest.mark.unit
def test_rate_race_ignores_money_without_fec_coverage():
    with_coverage = rate_race(
        leaning_score=4.0,
        dem_money=5_000_000,
        rep_money=0,
        incumbent_party="D",
        source_count=5,
        fec_coverage=1.0,
    )
    without_coverage = rate_race(
        leaning_score=4.0,
        dem_money=5_000_000,
        rep_money=0,
        incumbent_party="D",
        source_count=5,
        fec_coverage=0.0,
    )
    assert without_coverage.available["money"] is False
    # The absent money signal renormalizes weights across coverage + incumbency
    # instead of counting as a neutral zero.
    assert without_coverage.rating_score != with_coverage.rating_score
    assert without_coverage.rating_score > 50  # still R-favorable from coverage


@pytest.mark.unit
def test_rate_race_renormalizes_when_money_missing():
    result = rate_race(
        leaning_score=5.0,
        incumbent_party=None,
        source_count=5,
        fec_coverage=0.0,
    )
    assert result.available["money"] is False
    assert result.available["incumbency"] is False
    # Coverage-only extreme: raw = 100 from the one available component, then
    # shrunk toward 50 because only 40% of the input weight is present.
    assert result.rating_score == pytest.approx(70.0)
    assert result.rating_band == "Likely R"


@pytest.mark.unit
def test_rate_race_thin_coverage_lowers_confidence():
    thin = rate_race(
        leaning_score=1.0,
        incumbent_party=None,
        source_count=0,
        fec_coverage=0.0,
    )
    strong = rate_race(
        leaning_score=1.0,
        incumbent_party=None,
        source_count=5,
        fec_coverage=0.0,
    )
    assert thin.confidence < strong.confidence
    # Thin evidence pulls the same signal toward the tossup midpoint.
    assert abs(thin.rating_score - 50) < abs(strong.rating_score - 50)


@pytest.mark.unit
def test_rate_race_no_inputs_is_tossup():
    result = rate_race(
        leaning_score=None,
        dem_money=None,
        rep_money=None,
        incumbent_party=None,
        source_count=0,
        fec_coverage=0.0,
    )
    assert result.rating_band == "Tossup"
    assert result.rating_score == 50.0
    assert result.confidence == 0.0


@pytest.mark.unit
def test_incumbency_alone_does_not_produce_a_band():
    """A known holder is an input, not evidence: no coverage, no band."""
    result = rate_race(
        leaning_score=None,
        dem_money=None,
        rep_money=None,
        incumbent_party="R",
        source_count=0,
        fec_coverage=0.0,
    )
    assert result.rating_band == "Tossup"
    assert result.rating_score == 50.0
    assert result.confidence == 0.0
    assert result.available == {"coverage": False, "money": False, "incumbency": True}
    assert result.components["incumbency"] == 1.0


@pytest.mark.unit
def test_incumbency_tilts_a_race_that_has_evidence():
    kwargs = dict(leaning_score=1.0, source_count=3, fec_coverage=0.0)
    with_incumbent = rate_race(incumbent_party="D", **kwargs)
    without_incumbent = rate_race(incumbent_party=None, **kwargs)
    # Coverage already leans Democratic; a Democratic incumbent deepens it.
    assert with_incumbent.rating_score < without_incumbent.rating_score < 50
    assert with_incumbent.available["incumbency"] is True
    assert without_incumbent.available["incumbency"] is False


@pytest.mark.unit
def test_rating_is_deterministic():
    kwargs = dict(
        leaning_score=3.1,
        dem_money=400_000,
        rep_money=900_000,
        incumbent_party="R",
        source_count=3,
        fec_coverage=1.0,
    )
    assert rate_race(**kwargs).as_dict() == rate_race(**kwargs).as_dict()


@pytest.mark.unit
def test_normalize_weights_validates():
    assert normalize_weights(None) == {"coverage": 0.4, "money": 0.4, "incumbency": 0.2}
    assert normalize_weights({"coverage": 2, "money": 1, "incumbency": 1}) == {
        "coverage": 0.5, "money": 0.25, "incumbency": 0.25,
    }
    with pytest.raises(ValueError):
        normalize_weights({"coverage": 1, "money": 1})
    with pytest.raises(ValueError):
        normalize_weights({"coverage": -1, "money": 1, "incumbency": 1})
    with pytest.raises(ValueError):
        normalize_weights({"coverage": 0, "money": 0, "incumbency": 0})


@pytest.mark.unit
def test_weight_presets_change_the_composite():
    kwargs = dict(
        leaning_score=4.0, dem_money=2_000_000, rep_money=1_000_000,
        incumbent_party=None, source_count=5, fec_coverage=1.0,
    )
    balanced = rate_race(**kwargs, weights=WEIGHT_PRESETS["balanced"]).rating_score
    coverage_first = rate_race(**kwargs, weights=WEIGHT_PRESETS["coverage_first"]).rating_score
    money_first = rate_race(**kwargs, weights=WEIGHT_PRESETS["money_first"]).rating_score
    # Coverage points toward R, money toward D, so weight order is monotonic.
    assert coverage_first > balanced > money_first
    # Default (no weights) equals the balanced preset.
    assert rate_race(**kwargs).rating_score == balanced


@pytest.mark.unit
def test_default_weights_are_reported():
    result = rate_race(leaning_score=2.5, source_count=3)
    assert result.weights == {"coverage": 0.4, "money": 0.4, "incumbency": 0.2}
