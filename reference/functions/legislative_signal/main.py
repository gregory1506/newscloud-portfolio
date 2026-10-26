"""Daily legislative, campaign-finance, and official-messaging signals.

Congress.gov contributes sponsor-attributed activity observed in its run-date
update feed. Introductions/actions may carry up to three days of official
publication lag. This is governing context, not electoral sentiment.
"""

from __future__ import annotations

import base64
from collections import Counter
from datetime import date
import json
import os
from pathlib import Path

import functions_framework
from shared.supabase_client import get_supabase
from supabase import Client

import ad_spend
from congress_gov import get_daily_legislative_activity
import digital_ads
from fec import get_state_party_fundraising
from press_releases import extract_top_issue_terms, fetch_press_release_headlines
from repository import compute_source_hash, upsert_legislative_signal
from shared.tracing import get_tracer

tracer = get_tracer("legislative_signal")

_DELEGATIONS_PATH = Path(__file__).parent / "us_delegations.json"
_FEC_CYCLE = 2026
_CONGRESS = 119
_EXCLUDED_REGIONS = {"US-DC"}


def get_congress_api_key() -> str | None:
    return os.environ.get("CONGRESS_API_KEY")


def load_delegations() -> dict:
    return json.loads(_DELEGATIONS_PATH.read_text(encoding="utf-8"))


def state_code_to_postal(region: str) -> str:
    return region.split("-", 1)[1]


def _collect_rss_terms(members: list[dict], party: str) -> list[str]:
    headlines: list[str] = []
    for member in members:
        if member.get("party") == party and member.get("rss_url"):
            headlines.extend(fetch_press_release_headlines(member["rss_url"]))
    return extract_top_issue_terms(headlines)


def _party_activity(events: list[dict], party: str, delegation_size: int) -> dict:
    selected = [event for event in events if event["party"] == party]
    divisor = delegation_size or 1
    policy_areas = Counter(
        event["policy_area"] for event in selected if event.get("policy_area")
    )
    introduced = sum(bool(event["introduced"]) for event in selected)
    advanced = sum(bool(event["advanced"]) for event in selected)
    return {
        "introduced": introduced,
        "advanced": advanced,
        "introduced_per_member": introduced / divisor,
        "advanced_per_member": advanced / divisor,
        "policy_areas": [name for name, _ in policy_areas.most_common(5)],
    }


def process_state(
    region: str,
    run_date: str,
    delegation: dict,
    daily_events: list[dict],
    congress_coverage: bool,
    supabase: Client,
) -> None:
    postal = state_code_to_postal(region)
    representatives = delegation.get("representatives", [])
    state_events = [event for event in daily_events if event["state"] == postal]
    dem = _party_activity(state_events, "D", len(representatives))
    rep = _party_activity(state_events, "R", len(representatives))
    with tracer.start_as_current_span("fec.fetch", attributes={"region": region}):
        fec = get_state_party_fundraising(postal, _FEC_CYCLE)

    with tracer.start_as_current_span("press_releases.fetch", attributes={"region": region}):
        dem_issue_terms = _collect_rss_terms(representatives, "D")
        rep_issue_terms = _collect_rss_terms(representatives, "R")

    row = {
        "run_date": run_date,
        "region": region,
        "dem_bills_introduced": dem["introduced"] if congress_coverage else None,
        "rep_bills_introduced": rep["introduced"] if congress_coverage else None,
        "dem_bills_advanced": dem["advanced"] if congress_coverage else None,
        "rep_bills_advanced": rep["advanced"] if congress_coverage else None,
        "dem_introduced_per_member": dem["introduced_per_member"] if congress_coverage else None,
        "rep_introduced_per_member": rep["introduced_per_member"] if congress_coverage else None,
        "dem_advanced_per_member": dem["advanced_per_member"] if congress_coverage else None,
        "rep_advanced_per_member": rep["advanced_per_member"] if congress_coverage else None,
        "dem_policy_areas": dem["policy_areas"] if congress_coverage else None,
        "rep_policy_areas": rep["policy_areas"] if congress_coverage else None,
        "congress_coverage": 1.0 if congress_coverage else 0.0,
        "dem_fundraising": fec["dem_fundraising"],
        "rep_fundraising": fec["rep_fundraising"],
        "dem_issue_terms": dem_issue_terms,
        "rep_issue_terms": rep_issue_terms,
        "fec_coverage": fec["fec_coverage"],
    }
    row["source_hash"] = compute_source_hash(row)
    upsert_legislative_signal(supabase, row)
    print(f"legislative_signals upserted for {region} {run_date} (congress_coverage={row['congress_coverage']:.0f})")


@functions_framework.cloud_event
def gather_legislative_signals(cloud_event) -> None:
    payload = json.loads(base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8"))
    run_date = payload.get("date") or payload.get("run_date")

    if payload.get("refresh_digital"):
        run_date = run_date or date.today().isoformat()
        try:
            digital_ads.refresh_digital_spend(run_date, get_supabase())
        except digital_ads.DigitalSpendUnavailable as exc:
            # Log ERROR and return rather than raise. This subscription has no
            # dead-letter policy and a 600s max backoff, so raising would retry
            # for the 7-day retention window at 50 FEC calls per attempt --
            # enough to rate-limit the daily pipeline. Severity ERROR plus a
            # stable marker makes this alertable without the retry storm.
            print(json.dumps({
                "severity": "ERROR",
                "marker": "digital_spend_refresh_failed",
                "run_date": run_date,
                "message": str(exc),
            }))
        return

    if not run_date:
        print("Error: 'date' missing from legislative signal trigger payload.")
        return

    with tracer.start_as_current_span("gather_legislative_signals", attributes={"run_date": run_date}):
        supabase = get_supabase()
        delegations = load_delegations().get("states", {})
        with tracer.start_as_current_span("congress_gov.fetch", attributes={"run_date": run_date}):
            events, congress_coverage = get_daily_legislative_activity(
                run_date, _CONGRESS, get_congress_api_key()
            )

        processed = failed = 0
        for region, delegation in delegations.items():
            if region in _EXCLUDED_REGIONS:
                continue
            try:
                with tracer.start_as_current_span("process_state", attributes={"region": region}):
                    process_state(
                        region, run_date, delegation, events, congress_coverage, supabase
                    )
                try:
                    ad_spend.gather_state_ad_spend(region, run_date, supabase)
                except Exception as exc:
                    print(f"ad_spend degraded for {region} {run_date}: {exc}")
                processed += 1
            except Exception as exc:
                print(f"Error processing {region} {run_date}: {exc}")
                failed += 1
        print(f"Legislative signal gather complete for {run_date}: {processed} succeeded, {failed} failed.")
