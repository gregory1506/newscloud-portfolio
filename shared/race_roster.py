"""Race roster helpers shared by the builder, sync script, and scorer.

Phase 1 (``GR3-516``). Keeps the race-id format, roster validation, party
normalization, and FEC-candidate mapping in one place so the builder and the
runtime cannot drift.
"""

from __future__ import annotations

import json
from pathlib import Path

CHAMBER_PREFIX: dict[str, str] = {
    "senate": "SEN",
    "house": "HOU",
    "governor": "GOV",
}

SEAT_STATUSES: frozenset[str] = frozenset({"incumbent", "open", "retiring", "unknown"})

_PARTY_LETTERS = {
    "DEM": "D", "DEMOCRAT": "D", "DEMOCRATIC": "D", "D": "D", "DFL": "D",
    "REP": "R", "REPUBLICAN": "R", "R": "R", "GOP": "R",
    "IND": "I", "INDEPENDENT": "I", "I": "I", "GRE": "G", "LIB": "L",
}


def race_id(chamber: str, postal: str, district: int | None = None) -> str:
    """Return the canonical race id, e.g. ``2026-HOU-TX-07``."""
    if chamber not in CHAMBER_PREFIX:
        raise ValueError(f"Unsupported chamber: {chamber!r}")
    prefix = CHAMBER_PREFIX[chamber]
    if chamber == "house":
        if district is None:
            raise ValueError("house races require a district")
        return f"2026-{prefix}-{postal}-{district:02d}"
    return f"2026-{prefix}-{postal}"


def normalize_party(party: str | None) -> str:
    """Map an FEC/roster party code or name to ``D``/``R``/``I``/other."""
    if not party:
        return ""
    return _PARTY_LETTERS.get(str(party).strip().upper(), str(party).strip().upper())


def load_roster(path: str | Path) -> dict:
    """Load and validate a roster JSON document."""
    roster = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = validate_roster(roster)
    if problems:
        raise ValueError("invalid race roster: " + "; ".join(problems))
    return roster


def _validate_race(race: dict) -> list[str]:
    rid = race.get("race_id")
    if not rid:
        return ["race missing race_id"]
    problems: list[str] = []
    if race.get("chamber") not in CHAMBER_PREFIX:
        problems.append(f"{rid}: bad chamber {race.get('chamber')!r}")
    if race.get("seat_status") not in SEAT_STATUSES:
        problems.append(f"{rid}: bad seat_status {race.get('seat_status')!r}")
    if race.get("chamber") == "house" and race.get("district") is None:
        problems.append(f"{rid}: house race missing district")
    return problems


def _validate_counts(roster: dict, races: list[dict]) -> list[str]:
    counts = roster.get("counts")
    if not isinstance(counts, dict):
        return []
    actual = {
        "senate": sum(1 for r in races if r.get("chamber") == "senate"),
        "house": sum(1 for r in races if r.get("chamber") == "house"),
        "governor": sum(1 for r in races if r.get("chamber") == "governor"),
    }
    return [
        f"counts.{chamber}={expected} but found {actual.get(chamber)}"
        for chamber, expected in counts.items()
        if actual.get(chamber) != expected
    ]


def validate_roster(roster: dict) -> list[str]:
    """Return a list of validation problems. Empty means valid."""
    races = roster.get("races")
    if not isinstance(races, list) or not races:
        return ["roster has no races"]

    problems: list[str] = []
    seen: set[str] = set()
    for race in races:
        rid = race.get("race_id")
        if rid and rid in seen:
            problems.append(f"duplicate race_id {rid}")
        if rid:
            seen.add(rid)
        problems.extend(_validate_race(race))
    problems.extend(_validate_counts(roster, races))
    return problems


def map_fec_candidate(candidate: dict, race_id_value: str) -> dict:
    """Map one FEC candidate dict to a ``candidates`` row.

    Incumbency is left False unless the caller knows otherwise: the FEC
    candidate API does not flag incumbency, and guessing would be worse than
    leaving it for the roster/snapshot join.
    """
    return {
        "candidate_id": candidate.get("candidate_id", ""),
        "race_id": race_id_value,
        "name": candidate.get("name", ""),
        "party": normalize_party(candidate.get("party")),
        "is_incumbent": False,
        "status": "declared",
        "committee_ids": [],
        "fec_coverage": 1.0 if candidate.get("candidate_id") else 0.0,
    }
