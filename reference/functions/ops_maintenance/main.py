import base64
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

import functions_framework
import google.auth
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token
import requests
from shared.districts import load_district_targets, select_district_targets
from shared.publication_schedule import publication_date_on_or_before
from shared.regions import ALL_REGIONS
from shared.supabase_client import get_supabase
from supabase import Client


MODE_SHADOW = "shadow"
MODE_ACTIVE = "active"
VALID_MODES = {MODE_SHADOW, MODE_ACTIVE}
TASK_NAME_EMAIL_RETRY = "email_retry"
TASK_NAME_EMAIL_AUDIT = "email_delivery_audit"
TASK_NAME_REGION_AUDIT = "region_site_audit"
TASK_NAME_RUN_HEALTH = "run_health"
TASK_NAME_NEWSDATA_COVERAGE = "newsdata_coverage"
TASK_NAME_ARTIFACT_REGISTRY = "artifact_registry_audit"
DEFAULT_RETRY_LIMIT = 10
DEFAULT_RETRY_INTERVAL_MINUTES = 60
DEFAULT_LEASE_SECONDS = 300
LOCAL_TIMEZONE = ZoneInfo("America/Port_of_Spain")
RUN_HEALTH_LOCAL_START = (13, 0)
RUN_PUBLISH_DEADLINE_LOCAL_START = (19, 0)
EMAIL_AUDIT_LOCAL_START = (19, 0)
REGION_AUDIT_LOCAL_START = (19, 30)
# Both gather sweeps are drained by then: the state fan-out paces at 65 seconds
# per region and the district fan-out at 65 seconds per district, so the long
# pole (79 districts) finishes about 86 minutes after the 15:00 UTC fan-out.
NEWSDATA_COVERAGE_LOCAL_START = (13, 0)
NEWSDATA_PROVIDER = "newsdata_io"
# Statuses the gatherers write when the shared credit reservation refused the
# provider call (see shared/newsdata_quota.py).
QUOTA_SOURCE_STATUSES = ("quota_deferred", "quota_exhausted")
# district_runs states that mean the district was tried and came back short.
DISTRICT_SHORT_STATUSES = ("failed", "deferred")
DISTRICT_TARGETS_PATH = Path(__file__).with_name("district_targets_2026.json")
BOARD_ARTIFACT_TYPE = "race_board_email"
BOARD_REGION = "national"
PARTY_LANE_AUDIENCES = {"party_email_democrat": "democrat", "party_email_republican": "republican"}
# Retired email products: from these run dates the product is off the live path,
# so a missing send is no longer a failure and a send is itself an anomaly.
BATTLEGROUND_EMAIL_RETIRED_FROM = "2026-09-13"
PARTY_LANE_EMAIL_RETIRED_FROM = "2026-09-20"
RUN_HEALTH_FAILED_MARKER = "run_health_failed"
NEWSDATA_COVERAGE_FAILED_MARKER = "newsdata_coverage_failed"
EMAIL_AUDIT_FAILED_MARKER = "email_delivery_audit_failed"
REGION_AUDIT_FAILED_MARKER = "region_site_audit_failed"
REGION_SITES = {
    "TT": "https://tt.example.invalid/",
    "UK": "https://uk.example.invalid/",
}
# Both region sites render the same brief; only copy differs, so each region
# declares its own copy marker plus the other region's copy marker and wordle
# title, which must not leak in.
BRIEF_SECTION_MARKERS = ("news-wordcloud", "top-issues", "wordle-game")
REGION_BRIEF_MARKERS = {
    "TT": {"copy": "Trinidad & Tobago", "foreign": ("United Kingdom", "UK News Wordle")},
    "UK": {"copy": "United Kingdom", "foreign": ("Trinidad", "Trini News Wordle")},
}


def log_event(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True, default=str))


def get_mode(name: str = "OPS_MAINTENANCE_MODE") -> str:
    mode = os.environ.get(name, os.environ.get("OPS_MAINTENANCE_MODE", MODE_SHADOW)).strip().lower()
    if mode not in VALID_MODES:
        raise ValueError(f"{name} must be one of: {', '.join(sorted(VALID_MODES))}")
    return mode


def get_retry_limit() -> int:
    value = int(os.environ.get("OPS_MAINTENANCE_RETRY_LIMIT", str(DEFAULT_RETRY_LIMIT)))
    if value < 1 or value > 100:
        raise ValueError("OPS_MAINTENANCE_RETRY_LIMIT must be between 1 and 100")
    return value


def get_retry_interval_minutes() -> int:
    value = int(
        os.environ.get(
            "OPS_MAINTENANCE_RETRY_INTERVAL_MINUTES",
            str(DEFAULT_RETRY_INTERVAL_MINUTES),
        )
    )
    if value not in {10, 20, 30, 60}:
        raise ValueError(
            "OPS_MAINTENANCE_RETRY_INTERVAL_MINUTES must be one of: 10, 20, 30, 60"
        )
    return value


def retry_sweep_is_due(now: datetime, *, interval_minutes: int) -> bool:
    return now.minute % interval_minutes == 0


def parse_scheduler_event(cloud_event) -> dict | None:
    message = (cloud_event.data or {}).get("message") or {}
    encoded = message.get("data")
    if not encoded:
        log_event("ops_maintenance_invalid_event", reason="missing_message_data")
        return None
    try:
        payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        log_event("ops_maintenance_invalid_event", reason="invalid_json")
        return None
    return payload


def fetch_due_retry_jobs(supabase: Client, *, now_iso: str, limit: int) -> list[dict]:
    fields = "id,run_date,target,channel,status,attempt_count,next_retry_at"
    pending_response = (
        supabase.table("delivery_jobs")
        .select(fields)
        .eq("status", "pending")
        .eq("channel", "email")
        .order("id")
        .limit(limit)
        .execute()
    )
    pending = pending_response.data or []
    remaining = max(0, limit - len(pending))
    if not remaining:
        return pending
    retry_response = (
        supabase.table("delivery_jobs")
        .select(fields)
        .eq("status", "retry_scheduled")
        .eq("channel", "email")
        .lte("next_retry_at", now_iso)
        .order("id")
        .limit(remaining)
        .execute()
    )
    return pending + (retry_response.data or [])


def retry_logical_key(job: dict) -> str:
    next_attempt = int(job.get("attempt_count") or 0) + 1
    return f"delivery_job:{int(job['id'])}:attempt:{next_attempt}"


def claim_task(
    supabase: Client,
    *,
    logical_key: str,
    now_iso: str,
    task_name: str = TASK_NAME_EMAIL_RETRY,
) -> str | None:
    response = supabase.rpc(
        "claim_scheduled_task",
        {
            "p_task_name": task_name,
            "p_logical_key": logical_key,
            "p_lease_seconds": DEFAULT_LEASE_SECONDS,
            "p_now": now_iso,
        },
    ).execute()
    value = response.data
    if isinstance(value, list):
        value = value[0] if value else None
    return str(value) if value else None


def finish_task(
    supabase: Client,
    *,
    logical_key: str,
    claim_token: str,
    status: str,
    details: dict,
    error: str | None = None,
    task_name: str = TASK_NAME_EMAIL_RETRY,
) -> bool:
    response = supabase.rpc(
        "finish_scheduled_task",
        {
            "p_task_name": task_name,
            "p_logical_key": logical_key,
            "p_claim_token": claim_token,
            "p_status": status,
            "p_details": details,
            "p_error": error,
        },
    ).execute()
    return bool(response.data)


def invoke_emailer(*, delivery_job_id: int) -> tuple[int, dict]:
    emailer_url = os.environ.get("EMAILER_URL")
    dispatch_token = os.environ.get("EMAIL_DISPATCH_TOKEN")
    if not emailer_url or not dispatch_token:
        raise ValueError("EMAILER_URL and EMAIL_DISPATCH_TOKEN must be set in active mode")

    identity_token = id_token.fetch_id_token(GoogleAuthRequest(), emailer_url)
    request_ = urllib.request.Request(
        emailer_url,
        data=json.dumps({"delivery_job_id": delivery_job_id}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {identity_token}",
            "Content-Type": "application/json",
            "X-Dispatch-Token": dispatch_token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request_, timeout=120) as response:
            return response.getcode(), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            body = {"error": raw}
        return exc.code, body


def process_due_retries(*, supabase: Client, mode: str, now: datetime) -> dict:
    now_iso = now.isoformat()
    jobs = fetch_due_retry_jobs(supabase, now_iso=now_iso, limit=get_retry_limit())
    selected_ids = [int(job["id"]) for job in jobs]
    summary = {
        "mode": mode,
        "selected_count": len(jobs),
        "selected_ids": selected_ids,
        "claimed_count": 0,
        "sent_count": 0,
        "skipped_claim_count": 0,
        "failure_count": 0,
    }

    if mode == MODE_SHADOW:
        return summary

    failures: list[str] = []
    for job in jobs:
        job_id = int(job["id"])
        logical_key = retry_logical_key(job)
        claim_token = claim_task(supabase, logical_key=logical_key, now_iso=now_iso)
        if not claim_token:
            summary["skipped_claim_count"] += 1
            continue
        summary["claimed_count"] += 1
        try:
            status_code, body = invoke_emailer(delivery_job_id=job_id)
            succeeded = status_code < 300 and not body.get("failed_count") and not body.get("failures")
            if not succeeded:
                raise RuntimeError(f"emailer returned HTTP {status_code}: {json.dumps(body, sort_keys=True)}")
            finish_task(
                supabase,
                logical_key=logical_key,
                claim_token=claim_token,
                status="succeeded",
                details={"delivery_job_id": job_id, "status_code": status_code},
            )
            summary["sent_count"] += int(body.get("sent_count") or 0)
        except Exception as exc:
            finish_task(
                supabase,
                logical_key=logical_key,
                claim_token=claim_token,
                status="failed",
                details={"delivery_job_id": job_id},
                error=str(exc),
            )
            summary["failure_count"] += 1
            failures.append(f"delivery_job_id={job_id}: {exc}")

    if failures:
        raise RuntimeError("; ".join(failures))
    return summary


def local_run_date(now: datetime) -> str:
    return now.astimezone(LOCAL_TIMEZONE).date().isoformat()


def is_at_or_after(now: datetime, threshold: tuple[int, int]) -> bool:
    return (now.hour, now.minute) >= threshold


def _paginate_rows(query) -> list[dict]:
    result = []
    while True:
        page = query.range(len(result), len(result) + 499).execute().data or []
        result.extend(page)
        if len(page) < 500:
            return result


def _email_audit_key(row: dict, target_field: str) -> tuple:
    return (row.get("artifact_type"), row.get("region"), row.get(target_field))


def _is_retired_email_audit_row(row: dict, run_date: str) -> bool:
    # Preserve pre-retirement audits. Starting with the next daily edition,
    # the retired product is no longer an expected send.
    artifact_type = row.get("artifact_type")
    if (run_date >= BATTLEGROUND_EMAIL_RETIRED_FROM and artifact_type == "email_brief"
            and row.get("region") == "battleground"):
        return True
    # The two party lanes were cut over to the single Race Board email, so from
    # the freeze date a lane send is the anomaly rather than a missing one.
    return run_date >= PARTY_LANE_EMAIL_RETIRED_FROM and artifact_type in PARTY_LANE_AUDIENCES


def _expected_email_deliveries(jobs: list[dict], subscriptions: list[dict], run_date: str) -> set[tuple]:
    expected = {_email_audit_key(job, "target") for job in jobs if not _is_retired_email_audit_row(job, run_date)}
    for subscription in subscriptions:
        if _is_retired_email_audit_row(subscription, run_date):
            continue
        kind = subscription.get("artifact_type")
        if kind in PARTY_LANE_AUDIENCES and subscription.get("audience") == PARTY_LANE_AUDIENCES[kind]:
            expected.add((kind, "all-states", subscription.get("target")))
        elif kind == BOARD_ARTIFACT_TYPE and subscription.get("region") == BOARD_REGION:
            expected.add((kind, BOARD_REGION, subscription.get("target")))
        elif kind == "email_brief" and subscription.get("region") == "battleground":
            expected.add(_email_audit_key(subscription, "target"))
    return expected


def _email_delivery_failures(
    expected: set[tuple], jobs: list[dict], deliveries: list[dict], run_date: str
) -> list[dict]:
    job_by_key = {_email_audit_key(job, "target"): job for job in jobs}
    audit_by_key = {_email_audit_key(row, "recipient_email"): row for row in deliveries}
    failures = []
    for item in sorted(expected):
        job = job_by_key.get(item, {})
        audit = audit_by_key.get(item, {})
        if (not item[2] or job.get("status") != "sent"
                or audit.get("status") != "sent"
                or not job.get("provider_message_id")
                or job.get("provider_message_id") != audit.get("provider_message_id")):
            # Report lane and region, without copying recipient addresses to logs.
            failures.append({"artifact_type": item[0], "region": item[1]})
    for delivery in deliveries:
        if _is_retired_email_audit_row(delivery, run_date) and delivery.get("status") == "sent":
            failures.append({"artifact_type": delivery["artifact_type"],
                             "region": delivery["region"], "reason": "retired_template_sent"})
    return failures


def fetch_email_audit_status(supabase: Client, *, run_date: str) -> dict:
    daily_response = (
        supabase.table("daily_runs")
        .select("run_date,status,completed_region_count,failed_region_count,published_at")
        .eq("run_date", run_date)
        .limit(1)
        .execute()
    )

    deliveries = _paginate_rows(
        supabase.table("email_deliveries")
        .select("artifact_type,region,recipient_email,status,provider_message_id")
        .eq("run_date", run_date)
        .order("id")
    )
    jobs = _paginate_rows(
        supabase.table("delivery_jobs")
        .select("artifact_type,region,target,status,provider_message_id")
        .eq("run_date", run_date).eq("channel", "email").order("id")
    )
    subscriptions = _paginate_rows(
        supabase.table("subscriptions")
        .select("artifact_type,region,target,audience")
        .eq("active", True).eq("channel", "email").order("id")
    )

    expected = _expected_email_deliveries(jobs, subscriptions, run_date)
    failures = _email_delivery_failures(expected, jobs, deliveries, run_date)
    daily_rows = daily_response.data or []
    return {
        "run_date": run_date,
        "ok": bool(expected) and not failures,
        "expected_delivery_count": len(expected),
        "sent_delivery_count": sum(row.get("status") == "sent" for row in deliveries),
        "failed_deliveries": failures,
        "daily_run": daily_rows[0] if daily_rows else None,
    }


def expected_gather_targets() -> list[str]:
    """The targets one scheduled pass should gather.

    Mirrors the orchestrator's fan-out: every state region plus the districts
    its target policy selects. A missing policy file means district gathering is
    off, so only the state regions are expected.
    """
    targets = list(ALL_REGIONS)
    if not DISTRICT_TARGETS_PATH.is_file():
        return targets
    config = load_district_targets(DISTRICT_TARGETS_PATH)
    targets.extend(select_district_targets(config.get("priority_regions", []), config))
    return targets


def fetch_newsdata_coverage(supabase: Client, *, run_date: str) -> dict[str, list[str]]:
    """Return ``{target: [status, ...]}`` for NewsData attempts on ``run_date``."""
    response = (
        supabase.table("source_contributions")
        .select("region,status")
        .eq("date", run_date)
        .eq("provider", NEWSDATA_PROVIDER)
        .execute()
    )
    coverage: dict[str, list[str]] = {}
    for row in response.data or []:
        coverage.setdefault(row["region"], []).append(row.get("status") or "")
    return coverage


def fetch_district_run_statuses(supabase: Client, *, run_date: str) -> dict[str, str]:
    """Return ``{district: gatherer_status}`` for the run date.

    Districts only write ``source_contributions`` when they have text, so an
    attempted district that produced nothing left no provenance row at all and
    the audit could not tell it apart from one the fan-out never reached. The
    ``district_runs`` row is written on every attempt, so it is the authority
    for whether a district was gathered.
    """
    response = (
        supabase.table("district_runs")
        .select("district,gatherer_status")
        .eq("run_date", run_date)
        .execute()
    )
    return {
        row["district"]: row.get("gatherer_status") or "none"
        for row in response.data or []
    }


def audit_newsdata_coverage(supabase: Client, *, run_date: str) -> dict:
    """Report targets the scheduled pass spent no usable NewsData credit on.

    Two failure modes matter and a quiet provider is not one of them:

    - a target with **no** attempt record never got its turn, so the fan-out
      missed it. For a district the record is the ``district_runs`` row, so an
      attempted-but-empty district is not mistaken for a missed one;
    - a target whose only rows are quota denials was refused by the shared
      reservation, which is the shortfall the free-tier ceilings trade against.
      A district also counts as short when its ``district_runs`` status is
      ``failed`` or ``deferred``.

    An ``empty`` row means the provider answered with nothing, which is normal.
    A denial never reaches here as ``empty`` because the gatherers record the
    quota status instead (see ``shared/newsdata_quota.py``).
    """
    expected = expected_gather_targets()
    coverage = fetch_newsdata_coverage(supabase, run_date=run_date)
    district_statuses = fetch_district_run_statuses(supabase, run_date=run_date)
    missing = [
        target
        for target in expected
        if target not in coverage
        and district_statuses.get(target, "none") == "none"
    ]
    denied = [
        target
        for target in expected
        if district_statuses.get(target) in DISTRICT_SHORT_STATUSES
        or (
            coverage.get(target)
            and all(status in QUOTA_SOURCE_STATUSES for status in coverage[target])
        )
    ]
    result = {
        "run_date": run_date,
        "expected_targets": len(expected),
        "observed_targets": sum(
            1
            for target in expected
            if target in coverage or district_statuses.get(target, "none") != "none"
        ),
        "missing_targets": missing,
        "denied_targets": denied,
        "empty_targets": sum(
            1
            for target in expected
            if coverage.get(target) and all(status == "empty" for status in coverage[target])
        ),
    }
    if missing or denied:
        raise RuntimeError(
            f"newsdata coverage short for {run_date}: {len(missing)} of "
            f"{len(expected)} target(s) never attempted, {len(denied)} denied by "
            f"quota; missing={missing[:5]} denied={denied[:5]}"
        )
    return result


def audit_email_delivery(supabase: Client, *, run_date: str) -> dict:
    result = fetch_email_audit_status(supabase, run_date=run_date)
    if not result["ok"]:
        raise RuntimeError(
            f"incomplete email delivery for {run_date}: "
            f"{len(result.get('failed_deliveries', []))} missing or inconsistent "
            f"of {result.get('expected_delivery_count', 0)} expected"
        )
    return result


def fetch_run_health(supabase: Client, *, run_date: str, now: datetime) -> dict:
    """Report whether the daily run is stalled or still unpublished.

    A stalled run is one that produced no region completions well past the
    15:00 UTC fan-out; an unpublished run is one whose publication never landed
    before the email audit claims. Both went unnoticed for two days in the
    September 18-19 outage, so each reports its own reason.
    """
    response = (
        supabase.table("daily_runs")
        .select("run_date,status,completed_region_count,failed_region_count,published_at")
        .eq("run_date", run_date)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    expected_region_count = len(ALL_REGIONS)
    local_now = now.astimezone(LOCAL_TIMEZONE)
    if not rows:
        stalled = is_at_or_after(local_now, RUN_HEALTH_LOCAL_START)
        return {
            "run_date": run_date,
            "ok": not stalled,
            "reason": "run_missing" if stalled else None,
            "completed_region_count": 0,
            "expected_region_count": expected_region_count,
            "status": None,
        }
    row = rows[0]
    completed = int(row.get("completed_region_count") or 0)
    published = bool(row.get("published_at"))
    if completed == 0 and is_at_or_after(local_now, RUN_HEALTH_LOCAL_START):
        reason = "run_stalled"
    elif (not published and completed < expected_region_count
          and is_at_or_after(local_now, RUN_PUBLISH_DEADLINE_LOCAL_START)):
        # A partial run never reaches the export claim, so nothing publishes and
        # no email goes out. Name it: "unpublished" would hide the missing regions.
        reason = "run_incomplete"
    elif not published and is_at_or_after(local_now, RUN_PUBLISH_DEADLINE_LOCAL_START):
        reason = "run_unpublished"
    else:
        reason = None
    return {
        "run_date": run_date,
        "ok": reason is None,
        "reason": reason,
        "completed_region_count": completed,
        "failed_region_count": int(row.get("failed_region_count") or 0),
        "expected_region_count": expected_region_count,
        "status": row.get("status"),
    }


def audit_run_health(supabase: Client, *, run_date: str, now: datetime) -> dict:
    result = fetch_run_health(supabase, run_date=run_date, now=now)
    if not result["ok"]:
        raise RuntimeError(
            f"{result['reason']} for {run_date}: "
            f"{result['completed_region_count']}/{result['expected_region_count']} regions "
            f"completed (status={result['status']})"
        )
    return result


def fetch_public_text(url: str) -> str:
    request_ = urllib.request.Request(
        url,
        headers={"Cache-Control": "no-cache", "User-Agent": "newscloud-ops-maintenance/1.0"},
    )
    with urllib.request.urlopen(request_, timeout=20) as response:
        content_type = response.headers.get_content_type()
        if "html" not in content_type:
            raise RuntimeError(f"{url} returned {content_type!r}, expected HTML")
        return response.read().decode("utf-8")


def verify_region_sites(*, run_date: str) -> dict:
    reports = {}
    for region, base_url in REGION_SITES.items():
        markers = REGION_BRIEF_MARKERS[region]
        body = fetch_public_text(base_url)
        # Copy markers are compared against the rendered text, not raw HTML entities.
        text = html.unescape(body)
        required = [
            f"Edition: {run_date}",
            *BRIEF_SECTION_MARKERS,
            f"archive/{run_date}/",
            markers["copy"],
        ]
        forbidden = list(markers["foreign"])
        archive = fetch_public_text(f"{base_url}archive/{run_date}/")
        if "Archived edition" not in archive or f"Edition: {run_date}" not in archive:
            raise RuntimeError(f"{region} archive does not match {run_date}")
        missing = [marker for marker in required if marker not in text]
        leaked = [marker for marker in forbidden if marker in text]
        if missing or leaked:
            raise RuntimeError(
                f"{region} contract failed for {run_date}: missing={missing}, leaked={leaked}"
            )
        reports[region] = {"url": base_url, "html_bytes": len(body.encode("utf-8"))}
    return {"run_date": run_date, "ok": True, "regions": reports}


def run_claimed_audit(
    supabase: Client,
    *,
    task_name: str,
    run_date: str,
    now: datetime,
    mode: str,
    audit,
) -> dict:
    if mode == MODE_SHADOW:
        result = audit()
        return {"mode": mode, "claimed": False, "result": result}

    claim_token = claim_task(
        supabase,
        task_name=task_name,
        logical_key=run_date,
        now_iso=now.isoformat(),
    )
    if not claim_token:
        return {"mode": mode, "claimed": False, "already_completed_or_running": True}
    try:
        result = audit()
        finish_task(
            supabase,
            task_name=task_name,
            logical_key=run_date,
            claim_token=claim_token,
            status="succeeded",
            details=result,
        )
        return {"mode": mode, "claimed": True, "result": result}
    except Exception as exc:
        finish_task(
            supabase,
            task_name=task_name,
            logical_key=run_date,
            claim_token=claim_token,
            status="failed",
            details={"run_date": run_date},
            error=str(exc),
        )
        raise


def run_daily_audit(
    supabase: Client,
    *,
    task_name: str,
    run_date: str,
    now: datetime,
    mode: str,
    marker: str,
    audit,
) -> dict:
    """Run one claimed audit, reporting failures as alertable log markers.

    An audit failure is a finding about the pipeline, not a fault of this
    function: it is logged with ``severity``/``marker`` so a log-based alert
    policy can route it, and deliberately not raised, so Pub/Sub does not
    redeliver the heartbeat and retry-storm the whole scan.
    """
    try:
        return run_claimed_audit(
            supabase,
            task_name=task_name,
            run_date=run_date,
            now=now,
            mode=mode,
            audit=audit,
        )
    except Exception as exc:
        return {"mode": mode, "error": str(exc), "severity": "ERROR", "marker": marker}


# Every worker subscription must bound its redelivery. Eventarc owns these
# subscriptions, so a Cloud Functions redeploy can silently reset the policy, and
# two September storms were exactly that: unbounded retries nobody noticed until
# the month was measured (legislative-signal on 09-12/13, the gatherer on
# 09-27..29). The churn alert detects the effect; this check detects the cause.
DELIVERY_POLICY_FAILED_MARKER = "delivery_policy_failed"
DELIVERY_POLICY_LOCAL_START = (20, 0)
TASK_NAME_DELIVERY_POLICY = "ops_maintenance_delivery_policy"
DELIVERY_POLICY_MAX_ATTEMPTS = 5
DELIVERY_POLICY_SHARED_TOPIC = "topic-gather-dead-letter"
# The dead-letter hold is a sink, not a worker: it carries no policy by design.
DELIVERY_POLICY_EXEMPT = ("gather-dead-letter-hold",)
PUBSUB_SCOPE = "https://www.googleapis.com/auth/pubsub"


def _pubsub_subscriptions(project: str) -> list[dict]:
    credentials, _ = google.auth.default(scopes=[PUBSUB_SCOPE])
    credentials.refresh(GoogleAuthRequest())
    response = requests.get(
        f"https://pubsub.googleapis.com/v1/projects/{project}/subscriptions",
        headers={"Authorization": f"Bearer {credentials.token}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("subscriptions", [])


def audit_delivery_policies(*, project: str | None = None) -> dict:
    """Report worker subscriptions that do not bound their redelivery.

    A subscription with no dead-letter policy and no maximum delivery attempt
    count retries until the message retention expires -- on the order of 1,000
    deliveries of one stuck message at a 600-second ack deadline over seven days.
    """
    project = project or os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or ""
    if not project:
        raise RuntimeError("no project id available for the delivery-policy audit")
    checked = 0
    unbounded = []
    for subscription in _pubsub_subscriptions(project):
        name = subscription["name"].rsplit("/", 1)[-1]
        if name in DELIVERY_POLICY_EXEMPT:
            continue
        checked += 1
        policy = subscription.get("deadLetterPolicy") or {}
        attempts = int(policy.get("maxDeliveryAttempts") or 0)
        if not policy.get("deadLetterTopic") or attempts > DELIVERY_POLICY_MAX_ATTEMPTS:
            unbounded.append(
                {
                    "subscription": name,
                    "dead_letter_topic": policy.get("deadLetterTopic"),
                    "max_delivery_attempts": attempts,
                }
            )
    if unbounded:
        raise RuntimeError(
            f"{len(unbounded)} of {checked} subscription(s) do not bound redelivery: "
            + ", ".join(item["subscription"] for item in unbounded)
        )
    return {
        "project": project,
        "checked": checked,
        "expected_topic": DELIVERY_POLICY_SHARED_TOPIC,
        "max_delivery_attempts": DELIVERY_POLICY_MAX_ATTEMPTS,
    }


ARTIFACT_REGISTRY_FAILED_MARKER = "artifact_registry_audit_failed"
# After the delivery-policy check, and after the day's deploys have settled.
ARTIFACT_REGISTRY_LOCAL_START = (20, 30)
ARTIFACT_REGISTRY_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
ARTIFACT_REGISTRY_DEFAULT_REGION = "us-central1"
# Repositories whose retention policy is load-bearing. Without one the version
# count drifts unboundedly between manual prunes -- that is how `gcf-artifacts`
# reached 61 versions unnoticed. `test-project-runtime` holds one package whose job
# is redeployed on every relevant push, so keeping ten is ample margin for the
# digests a live revision pins.
ARTIFACT_REGISTRY_REQUIRED_POLICIES = {
    "test-project-runtime": ("delete-older-than-30-days", "keep-recent-10"),
}


def _artifact_registry_token() -> str:
    credentials, _ = google.auth.default(scopes=[ARTIFACT_REGISTRY_SCOPE])
    credentials.refresh(GoogleAuthRequest())
    return credentials.token


def _artifact_pages(url: str, key: str, token: str) -> list[dict]:
    """Every item of a paginated Artifact Registry list.

    `dockerImages` returns 30 items per page with a `nextPageToken`, so a single
    request under-reports. The version count is this audit's drift signal, so it
    has to page: reading one page said 30 where the truth was 54.
    """
    items: list[dict] = []
    page_token = None
    while True:
        response = requests.get(
            url,
            params={"pageToken": page_token} if page_token else None,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        items.extend(payload.get(key, []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return items


def _artifact_repositories(project: str, region: str, token: str) -> list[str]:
    """Repository names in the region.

    `repositories.list` returns a reduced resource that omits `cleanupPolicies`
    and `registryUri`, so anything policy-related must be read back per repository.
    """
    return [
        item["name"]
        for item in _artifact_pages(
            f"https://artifactregistry.googleapis.com/v1/projects/{project}"
            f"/locations/{region}/repositories",
            "repositories",
            token,
        )
    ]


def _artifact_repository(repository: str, project: str, region: str, token: str) -> dict:
    """One repository's full resource, including its cleanup policies."""
    response = requests.get(
        f"https://artifactregistry.googleapis.com/v1/projects/{project}"
        f"/locations/{region}/repositories/{repository}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _artifact_version_count(repository: str, project: str, region: str, token: str) -> int:
    return len(
        _artifact_pages(
            f"https://artifactregistry.googleapis.com/v1/projects/{project}/locations/{region}"
            f"/repositories/{repository}/dockerImages",
            "dockerImages",
            token,
        )
    )


def audit_artifact_registry(
    *, project: str | None = None, region: str = ARTIFACT_REGISTRY_DEFAULT_REGION
) -> dict:
    """Report Artifact Registry usage and assert the retention policies exist.

    These repositories sit above the 0.5 GB free allowance *structurally* -- the
    live image footprint alone exceeds it -- so size is reported, not alerted on.
    What this does alert on is a missing cleanup policy: a policy is what bounds
    the version count between prunes. Pruning itself stays manual and explicit,
    because the safe criterion is a *computed reference set*
    (`scripts/prune_artifact_registry_images.py`) that a policy cannot express.
    """
    project = (
        project
        or os.environ.get("GCP_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or ""
    )
    if not project:
        raise RuntimeError("no project id available for the artifact registry audit")
    token = _artifact_registry_token()
    repositories = {}
    missing = []
    for resource_name in _artifact_repositories(project, region, token):
        name = resource_name.rsplit("/", 1)[-1]
        repository = _artifact_repository(name, project, region, token)
        policies = sorted((repository.get("cleanupPolicies") or {}).keys())
        repositories[name] = {
            "size_bytes": int(repository.get("sizeBytes") or 0),
            "versions": _artifact_version_count(name, project, region, token),
            "cleanup_policies": policies,
        }
        absent = [
            policy
            for policy in ARTIFACT_REGISTRY_REQUIRED_POLICIES.get(name, ())
            if policy not in policies
        ]
        if absent:
            missing.append({"repository": name, "missing_policies": absent})
    if missing:
        raise RuntimeError(
            "Artifact Registry retention policy missing: "
            + "; ".join(
                f"{item['repository']} needs {', '.join(item['missing_policies'])}"
                for item in missing
            )
        )
    return {"project": project, "region": region, "repositories": repositories}


def process_daily_audits(*, supabase: Client, mode: str, now: datetime) -> list[dict]:
    today = local_run_date(now)
    local_now = now.astimezone(LOCAL_TIMEZONE)
    run_date = publication_date_on_or_before(local_now.date()).isoformat()
    schedule = [
        (
            RUN_HEALTH_LOCAL_START,
            "ops_maintenance_run_health",
            TASK_NAME_RUN_HEALTH,
            RUN_HEALTH_FAILED_MARKER,
            run_date,
            lambda: audit_run_health(supabase, run_date=run_date, now=now),
        ),
        (
            NEWSDATA_COVERAGE_LOCAL_START,
            "ops_maintenance_newsdata_coverage",
            TASK_NAME_NEWSDATA_COVERAGE,
            NEWSDATA_COVERAGE_FAILED_MARKER,
            run_date,
            lambda: audit_newsdata_coverage(supabase, run_date=run_date),
        ),
        (
            EMAIL_AUDIT_LOCAL_START,
            "ops_maintenance_email_audit",
            TASK_NAME_EMAIL_AUDIT,
            EMAIL_AUDIT_FAILED_MARKER,
            run_date,
            lambda: audit_email_delivery(supabase, run_date=run_date),
        ),
        (
            REGION_AUDIT_LOCAL_START,
            "ops_maintenance_region_audit",
            TASK_NAME_REGION_AUDIT,
            REGION_AUDIT_FAILED_MARKER,
            run_date,
            lambda: verify_region_sites(run_date=run_date),
        ),
        (
            DELIVERY_POLICY_LOCAL_START,
            "ops_maintenance_delivery_policy",
            TASK_NAME_DELIVERY_POLICY,
            DELIVERY_POLICY_FAILED_MARKER,
            today,
            lambda: audit_delivery_policies(),
        ),
        (
            ARTIFACT_REGISTRY_LOCAL_START,
            "ops_maintenance_artifact_registry",
            TASK_NAME_ARTIFACT_REGISTRY,
            ARTIFACT_REGISTRY_FAILED_MARKER,
            today,
            lambda: audit_artifact_registry(),
        ),
    ]
    results = []
    for threshold, event, task_name, marker, audit_date, audit in schedule:
        if not is_at_or_after(local_now, threshold):
            continue
        result = run_daily_audit(
            supabase,
            task_name=task_name,
            run_date=audit_date,
            now=now,
            mode=mode,
            marker=marker,
            audit=audit,
        )
        results.append({"event": event, **result})
    return results


@functions_framework.cloud_event
def run_ops_maintenance(cloud_event) -> None:
    payload = parse_scheduler_event(cloud_event)
    if payload is None:
        return
    if payload.get("source") != "scheduler":
        log_event("ops_maintenance_ignored", source=payload.get("source") or "stage-event")
        return

    retry_mode = get_mode("OPS_MAINTENANCE_RETRY_MODE")
    audit_mode = get_mode("OPS_MAINTENANCE_AUDIT_MODE")
    now = datetime.now(timezone.utc)
    supabase = get_supabase()
    retry_failures = []
    retry_interval = get_retry_interval_minutes()
    if retry_sweep_is_due(now, interval_minutes=retry_interval):
        try:
            summary = process_due_retries(supabase=supabase, mode=retry_mode, now=now)
            log_event("ops_maintenance_retry_scan", observed_at=now.isoformat(), **summary)
        except Exception as exc:
            retry_failures.append(f"retry: {exc}")
            log_event("ops_maintenance_retry_failed", observed_at=now.isoformat(), error=str(exc))
    else:
        log_event(
            "ops_maintenance_retry_scan_skipped",
            observed_at=now.isoformat(),
            mode=retry_mode,
            interval_minutes=retry_interval,
            reason="outside_interval_boundary",
        )
    try:
        for result in process_daily_audits(supabase=supabase, mode=audit_mode, now=now):
            event = result.pop("event")
            log_event(event, observed_at=now.isoformat(), **result)
    except Exception as exc:
        log_event("ops_maintenance_audit_failed", observed_at=now.isoformat(), error=str(exc))
    if retry_failures:
        raise RuntimeError("; ".join(retry_failures))
