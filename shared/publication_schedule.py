"""Publication dates during the every-other-day wind-down."""

from datetime import date, timedelta


WIND_DOWN_ANCHOR = date(2026, 10, 23)


def publication_date_on_or_before(day: date) -> date:
    """Keep historical daily runs; alternate dates after the last daily edition.

    Use elapsed calendar days, not odd month days: October 31 is followed by
    November 2, including across the daylight-saving transition.
    """
    if day <= WIND_DOWN_ANCHOR:
        return day
    return day - timedelta(days=(day - WIND_DOWN_ANCHOR).days % 2)
