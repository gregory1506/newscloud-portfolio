"""Unit tests for the Race Board data exporter (pure functions)."""

from __future__ import annotations

import pytest

import scripts.export_race_board_data as board_export
from scripts.export_race_board_data import (
    band_counts,
    board_read,
    build_board_payload,
    candidate_key_for,
    changelog,
    exposure_tally,
    public_race_detail,
    public_race_row,
    sanitize_board_payload,
    sanitize_candidates,
    sanitize_evidence,
    trend_point,
)


def _row(race_id, band, score, label="Texas", chamber="senate", state="US-TX"):
    return {
        "race_id": race_id, "chamber": chamber, "state": state, "state_name": "Texas",
        "label": label, "rating_band": band, "rating_score": score, "source_count": 4,
    }


@pytest.mark.unit
def test_band_counts_and_tally():
    rows = [
        _row("a", "Safe D", 10), _row("b", "Tossup", 50),
        _row("c", "Tossup", 52), _row("d", "Lean R", 60),
    ]
    counts = band_counts(rows)
    assert counts["Tossup"] == 2
    assert counts["Safe D"] == 1
    assert counts["Safe R"] == 0
    tally = exposure_tally(rows)
    assert tally["seats"] == 4
    assert tally["contested"] == 3  # Lean D + Tossup + Lean R (2 tossup + 1 lean R)
    assert tally["bands"]["Tossup"] == 2


@pytest.mark.unit
def test_board_read_reports_direction_and_tossups():
    tally = exposure_tally([
        _row("a", "Safe R", 90), _row("b", "Likely R", 70), _row("c", "Tossup", 50),
    ])
    read = board_read("senate", tally)
    assert "Republican-ward" in read
    assert "3 Senate seats" in read
    assert "1 in the tossup band" in read
    assert "predict" not in read.lower()


@pytest.mark.unit
def test_board_read_even_split():
    tally = exposure_tally([_row("a", "Lean D", 40), _row("b", "Lean R", 60)])
    assert "split" in board_read("house", tally)


@pytest.mark.unit
def test_changelog_reports_band_movers():
    rows = [_row("a", "Tossup", 50), _row("b", "Safe D", 10)]
    prior = {"a": "Lean D", "b": "Safe D"}
    movers = changelog(rows, prior)
    assert len(movers) == 1
    assert movers[0]["race_id"] == "a"
    assert movers[0]["from_band"] == "Lean D"
    assert movers[0]["to_band"] == "Tossup"


@pytest.mark.unit
def test_trend_point_averages_scores():
    point = trend_point([_row("a", "Tossup", 50), _row("b", "Lean R", 60)])
    assert point["avg_score"] == pytest.approx(55.0)
    assert point["tossup"] == 1
    assert point["contested"] == 2


@pytest.mark.unit
def test_public_race_row_flags_thin_signal():
    race = {"race_id": "2026-HOU-TX-07", "chamber": "house", "state": "US-TX", "district": 7,
            "incumbent_party": "R"}
    row = public_race_row(race, {"rating_band": "Lean R", "rating_score": 58.5,
                                 "rating_confidence": 0.3, "fec_coverage": 1.0})
    assert row["label"] == "TX-07"
    assert row["rating_score"] == 58.5
    assert row["thin_signal"] is True


@pytest.mark.unit
def test_build_payload_and_sanitize_drops_private_fields():
    races = [
        {"race_id": "2026-SEN-TX", "chamber": "senate", "state": "US-TX", "district": None,
         "incumbent_party": "R"},
        {"race_id": "2026-HOU-TX-07", "chamber": "house", "state": "US-TX", "district": 7,
         "incumbent_party": None},
    ]
    snapshots = {
        "2026-SEN-TX": {"rating_band": "Lean R", "rating_score": 60.0, "rating_confidence": 1.0},
        "2026-HOU-TX-07": {"rating_band": "Tossup", "rating_score": 50.0, "rating_confidence": 0.4},
    }
    payload = build_board_payload(
        run_date="2026-09-19", races=races, snapshots_by_race=snapshots, prior_bands={},
    )
    assert set(payload["chambers"]) == {"senate", "house", "governor"}
    assert payload["chambers"]["senate"]["tally"]["seats"] == 1
    assert payload["chambers"]["governor"]["tally"]["seats"] == 0
    assert payload["chambers"]["senate"]["read"]

    dirty = build_board_payload(
        run_date="2026-09-19", races=races, snapshots_by_race=snapshots, prior_bands={},
    )
    dirty["chambers"]["senate"]["races"][0]["raw_score"] = 999
    clean = sanitize_board_payload(dirty)
    assert "raw_score" not in clean["chambers"]["senate"]["races"][0]


@pytest.mark.unit
def test_public_race_detail_whitelists_and_sanitizes():
    race = {"race_id": "2026-HOU-TX-07", "chamber": "house", "state": "US-TX",
            "district": 7, "incumbent_party": "R", "seat_status": "unknown"}
    snapshot = {
        "rating_band": "Lean R", "rating_score": 58.0, "rating_confidence": 0.9,
        "coverage_leaning": 3.4, "coverage_tone": 5.0, "ie_support": 100.0,
        "ie_oppose": 20.0, "fec_coverage": 1.0, "methodology_version": "coverage-rating-v1",
        "raw_score": 999,
    }
    detail = public_race_detail(
        race, snapshot,
        [{"candidate_name": "Jane Doe", "party": "REP", "ie_support_7d": 10, "ie_oppose_7d": 0}],
        [{"title": "Budget vote", "url": "https://x.com/a", "source_name": "Desk"}],
    )
    assert detail["slug"] == "tx-07"
    assert detail["label"] == "TX-07"
    assert detail["candidates"][0]["name"] == "Jane Doe"
    assert detail["evidence"][0]["url"] == "https://x.com/a"
    assert "raw_score" not in detail


@pytest.mark.unit
def test_sanitize_evidence_drops_bad_urls():
    out = sanitize_evidence([
        {"title": "bad", "url": "javascript:alert(1)"},
        {"title": "good", "url": "https://ok.example.com/story"},
    ])
    assert [row["url"] for row in out] == ["https://ok.example.com/story"]


@pytest.mark.unit
def test_sanitize_candidates_skips_blank_and_sorts_by_party():
    out = sanitize_candidates([
        {"candidate_name": "  ", "party": "DEM"},
        {"candidate_name": "Zed", "party": "REP"},
        {"candidate_name": "Amy", "party": "DEM"},
    ])
    assert [row["name"] for row in out] == ["Amy", "Zed"]


@pytest.mark.unit
def test_mover_significance_rewards_bigger_crossings():
    from scripts.export_race_board_data import mover_significance

    assert mover_significance("Lean R", "Lean D") > mover_significance("Lean R", "Tossup")
    assert mover_significance("Lean R", "Tossup") > mover_significance("Lean R", "Likely R")
    assert mover_significance("Lean R", "Lean R") == 0


@pytest.mark.unit
def test_changelog_ranks_by_significance_and_lead_names_the_mover():
    races = [
        {"race_id": "a", "chamber": "senate", "state": "US-GA", "district": None, "incumbent_party": "R"},
        {"race_id": "b", "chamber": "senate", "state": "US-ID", "district": None, "incumbent_party": "R"},
    ]
    snaps = {"a": {"rating_band": "Lean D", "source_count": 4},
             "b": {"rating_band": "Lean R", "source_count": 4}}
    board = build_board_payload(
        run_date="2026-09-20", races=races, snapshots_by_race=snaps,
        prior_bands={"a": "Lean R", "b": "Likely R"},
    )
    movers = board["chambers"]["senate"]["changelog"]
    # a crosses the midpoint (Lean R -> Lean D) and outranks b (Likely R -> Lean R).
    assert movers[0]["race_id"] == "a"
    assert movers[0]["toward"] == "D"
    assert "Georgia" in board["lead"] or "GA" in board["lead"]
    assert "Georgia moved toward Democrats" in board["lead"]
    assert "monitored seats to change bands" in board["lead"]
    assert "→" in board["subject"]


@pytest.mark.unit
def test_public_race_row_has_signal_requires_coverage_or_money():
    race = {"race_id": "2026-HOU-TX-07", "chamber": "house", "state": "US-TX",
            "district": 7, "incumbent_party": None}
    assert public_race_row(race, {"source_count": 3})["has_signal"] is True
    assert public_race_row(race, {"source_count": 1, "fec_coverage": 1.0})["has_signal"] is True
    assert public_race_row(race, {"source_count": 1, "fec_coverage": 0.0})["has_signal"] is False
    assert public_race_row(race, {})["has_signal"] is False




@pytest.mark.unit
def test_candidate_key_matches_how_ad_spend_rows_are_keyed():
    assert candidate_key_for({"chamber": "house", "state": "US-PA", "district": 7}) == "PA-07"
    assert candidate_key_for({"chamber": "senate", "state": "US-PA", "district": None}) == "PA"
    # Governors have no federal filings, so they must not borrow the Senate key.
    assert candidate_key_for({"chamber": "governor", "state": "US-PA", "district": None}) is None


def _snapshot(race_id: str, band: str, *, sources: int, fec: int = 0) -> dict:
    return {
        "race_id": race_id,
        "rating_band": band,
        "rating_score": 50.0,
        "source_count": sources,
        "fec_coverage": fec,
    }


@pytest.mark.unit
def test_bands_and_contested_count_only_races_with_monitored_coverage():
    """An unmonitored race renormalizes to Tossup; counting it invents a horse race."""
    rows = [
        _snapshot("a", "Tossup", sources=3),
        _snapshot("b", "Lean R", sources=2),
        _snapshot("c", "Tossup", sources=0),
        _snapshot("d", "Tossup", sources=0, fec=1),
    ]

    tally = exposure_tally(rows)

    assert tally["seats"] == 4
    assert tally["monitored"] == 3
    assert tally["not_monitored"] == 1
    assert tally["bands"]["Tossup"] == 2
    assert tally["bands"]["Lean R"] == 1
    # Tossup x2 + Lean R: the contested range spans Lean D..Lean R, not Tossup alone.
    assert tally["contested"] == 3


@pytest.mark.unit
def test_board_read_names_the_unmonitored_seats():
    tally = exposure_tally([
        _snapshot("a", "Lean D", sources=2),
        _snapshot("b", "Tossup", sources=0),
    ])

    read = board_read("senate", tally)

    assert "1 of the 2 seats" in read
    assert "no monitored coverage" in read


@pytest.mark.unit
def test_band_counts_can_still_count_every_row():
    """The all-rows count stays available so the trend series does not jump."""
    rows = [_snapshot("a", "Tossup", sources=0), _snapshot("b", "Tossup", sources=3)]

    assert band_counts(rows)["Tossup"] == 2
    assert band_counts(rows, monitored_only=True)["Tossup"] == 1
