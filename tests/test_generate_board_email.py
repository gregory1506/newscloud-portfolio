"""Tests for the Race Board email generator (rendering and the language gate)."""

from __future__ import annotations

import pytest

from scripts.export_race_board_data import build_board_payload
from scripts.generate_board_email import (
    check_prohibited_language,
    render_board_html_email,
    render_board_text_email,
    select_spotlight,
)


def _board():
    races = [
        {"race_id": "2026-HOU-TX-07", "chamber": "house", "state": "US-TX",
         "district": 7, "incumbent_party": "R", "seat_status": "unknown"},
    ]
    snapshots = {"2026-HOU-TX-07": {"rating_band": "Tossup", "rating_score": 50.0,
                                    "rating_confidence": 0.8, "source_count": 4}}
    return build_board_payload(
        run_date="2026-09-19", races=races, snapshots_by_race=snapshots,
        prior_bands={"2026-HOU-TX-07": "Lean R"},
    )


@pytest.mark.unit
def test_board_email_text_tells_the_lead_move_once_with_its_evidence():
    """The top mover is the spotlight: one telling, then the rest as a list."""
    text = render_board_text_email(_board(), "https://example.com/board")
    assert "NEWSCLOUD RACE BOARD" in text
    assert "2026-09-19" in text
    assert "moved back into tossup" in text  # specific change-first lead
    assert "Moved on the board — TX-07 (Tossup)" in text
    # The lead mover is not repeated in a list of movers.
    assert "TX-07: Lean R → Tossup" not in text
    assert "Spotlight — TX-07" not in text
    assert "https://example.com/board/race/tx-07/" in text
    assert "not public opinion research or vote intention" in text


@pytest.mark.unit
def test_other_movers_stay_a_list_beneath_the_lead():
    board = build_board_payload(
        run_date="2026-09-19",
        races=[
            {"race_id": "2026-SEN-GA", "chamber": "senate", "state": "US-GA"},
            {"race_id": "2026-SEN-TX", "chamber": "senate", "state": "US-TX"},
        ],
        snapshots_by_race={
            "2026-SEN-GA": {"rating_band": "Lean D", "rating_score": 40.0, "source_count": 4},
            "2026-SEN-TX": {"rating_band": "Lean R", "rating_score": 60.0, "source_count": 4},
        },
        prior_bands={"2026-SEN-GA": "Lean R", "2026-SEN-TX": "Tossup"},
    )

    text = render_board_text_email(board)

    assert "Moved on the board —" in text
    assert "Also moved:" in text
    # The lead mover is told in its own block, never again in list form; the second
    # mover is only in the list.
    assert "Georgia: Lean R → Lean D" not in text
    assert "Texas: Tossup → Lean R" in text


@pytest.mark.unit
def test_board_email_passes_its_own_language_gate():
    board = _board()
    combined = render_board_html_email(board) + "\n" + render_board_text_email(board)
    assert check_prohibited_language(combined) == []


@pytest.mark.unit
def test_language_gate_flags_predictive_phrases():
    assert "will win" in check_prohibited_language("Our candidate will win this seat")
    assert "forecast" in check_prohibited_language("A forecast of the midterms")
    # Quoting coverage that mentions polling is legitimate for the board.
    assert check_prohibited_language("The latest polling average") == []


@pytest.mark.unit
def test_email_bars_count_monitored_coverage_and_name_the_rest():
    """The bar is drawn over monitored races; the unmonitored seat is named, not painted."""
    board = build_board_payload(
        run_date="2026-09-19",
        races=[
            {"race_id": "2026-SEN-GA", "chamber": "senate", "state": "US-GA"},
            {"race_id": "2026-SEN-TX", "chamber": "senate", "state": "US-TX"},
        ],
        snapshots_by_race={
            "2026-SEN-GA": {"rating_band": "Lean D", "rating_score": 42.0, "source_count": 4},
            "2026-SEN-TX": {"rating_band": "Tossup", "rating_score": 50.0, "source_count": 0},
        },
        prior_bands={},
    )

    html_body = render_board_html_email(board)
    text_body = render_board_text_email(board)

    assert "Chamber distribution" in html_body
    assert "Lean D 1" in html_body
    assert "1 of 2 seats with monitored coverage · 1 without" in html_body
    # No segment is painted Tossup for the unmonitored seat (the key legitimately
    # shows the colour, so the check is on segment styling).
    assert "background:#9b84bd;width" not in html_body
    assert "Chamber distribution (races with monitored coverage):" in text_body
    assert "Senate: Monitored coverage runs Democratic-ward, 1 to 0" in text_body
    assert "1 of 2 seats with monitored coverage" in text_body
    # The coloured bar is sized to the monitored share of the chamber (1 of 2), so it
    # cannot claim coverage the board does not have.
    assert 'width="50.00%"' in html_body


@pytest.mark.unit
def test_html_money_line_is_omitted_when_the_spotlight_has_no_money():
    """The text edition guarded this; the HTML shipped '— favoring Democrats' daily."""
    board = build_board_payload(
        run_date="2026-09-19",
        races=[{"race_id": "2026-SEN-GA", "chamber": "senate", "state": "US-GA"}],
        snapshots_by_race={
            "2026-SEN-GA": {"rating_band": "Tossup", "rating_score": 50.0, "source_count": 4},
        },
        prior_bands={},
    )

    assert "favoring Democrats" not in render_board_html_email(board)


@pytest.mark.unit
def test_html_money_line_renders_when_the_spotlight_has_money():
    board = build_board_payload(
        run_date="2026-09-19",
        races=[{"race_id": "2026-SEN-GA", "chamber": "senate", "state": "US-GA"}],
        snapshots_by_race={
            "2026-SEN-GA": {
                "rating_band": "Tossup",
                "rating_score": 50.0,
                "source_count": 4,
                "dem_money": 120000.0,
                "rep_money": 40000.0,
            },
        },
        prior_bands={},
    )

    html_body = render_board_html_email(board)

    assert "favoring Democrats" in html_body
    assert "120,000" in html_body


@pytest.mark.unit
def test_distribution_read_names_the_direction_before_the_counts():
    """The counts are detail; the sentence has to say what they mean."""
    board = build_board_payload(
        run_date="2026-09-19",
        races=[
            {"race_id": "2026-SEN-GA", "chamber": "senate", "state": "US-GA"},
            {"race_id": "2026-SEN-TX", "chamber": "senate", "state": "US-TX"},
            {"race_id": "2026-SEN-OH", "chamber": "senate", "state": "US-OH"},
        ],
        snapshots_by_race={
            "2026-SEN-GA": {"rating_band": "Lean R", "rating_score": 60.0, "source_count": 4},
            "2026-SEN-TX": {"rating_band": "Likely R", "rating_score": 70.0, "source_count": 4},
            "2026-SEN-OH": {"rating_band": "Lean D", "rating_score": 40.0, "source_count": 4},
        },
        prior_bands={},
    )

    text_body = render_board_text_email(board)

    assert "Monitored coverage runs Republican-ward, 2 to 1, with 0 in the tossup band" in text_body


@pytest.mark.unit
def test_board_lead_gives_the_churn_its_denominator():
    """36 changed bands means nothing without how many could have."""
    board = build_board_payload(
        run_date="2026-09-19",
        races=[{"race_id": "2026-SEN-GA", "chamber": "senate", "state": "US-GA"}],
        snapshots_by_race={
            "2026-SEN-GA": {"rating_band": "Tossup", "rating_score": 50.0, "source_count": 4},
        },
        prior_bands={"2026-SEN-GA": "Lean R"},
    )

    assert "one of 1 of 1 monitored seats to change bands" in board["lead"]


@pytest.mark.unit
def test_email_embeds_a_map_only_when_a_url_is_given():
    """An image URL that 404s is worse than no image, so absence must stay absent."""
    board = build_board_payload(
        run_date="2026-09-19",
        races=[{"race_id": "2026-SEN-GA", "chamber": "senate", "state": "US-GA"}],
        snapshots_by_race={
            "2026-SEN-GA": {"rating_band": "Lean D", "rating_score": 42.0, "source_count": 4},
        },
        prior_bands={},
    )
    url = "https://example.com/data/board/maps/senate-2026-09-19.png"

    with_map = render_board_html_email(board, map_urls={"senate": url})
    without_map = render_board_html_email(board, map_urls={})

    assert url in with_map
    assert '<img src="https://example.com' in with_map
    assert "<img" not in without_map


@pytest.mark.unit
def test_select_spotlight_prefers_a_mover():
    spotlight = select_spotlight(_board())
    assert spotlight["slug"] == "tx-07"
    assert spotlight["to_band"] == "Tossup"


def _board_without_movers(*, has_signal: bool):
    races = [
        {"race_id": "2026-HOU-TX-07", "chamber": "house", "state": "US-TX",
         "district": 7, "incumbent_party": "R", "seat_status": "unknown"},
    ]
    snapshots = {
        "2026-HOU-TX-07": {
            "rating_band": "Tossup",
            "rating_score": 50.0,
            "rating_confidence": 0.8,
            "source_count": 4 if has_signal else 0,
        }
    }
    return build_board_payload(
        run_date="2026-09-19", races=races, snapshots_by_race=snapshots, prior_bands={}
    )


@pytest.mark.unit
def test_select_spotlight_skips_a_race_without_monitored_coverage():
    """An unmonitored race renormalizes to Tossup, so it is not a close race."""
    assert select_spotlight(_board_without_movers(has_signal=False)) is None
    assert select_spotlight(_board_without_movers(has_signal=True))["slug"] == "tx-07"
