"""Race Board scoring step owned by the site publisher (Race Board Phase 1).

Runs once per publication, before the board export reads ``race_snapshots``, and
writes one deterministic row per race. The publisher calls it best-effort; the
board export asserts its own date afterwards, so a scoring failure fails the
publication loudly instead of shipping a stale board.

Coverage is the race's own region — the district for House races, the state for
Senate and governor races. Money is FEC independent-expenditure pressure from
``ad_spend_signals``: House rows keyed by district, Senate rows keyed by state.
Governor races file with no federal agency, so they have no money rows. Missing
coverage or money lowers confidence rather than producing a stronger claim.
"""

from __future__ import annotations

import json
from pathlib import Path

from shared.race_roster import load_roster
from shared.race_scoring import build_snapshot_rows, summarize_district_money
from shared.supabase_client import get_supabase

ROOT = Path(__file__).resolve().parents[2]
ROSTER_PATH = ROOT / "config" / "races_2026.json"
RACE_SNAPSHOT_TABLE = "race_snapshots"


def load_bundled_roster() -> dict:
    return load_roster(ROSTER_PATH)


def sync_races(supabase, roster: dict) -> int:
    rows = [
        {
            "race_id": race["race_id"],
            "cycle": race["cycle"],
            "chamber": race["chamber"],
            "state": race["state"],
            "district": race.get("district"),
            "seat_class": race.get("seat_class"),
            "election_date": race["election_date"],
            "seat_status": race.get("seat_status", "unknown"),
            "incumbent_party": race.get("incumbent_party"),
            "data_status": race.get("data_status", "structural_only"),
        }
        for race in roster["races"]
    ]
    if rows:
        supabase.table("races").upsert(rows, on_conflict="race_id").execute()
    return len(rows)


def fetch_races(supabase, cycle: int) -> list[dict]:
    response = (
        supabase.table("races")
        .select("race_id,chamber,state,district,incumbent_party")
        .eq("cycle", cycle)
        .execute()
    )
    return response.data or []


def fetch_coverage(supabase, run_date: str) -> dict[str, dict]:
    """Return coverage lookup keyed by region for one run date."""
    sentiment_rows = (
        supabase.table("regional_sentiment")
        .select("region,leaning_score,sentiment_score,topic_scores")
        .eq("date", run_date)
        .execute()
        .data
        or []
    )
    frequency_rows = (
        supabase.table("word_frequencies")
        .select("region,supporting_headlines")
        .eq("date", run_date)
        .execute()
        .data
        or []
    )
    coverage: dict[str, dict] = {}
    for row in sentiment_rows:
        coverage[row["region"]] = {
            "leaning_score": row.get("leaning_score"),
            "sentiment_score": row.get("sentiment_score"),
            "issue_mix": row.get("topic_scores") or {},
        }
    for row in frequency_rows:
        headlines = row.get("supporting_headlines") or []
        sources = {
            (h.get("source_name") or "").strip().lower()
            for h in headlines
            if isinstance(h, dict) and (h.get("source_name") or "").strip()
        }
        evidence = [
            h.get("url") for h in headlines if isinstance(h, dict) and h.get("url")
        ][:3]
        entry = coverage.setdefault(row["region"], {})
        entry["source_count"] = len(sources)
        entry["headline_count"] = len(headlines)
        entry["evidence"] = evidence
    return coverage


def fetch_money(supabase, run_date: str) -> dict[str, dict]:
    rows = (
        supabase.table("ad_spend_signals")
        .select("party,district,ie_support_7d,ie_oppose_7d")
        .eq("run_date", run_date)
        .execute()
        .data
        or []
    )
    return summarize_district_money(rows)


def upsert_snapshots(supabase, rows: list[dict]) -> int:
    if not rows:
        return 0
    supabase.table(RACE_SNAPSHOT_TABLE).upsert(
        rows, on_conflict="run_date,race_id"
    ).execute()
    return len(rows)


def score_race_board(run_date: str, *, supabase=None, cycle: int = 2026) -> int:
    """Write ``race_snapshots`` for one run date. Returns the row count."""
    supabase = supabase or get_supabase()
    roster = load_bundled_roster()
    sync_races(supabase, roster)

    races = fetch_races(supabase, cycle)
    coverage = fetch_coverage(supabase, run_date)
    money = fetch_money(supabase, run_date)
    rows = build_snapshot_rows(
        run_date=run_date,
        races=races,
        coverage_by_region=coverage,
        money_by_district=money,
    )
    count = upsert_snapshots(supabase, rows)
    print(json.dumps({
        "event": "race_board_scored",
        "run_date": run_date,
        "race_count": len(races),
        "snapshot_count": count,
        "coverage_regions": len(coverage),
        "money_districts": len(money),
    }, sort_keys=True))
    return count
