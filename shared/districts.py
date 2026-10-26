"""Congressional-district region model.

Phase 1 (``GR3-516``). Districts are gathered as their own region namespace,
``US-<ST>-<DD>`` (e.g. ``US-TX-07``), so district coverage can live alongside
state coverage in ``word_frequencies`` / ``regional_sentiment`` **without**
joining ``shared.regions.ALL_REGIONS`` — the 53-region daily run and the U.S.
readiness barrier must never depend on 435 district runs.

District regions are intentionally outside :mod:`shared.regions` so that
``is_us_ready`` and party synthesis are unaffected.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_DISTRICT_RE = re.compile(r"^US-([A-Z]{2})-(\d{2})$")


def district_region(postal: str, district: int) -> str:
    """Return the district region code, e.g. ``US-TX-07``."""
    return f"US-{postal}-{district:02d}"


def parse_district_region(region: str) -> tuple[str, int] | None:
    """Return ``(postal, district)`` for a district region, else None."""
    match = _DISTRICT_RE.match(region or "")
    if not match:
        return None
    return match.group(1), int(match.group(2))


def is_district_region(region: str) -> bool:
    return parse_district_region(region) is not None


def district_label(postal: str, district: int) -> str:
    """Short human label, e.g. ``TX-07``."""
    return f"{postal}-{district:02d}"


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def district_display_name(postal: str, district: int, state_name: str | None = None) -> str:
    """District display name, e.g. ``Texas's 7th Congressional District``."""
    place = state_name or postal
    return f"{place}'s {_ordinal(district)} Congressional District"


def all_district_regions(roster: dict) -> list[str]:
    """Return every House district region code in a roster, sorted."""
    regions = [
        district_region(race["postal"], race["district"])
        for race in roster.get("races", [])
        if race.get("chamber") == "house" and race.get("district") is not None
    ]
    return sorted(regions)


def coverage_region_for_race(race: dict) -> str:
    """Return the region whose coverage applies to a race.

    House races use their own district (``US-TX-07``); Senate and governor
    races use the state (``US-TX``). ``race["state"]`` is an ``US-XX`` code.
    """
    postal = str(race.get("state", "")).removeprefix("US-")
    if race.get("chamber") == "house" and race.get("district") is not None:
        return district_region(postal, int(race["district"]))
    return f"US-{postal}"


def race_slug(chamber: str, postal: str, district: int | None = None) -> str:
    """URL slug for a race page: ``tx-07``, ``tx-senate``, ``tx-governor``."""
    if chamber == "house" and district is not None:
        return f"{postal.lower()}-{int(district):02d}"
    return f"{postal.lower()}-{chamber}"


def race_slug_for(race: dict) -> str:
    postal = str(race.get("state", "")).removeprefix("US-")
    return race_slug(race.get("chamber", ""), postal, race.get("district"))


def load_district_targets(path: str | Path) -> dict:
    """Load the district-gathering target policy."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def select_district_targets(
    all_regions: list[str],
    config: dict,
    *,
    ranked_regions: list[str] | None = None,
) -> list[str]:
    """Choose which districts to gather for a cycle.

    ``mode="all"`` gathers every district (subject to ``max_districts``).
    ``mode="priority"`` (the default) gathers only explicitly listed
    ``priority_regions`` plus any ``ranked_regions`` supplied at runtime (for
    example, the most competitive districts by campaign money). An empty result
    means district gathering is off, which is the safe default for a
    call-volume-heavy path.
    """
    valid = set(all_regions)
    mode = config.get("mode", "priority")
    if mode == "all":
        ordered = list(all_regions)
    else:
        ordered = list(
            dict.fromkeys(
                [
                    *(r for r in config.get("priority_regions", []) if r in valid),
                    *(r for r in (ranked_regions or []) if r in valid),
                ]
            )
        )

    cap = int(config.get("max_districts") or 0)
    return ordered[:cap] if cap > 0 else ordered

