"""Canonical U.S. region scope for the party-lane product.

All 50 states are ranked. Washington D.C. is collected as national context
but is not ranked. TT and UK are non-U.S. regions that do not affect U.S.
readiness or party synthesis.
"""

from __future__ import annotations

# Alphabetically ordered tuple of the 50 U.S. state region codes.
US_RANKED_STATES: tuple[str, ...] = (
    "US-AK", "US-AL", "US-AR", "US-AZ", "US-CA", "US-CO", "US-CT",
    "US-DE", "US-FL", "US-GA", "US-HI", "US-IA", "US-ID", "US-IL",
    "US-IN", "US-KS", "US-KY", "US-LA", "US-MA", "US-MD", "US-ME",
    "US-MI", "US-MN", "US-MO", "US-MS", "US-MT", "US-NC", "US-ND",
    "US-NE", "US-NH", "US-NJ", "US-NM", "US-NV", "US-NY", "US-OH",
    "US-OK", "US-OR", "US-PA", "US-RI", "US-SC", "US-SD", "US-TN",
    "US-TX", "US-UT", "US-VA", "US-VT", "US-WA", "US-WI", "US-WV",
    "US-WY",
)

DC: str = "US-DC"

NON_US_REGIONS: tuple[str, ...] = ("TT", "UK")

# 51 jurisdictions: 50 ranked states + D.C. as unranked national context.
US_COLLECTION_JURISDICTIONS: tuple[str, ...] = US_RANKED_STATES + (DC,)

# Full collection scope: 53 regions (51 U.S. + TT + UK).
ALL_REGIONS: tuple[str, ...] = US_COLLECTION_JURISDICTIONS + NON_US_REGIONS

# The seven states the coverage/attention reporting treats as battlegrounds.
BATTLEGROUND_REGIONS: tuple[str, ...] = (
    "US-AZ", "US-GA", "US-MI", "US-NC", "US-NV", "US-PA", "US-WI",
)

_RANKED_SET: frozenset[str] = frozenset(US_RANKED_STATES)
_US_SET: frozenset[str] = frozenset(US_COLLECTION_JURISDICTIONS)
_NON_US_SET: frozenset[str] = frozenset(NON_US_REGIONS)

STATE_DISPLAY_NAMES: dict[str, str] = {
    "US-AK": "Alaska",
    "US-AL": "Alabama",
    "US-AR": "Arkansas",
    "US-AZ": "Arizona",
    "US-CA": "California",
    "US-CO": "Colorado",
    "US-CT": "Connecticut",
    "US-DC": "Washington, D.C.",
    "US-DE": "Delaware",
    "US-FL": "Florida",
    "US-GA": "Georgia",
    "US-HI": "Hawaii",
    "US-IA": "Iowa",
    "US-ID": "Idaho",
    "US-IL": "Illinois",
    "US-IN": "Indiana",
    "US-KS": "Kansas",
    "US-KY": "Kentucky",
    "US-LA": "Louisiana",
    "US-MA": "Massachusetts",
    "US-MD": "Maryland",
    "US-ME": "Maine",
    "US-MI": "Michigan",
    "US-MN": "Minnesota",
    "US-MO": "Missouri",
    "US-MS": "Mississippi",
    "US-MT": "Montana",
    "US-NC": "North Carolina",
    "US-ND": "North Dakota",
    "US-NE": "Nebraska",
    "US-NH": "New Hampshire",
    "US-NJ": "New Jersey",
    "US-NM": "New Mexico",
    "US-NV": "Nevada",
    "US-NY": "New York",
    "US-OH": "Ohio",
    "US-OK": "Oklahoma",
    "US-OR": "Oregon",
    "US-PA": "Pennsylvania",
    "US-RI": "Rhode Island",
    "US-SC": "South Carolina",
    "US-SD": "South Dakota",
    "US-TN": "Tennessee",
    "US-TX": "Texas",
    "US-UT": "Utah",
    "US-VA": "Virginia",
    "US-VT": "Vermont",
    "US-WA": "Washington",
    "US-WI": "Wisconsin",
    "US-WV": "West Virginia",
    "US-WY": "Wyoming",
}

# URL-safe slugs for dashboard routes (e.g. /democrats/states/north-carolina/).
STATE_SLUGS: dict[str, str] = {
    "US-AK": "alaska",
    "US-AL": "alabama",
    "US-AR": "arkansas",
    "US-AZ": "arizona",
    "US-CA": "california",
    "US-CO": "colorado",
    "US-CT": "connecticut",
    "US-DC": "washington-dc",
    "US-DE": "delaware",
    "US-FL": "florida",
    "US-GA": "georgia",
    "US-HI": "hawaii",
    "US-IA": "iowa",
    "US-ID": "idaho",
    "US-IL": "illinois",
    "US-IN": "indiana",
    "US-KS": "kansas",
    "US-KY": "kentucky",
    "US-LA": "louisiana",
    "US-MA": "massachusetts",
    "US-MD": "maryland",
    "US-ME": "maine",
    "US-MI": "michigan",
    "US-MN": "minnesota",
    "US-MO": "missouri",
    "US-MS": "mississippi",
    "US-MT": "montana",
    "US-NC": "north-carolina",
    "US-ND": "north-dakota",
    "US-NE": "nebraska",
    "US-NH": "new-hampshire",
    "US-NJ": "new-jersey",
    "US-NM": "new-mexico",
    "US-NV": "nevada",
    "US-NY": "new-york",
    "US-OH": "ohio",
    "US-OK": "oklahoma",
    "US-OR": "oregon",
    "US-PA": "pennsylvania",
    "US-RI": "rhode-island",
    "US-SC": "south-carolina",
    "US-SD": "south-dakota",
    "US-TN": "tennessee",
    "US-TX": "texas",
    "US-UT": "utah",
    "US-VA": "virginia",
    "US-VT": "vermont",
    "US-WA": "washington",
    "US-WI": "wisconsin",
    "US-WV": "west-virginia",
    "US-WY": "wyoming",
}


def is_ranked_state(region: str) -> bool:
    """True for any of the 50 ranked U.S. states. D.C., TT, and UK return False."""
    return region in _RANKED_SET


def is_us_jurisdiction(region: str) -> bool:
    """True for all 51 U.S. collection jurisdictions (50 states + D.C.)."""
    return region in _US_SET


def is_non_us(region: str) -> bool:
    """True for TT and UK."""
    return region in _NON_US_SET


def get_ranked_states(limit: int | None = None) -> list[str]:
    """Return ranked state codes in alphabetical order, optionally capped to limit."""
    states = list(US_RANKED_STATES)
    return states[:limit] if limit is not None else states


def is_us_ready(completed_regions: set[str]) -> bool:
    """True when all 51 U.S. collection jurisdictions appear in completed_regions.

    TT and UK are ignored: a non-U.S. failure does not block party synthesis.
    """
    return _US_SET.issubset(completed_regions)
