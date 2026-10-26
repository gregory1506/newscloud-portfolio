from datetime import date, timedelta
from itertools import pairwise

import pytest

from shared.publication_schedule import publication_date_on_or_before


pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        ("2026-10-22", "2026-10-22"),
        ("2026-10-23", "2026-10-23"),
        ("2026-10-24", "2026-10-23"),
        ("2026-10-25", "2026-10-25"),
        ("2026-10-31", "2026-10-31"),
        ("2026-11-01", "2026-10-31"),
        ("2026-11-02", "2026-11-02"),
        ("2027-01-01", "2027-01-01"),
        ("2027-01-02", "2027-01-01"),
    ],
)
def test_expected_edition_across_cutover_month_and_year(day, expected):
    assert publication_date_on_or_before(date.fromisoformat(day)) == date.fromisoformat(expected)


def test_publications_remain_two_calendar_days_apart_through_leap_year():
    start = date(2026, 10, 23)
    days = [start + timedelta(days=offset) for offset in range(500)]
    publications = [day for day in days if publication_date_on_or_before(day) == day]
    assert all(right - left == timedelta(days=2) for left, right in pairwise(publications))
