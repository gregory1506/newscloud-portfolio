"""Per-candidate ad-spend gathering: FEC Schedule E independent expenditures.

Rolling 7-day window per candidate, one row per (run_date, region,
candidate_id). Both federal chambers are gathered: House rows are keyed by their
district label (``TX-07``), Senate rows by the state postal code (``TX``), which
is how the Race Board's money lookup resolves them. Governors file with no
federal agency, so they have no rows and their races rate without money.

Degrades to a single coverage-0 state row on House API failure — never raises
into the per-state processing loop. A Senate failure writes no rows (a race
without money lowers confidence, exactly as an absent row does).
"""

from __future__ import annotations

from datetime import date, timedelta

from fec import (
    get_house_candidates,
    get_senate_candidates,
    get_state_independent_expenditures,
)

_FEC_CYCLE = 2026
_IE_WINDOW_DAYS = 7


def build_ad_spend_rows(
    region: str,
    run_date: str,
    candidates: list[dict] | None,
    ie_totals: dict[str, dict] | None,
    *,
    district_label: str | None = None,
) -> list[dict]:
    """Pure row builder. None inputs produce one degraded coverage-0 row.

    ``district_label`` overrides the candidate's own FEC district, which is how
    Senate rows carry the state key the board looks up.
    """
    if candidates is None or ie_totals is None:
        return [
            {
                "run_date": run_date,
                "region": region,
                "candidate_id": "",
                "candidate_name": None,
                "party": None,
                "district": None,
                "ie_support_7d": None,
                "ie_oppose_7d": None,
                "fec_coverage": 0.0,
            }
        ]
    rows: list[dict] = []
    for cand in candidates:
        totals = ie_totals.get(cand["candidate_id"])
        if not totals:
            continue
        rows.append(
            {
                "run_date": run_date,
                "region": region,
                "candidate_id": cand["candidate_id"],
                "candidate_name": cand["name"],
                "party": cand["party"],
                "district": district_label or cand["district"],
                "ie_support_7d": totals["support"],
                "ie_oppose_7d": totals["oppose"],
                "fec_coverage": 1.0,
            }
        )
    return rows


def upsert_ad_spend_rows(supabase, rows: list[dict]) -> None:
    if not rows:
        return
    supabase.table("ad_spend_signals").upsert(
        rows, on_conflict="run_date,region,candidate_id"
    ).execute()


def _senate_rows(region: str, run_date: str, postal: str, window_start: str) -> list[dict]:
    """Senate independent expenditures for one state, keyed by its postal code.

    Outside money is the gating signal, so the expenditures are queried first:
    a state with no Senate activity costs one call instead of two.
    """
    ie_totals = get_state_independent_expenditures(
        postal, window_start, run_date, office="S"
    )
    if not ie_totals:
        return []
    candidates = get_senate_candidates(postal, _FEC_CYCLE)
    if not candidates:
        return []
    return build_ad_spend_rows(
        region, run_date, candidates, ie_totals, district_label=postal
    )


def gather_state_ad_spend(region: str, run_date: str, supabase) -> None:
    postal = region.split("-", 1)[1]
    window_start = (date.fromisoformat(run_date) - timedelta(days=_IE_WINDOW_DAYS)).isoformat()
    house_candidates = get_house_candidates(postal, _FEC_CYCLE)
    house_totals = (
        get_state_independent_expenditures(postal, window_start, run_date)
        if house_candidates is not None
        else None
    )
    rows = build_ad_spend_rows(region, run_date, house_candidates, house_totals)
    rows.extend(_senate_rows(region, run_date, postal, window_start))
    upsert_ad_spend_rows(supabase, rows)
    print(f"ad_spend_signals upserted {len(rows)} row(s) for {region} {run_date}")
