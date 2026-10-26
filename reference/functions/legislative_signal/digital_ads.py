"""Weekly Google political-ads placement spend from the public BigQuery dataset.

No table in `bigquery-public-data.google_political_ads` carries week and geo
together:

  * `advertiser_weekly_spend` has exact weekly USD per advertiser, no geo.
  * `advertiser_geo_spend`    has per-state USD per advertiser, but cumulative
                              (no date column at all).

So a weekly per-state figure is an *estimate*: the advertiser's spend for the
week, split across states in proportion to that advertiser's cumulative US geo
mix. The one assumption is that an advertiser's state mix is stable over time;
an advertiser that pivots states mid-cycle is mis-split. Product label:
"digital placement, state-apportioned estimate" — no district precision is
claimed.

Candidate matching is conservative: exact uppercase advertiser-name match
against FEC principal-committee names only. Unmatched spend aggregates into a
state-level unattributed bucket (candidate_id = '').
"""

from __future__ import annotations

import re

from fec import get_house_candidate_roster

_FEC_CYCLE = 2026

_DATASET = "bigquery-public-data.google_political_ads"

# Every column below is checked against a captured copy of the real BigQuery
# schema by test_bq_queries_reference_only_real_columns. A column borrowed from
# a sibling table -- the `geo_targeting_included` bug, which lives on
# creative_stats, not here -- fails that test instead of failing every
# production run behind a swallowed "skip".
#
# `election_cycle` is empty for every row in advertiser_weekly_spend, so it is
# useless as a filter. Weeks start Sunday and the feed lags by up to ~8 days,
# so take the newest week at or before the run date rather than computing one.
_TARGET_WEEK_SQL = f"""
  SELECT MAX(week_start_date)
  FROM `{_DATASET}.advertiser_weekly_spend`
  WHERE week_start_date <= @run_date
"""

_WEEKLY_SQL = f"""
SELECT advertiser_id, advertiser_name, spend_usd
FROM `{_DATASET}.advertiser_weekly_spend`
WHERE week_start_date = ({_TARGET_WEEK_SQL})
"""

# Scoped to advertisers active in the target week. Unscoped this table is
# ~616k US rows, which OOMs the 512 MiB container; the filter cuts it to ~60k
# while preserving each advertiser's *full* US total (the filter is on
# advertiser, not subdivision), so NULL-subdivision dilution still works.
_GEO_SQL = f"""
SELECT advertiser_id, country_subdivision_primary, spend_usd
FROM `{_DATASET}.advertiser_geo_spend`
WHERE country = 'US'
  AND advertiser_id IN (
    SELECT advertiser_id
    FROM `{_DATASET}.advertiser_weekly_spend`
    WHERE week_start_date = ({_TARGET_WEEK_SQL})
  )
"""

_US_POSTALS = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY",
]

_US_REGIONS = frozenset(f"US-{postal}" for postal in _US_POSTALS)


class DigitalSpendUnavailable(RuntimeError):
    """Raised when the BigQuery digital-spend refresh cannot complete.

    Deliberately fatal: a silent "skip" is how a broken query survived every
    weekly run while the prior snapshot carried forward looking healthy.
    """


def bq_queries() -> dict[str, str]:
    """Label -> SQL, for the schema contract test."""
    return {"weekly": _WEEKLY_SQL, "geo": _GEO_SQL}


def referenced_tables(query: str) -> set[str]:
    """Dataset table names the query reads, from its backtick-quoted paths."""
    return {
        path.rsplit(".", 1)[-1]
        for path in re.findall(r"`([^`]*)`", query)
        if path.startswith(_DATASET)
    }


_SQL_KEYWORDS = frozenset("""
select from where group by order limit as and or not in is null on join left
right inner outer max min sum count avg distinct having asc desc union all
""".split())


def referenced_columns(query: str) -> set[str]:
    """Bare identifiers the query uses, i.e. candidate column references.

    Tokenizes the SQL rather than trusting a hand-maintained list, so a column
    added to the query without updating anything else still gets checked
    against the real schema.
    """
    # Drop backtick-quoted table paths and @parameters, then take bare words.
    stripped = re.sub(r"`[^`]*`", " ", query)
    stripped = re.sub(r"@\w+", " ", stripped)
    stripped = re.sub(r"'[^']*'", " ", stripped)
    tokens = set(re.findall(r"\b[a-z_][a-z0-9_]*\b", stripped.lower()))
    return tokens - _SQL_KEYWORDS


def _candidates_for_states(postals: list[str]) -> dict[str, list[dict]]:
    roster = get_house_candidate_roster(_FEC_CYCLE)
    if not roster:
        raise DigitalSpendUnavailable(
            f"FEC bulk roster unavailable for {_FEC_CYCLE}; digital coverage not written"
        )
    return {postal: roster[postal] for postal in postals if postal in roster}


def _normalize_region(value) -> str | None:
    """"AZ" or "US-AZ" -> "US-AZ"; anything unrecognized -> None.

    The column's schema description claims ISO 3166-2 ("US-CA") but the rows
    actually carry bare postals, so both forms are accepted.
    """
    raw = str(value or "").upper().strip()
    region = raw if raw.startswith("US-") else f"US-{raw}"
    return region if region in _US_REGIONS else None


def apportion_weekly_by_geo(
    weekly_rows: list[dict],
    geo_rows: list[dict],
) -> list[dict]:
    """Split each advertiser's weekly spend across states by its US geo mix.

    The denominator is the advertiser's *entire* US geo history, including rows
    with no subdivision (national/untargeted spend). Those rows dilute the
    per-state estimates instead of inflating them — national money is not
    credited to whichever states the advertiser also happens to target.
    Advertisers with no US geo history at all are dropped rather than guessed at.
    """
    state_spend: dict[str, dict[str, float]] = {}
    us_total: dict[str, float] = {}
    for row in geo_rows:
        advertiser_id = str(row.get("advertiser_id") or "")
        amount = float(row.get("spend_usd") or 0)
        us_total[advertiser_id] = us_total.get(advertiser_id, 0.0) + amount
        region = _normalize_region(row.get("country_subdivision_primary"))
        if region is None:
            continue  # counted above, but not attributable to a state
        bucket = state_spend.setdefault(advertiser_id, {})
        bucket[region] = bucket.get(region, 0.0) + amount

    out: list[dict] = []
    for row in weekly_rows:
        advertiser_id = str(row.get("advertiser_id") or "")
        weekly_spend = float(row.get("spend_usd") or 0)
        shares = state_spend.get(advertiser_id)
        total = us_total.get(advertiser_id, 0.0)
        if not shares or total <= 0:
            continue
        for region, geo_spend in shares.items():
            out.append({
                "advertiser_name": row.get("advertiser_name"),
                "region": region,
                "spend_usd": weekly_spend * (geo_spend / total),
            })
    return out


def _query_bigquery(run_date: str) -> list[dict]:
    """Weekly spend apportioned to states. Raises on any BigQuery failure."""
    from google.cloud import bigquery

    client = bigquery.Client()

    def run(sql: str) -> list[dict]:
        # Both queries embed the target-week subquery, so both need @run_date.
        config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("run_date", "DATE", run_date),
            ]
        )
        return [dict(r) for r in client.query(sql, job_config=config).result()]

    weekly = run(_WEEKLY_SQL)
    geo = run(_GEO_SQL)
    print(f"BigQuery digital spend: {len(weekly)} advertiser-weeks, {len(geo)} geo rows")
    return apportion_weekly_by_geo(weekly, geo)


def match_advertisers(
    advertiser_spend: list[dict],
    candidates_by_state: dict[str, list[dict]],
) -> tuple[list[dict], dict[str, float]]:
    """Exact-name matching only; unmatched spend goes to the state bucket."""
    matched_totals: dict[tuple[str, str], float] = {}
    unmatched: dict[str, float] = {}
    for row in advertiser_spend:
        region = str(row.get("region") or "").upper()
        if region not in _US_REGIONS:
            continue
        postal = region[3:]
        name = str(row.get("advertiser_name") or "").upper()
        amount = float(row.get("spend_usd") or 0)
        hit = None
        for cand in candidates_by_state.get(postal, []):
            if name in cand["committee_names"]:
                hit = cand
                break
        if hit:
            key = (region, hit["candidate_id"])
            matched_totals[key] = matched_totals.get(key, 0.0) + amount
        else:
            unmatched[region] = unmatched.get(region, 0.0) + amount
    matched = [
        {"region": region, "candidate_id": candidate_id,
         "digital_spend_wk": amount}
        for (region, candidate_id), amount in matched_totals.items()
    ]
    return matched, unmatched


def refresh_digital_spend(run_date: str, supabase, bq_rows: list[dict] | None = None) -> None:
    if bq_rows is None:
        try:
            rows = _query_bigquery(run_date)
        except Exception as exc:  # surfaced, never swallowed
            raise DigitalSpendUnavailable(
                f"BigQuery digital-spend refresh failed for {run_date}: {exc}"
            ) from exc
    else:
        rows = bq_rows
    candidates_by_state = _candidates_for_states(_US_POSTALS)
    matched, unmatched = match_advertisers(rows, candidates_by_state)
    payload: list[dict] = [
        {"run_date": run_date, "region": m["region"],
         "candidate_id": m["candidate_id"],
         "digital_spend_wk": m["digital_spend_wk"], "digital_coverage": 1.0}
        for m in matched
    ]
    payload.extend(
        {"run_date": run_date, "region": region, "candidate_id": "",
         "digital_spend_wk": amount, "digital_coverage": 1.0}
        for region, amount in unmatched.items()
    )
    if not payload:
        raise DigitalSpendUnavailable(
            f"BigQuery digital-spend refresh for {run_date} produced no US state rows"
        )
    try:
        supabase.table("ad_spend_signals").upsert(
            payload, on_conflict="run_date,region,candidate_id"
        ).execute()
    except Exception as exc:  # converted to the non-retrying boundary error
        raise DigitalSpendUnavailable(
            f"Digital-spend upsert failed for {run_date}: {exc}"
        ) from exc
    print(f"digital spend refreshed: {len(matched)} matched, "
          f"{len(unmatched)} state buckets")
