"""Pure pipeline-health metric computations for the performance-brief function.

No I/O — every function here takes plain dicts/lists (as returned from
Supabase queries in main.py) and returns plain dicts, so it can be unit
tested without mocking Supabase.
"""
from __future__ import annotations

from datetime import datetime

STAGES = ("gatherer", "scorer", "generator")
PARTY_AUDIENCES = ("democrat", "republican")


def compute_stage_completion(region_runs: list[dict], expected_region_count: int) -> dict:
    result = {}
    for stage in STAGES:
        completed = sum(1 for row in region_runs if row.get(f"{stage}_status") == "completed")
        attempts = sum(int(row.get(f"{stage}_attempts") or 0) for row in region_runs)
        recovery_attempts = sum(int(row.get(f"{stage}_recovery_attempts") or 0) for row in region_runs)
        result[stage] = {
            "completed": completed,
            "expected": expected_region_count,
            "attempts": attempts,
            "recovery_attempts": recovery_attempts,
        }
    return result


def compute_stage_issues(region_runs: list[dict], *, limit: int = 10) -> list[dict]:
    issues = []
    for row in region_runs:
        for stage in STAGES:
            error = row.get(f"{stage}_last_error")
            if error:
                issues.append({"region": row.get("region"), "stage": stage, "last_error": error})
    issues.sort(key=lambda item: (item["region"], item["stage"]))
    return issues[:limit]


def compute_gemini_fallback_usage(source_contribution_rows: list[dict]) -> dict:
    by_status = {"success": 0, "empty": 0, "error": 0}
    for row in source_contribution_rows:
        status = row.get("status")
        if status in by_status:
            by_status[status] += 1
    return {"total": len(source_contribution_rows), "by_status": by_status}


def compute_legislative_coverage(legislative_rows: list[dict], expected_region_count: int) -> dict:
    region_count = len(legislative_rows)
    coverage_fraction = region_count / expected_region_count if expected_region_count else 0.0
    fec_values = [float(row["fec_coverage"]) for row in legislative_rows if row.get("fec_coverage") is not None]
    member_values = [
        float(row["member_coverage"]) for row in legislative_rows if row.get("member_coverage") is not None
    ]
    avg_fec_coverage = sum(fec_values) / len(fec_values) if fec_values else 0.0
    avg_member_coverage = sum(member_values) / len(member_values) if member_values else 0.0
    return {
        "region_count": region_count,
        "expected_region_count": expected_region_count,
        "coverage_fraction": round(coverage_fraction, 4),
        "avg_fec_coverage": round(avg_fec_coverage, 4),
        "avg_member_coverage": round(avg_member_coverage, 4),
    }


def compute_party_status(party_rows: dict[str, dict]) -> dict:
    result = {}
    for audience in PARTY_AUDIENCES:
        row = party_rows.get(audience)
        if row:
            result[audience] = {"status": row.get("status", "missing"), "attempts": int(row.get("attempts") or 0)}
        else:
            result[audience] = {"status": "missing", "attempts": 0}
    return result


def compute_run_duration_minutes(created_at: str | None, export_claimed_at: str | None) -> float | None:
    if not created_at or not export_claimed_at:
        return None
    start = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(export_claimed_at.replace("Z", "+00:00"))
    return round((end - start).total_seconds() / 60.0, 1)
