"""Deterministic assembly of a ``race_snapshots`` row.

Phase 1 (``GR3-516``). This module is pure: it turns already-gathered coverage
and campaign-finance inputs into one reviewable snapshot document, delegating
the rating itself to :mod:`shared.coverage_rating`. It performs no I/O and no
model calls, so the same inputs always produce the same row.
"""

from __future__ import annotations

from datetime import date

from shared.coverage_rating import (
    COVERAGE_RATING_VERSION,
    RatingResult,
    rate_race,
)
from shared.districts import coverage_region_for_race


def sum_money(*amounts: float | None) -> float:
    """Sum optional money amounts, treating missing values as zero."""
    return float(sum(a for a in amounts if a is not None))


def build_race_snapshot(    *,
    run_date: str | date,
    race_id: str,
    leaning_score: float | None,
    sentiment_score: float | None = None,
    issue_mix: dict | None = None,
    headline_count: int | None = None,
    source_count: int | None = None,
    dem_money: float | None = None,
    rep_money: float | None = None,
    incumbent_party: str | None = None,
    fec_coverage: float | None = None,
    ie_support: float | None = None,
    ie_oppose: float | None = None,
    digital_spend: float | None = None,
    evidence: list | None = None,
) -> dict:
    """Return a snapshot dict ready for an idempotent ``race_snapshots`` upsert.

    ``evidence`` must be a list of resolvable strings (source URLs, values). It
    is stored verbatim so every rendered band can point at its inputs.
    """
    result: RatingResult = rate_race(
        leaning_score=leaning_score,
        sentiment_score=sentiment_score,
        dem_money=dem_money,
        rep_money=rep_money,
        incumbent_party=incumbent_party,
        source_count=source_count,
        fec_coverage=fec_coverage,
    )
    iso_date = run_date.isoformat() if isinstance(run_date, date) else str(run_date)

    return {
        "run_date": iso_date,
        "race_id": race_id,
        "coverage_leaning": leaning_score,
        "coverage_tone": sentiment_score,
        "issue_mix": issue_mix or {},
        "headline_count": headline_count,
        "source_count": source_count,
        "ie_support": ie_support,
        "ie_oppose": ie_oppose,
        "digital_spend": digital_spend,
        "dem_money": dem_money,
        "rep_money": rep_money,
        "fec_coverage": fec_coverage,
        "rating_score": result.rating_score,
        "rating_band": result.rating_band,
        "rating_confidence": result.confidence,
        "components": dict(result.components),
        "methodology_version": COVERAGE_RATING_VERSION,
        "evidence": evidence or [],
    }


def summarize_district_money(ad_spend_rows: list[dict]) -> dict[str, dict]:
    """Aggregate ad-spend rows into per-district party money.

    Money favoring a party = independent expenditures supporting that party's
    candidates plus expenditures opposing the other party's candidates. Rows
    with no district (state-level unattributed digital spend) are ignored.
    """
    summary: dict[str, dict] = {}
    for row in ad_spend_rows:
        district = row.get("district")
        if not district:
            continue
        support = float(row.get("ie_support_7d") or 0.0)
        oppose = float(row.get("ie_oppose_7d") or 0.0)
        party = str(row.get("party") or "").upper()
        bucket = summary.setdefault(
            district,
            {"dem_money": 0.0, "rep_money": 0.0, "ie_support": 0.0, "ie_oppose": 0.0, "fec_coverage": 1.0},
        )
        bucket["ie_support"] += support
        bucket["ie_oppose"] += oppose
        if party.startswith("D"):
            bucket["dem_money"] += support
            bucket["rep_money"] += oppose
        elif party.startswith("R"):
            bucket["rep_money"] += support
            bucket["dem_money"] += oppose
    return summary


def build_snapshot_rows(
    *,
    run_date: str,
    races: list[dict],
    coverage_by_region: dict[str, dict],
    money_by_district: dict[str, dict],
) -> list[dict]:
    """Build one snapshot row per race from coverage and money lookups.

    ``races`` is a list of dicts with ``race_id``, ``chamber``, ``state``
    (``US-XX``), ``district``, and ``incumbent_party``. Coverage is looked up by
    the race's coverage region (district for House, state otherwise); money is
    looked up by district label for House races and by state postal code for
    Senate races.
    """
    rows: list[dict] = []
    for race in races:
        region = coverage_region_for_race(race)
        coverage = coverage_by_region.get(region) or {}
        postal = str(race.get("state", "")).removeprefix("US-")
        district_label = (
            f"{postal}-{int(race['district']):02d}"
            if race.get("chamber") == "house" and race.get("district") is not None
            else None
        )
        if district_label is not None:
            money_key = district_label
        elif race.get("chamber") == "senate":
            # Senate independent expenditures are keyed by state; a governor
            # race in the same state files nothing with the FEC and must not
            # borrow them.
            money_key = postal
        else:
            money_key = ""
        money = money_by_district.get(money_key) or {}
        rows.append(
            build_race_snapshot(
                run_date=run_date,
                race_id=race["race_id"],
                leaning_score=coverage.get("leaning_score"),
                sentiment_score=coverage.get("sentiment_score"),
                issue_mix=coverage.get("issue_mix") or {},
                headline_count=coverage.get("headline_count"),
                source_count=coverage.get("source_count"),
                dem_money=money.get("dem_money"),
                rep_money=money.get("rep_money"),
                incumbent_party=race.get("incumbent_party"),
                fec_coverage=money.get("fec_coverage", 0.0),
                ie_support=money.get("ie_support"),
                ie_oppose=money.get("ie_oppose"),
                evidence=coverage.get("evidence") or [],
            )
        )
    return rows
