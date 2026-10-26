import base64
from datetime import datetime, timedelta, timezone
import json
import os
import urllib.error
import urllib.request
import uuid

import functions_framework
from google.cloud import pubsub_v1
from shared.supabase_client import get_supabase
from shared.gcp_env import get_project_id

from pubsub_backlog import cached_undelivered_messages
from shared.tracing import get_tracer

tracer = get_tracer("finalizer")

GATHERER_TOPIC_ID = "topic-trigger-gatherer"
DOWNSTREAM_TOPIC_ID = "topic-generate-wordcloud"
LEGISLATIVE_SIGNAL_TOPIC_ID = "topic-gather-legislative-signals"
PERFORMANCE_BRIEF_TOPIC_ID = "topic-performance-brief"
SITE_PUBLISHER_TOPIC_ID = "topic-publish-sites"
MAX_STAGE_ATTEMPTS = 3
# Permit two bounded recovery cycles after the ordinary attempt budget. A single
# provider demand spike can outlast one three-attempt cycle, as happened for
# US-MT on 2026-06-30. The database claim still prevents concurrent retries.
MAX_STAGE_RECOVERIES = 2
# Two different failures need two different windows. A gatherer invocation is
# short -- one provider call behind a 65-second pacer, well inside the
# 300-second timeout -- so an invocation that started and has not finished after
# ten minutes is hung.
#
# A row still at ``none`` is normally *queued*, not stuck: the fan-out itself is
# the queue, drained by one instance per gatherer at 65 seconds per call, so the
# last district starts about 86 minutes after the fan-out. Judging a queued
# message by its creation time republished the backlog on every 10-minute nudge,
# and each duplicate spent a NewsData credit that the district sweep needed
# (~13 gather events per region on 2026-09-28). See
# docs/research/2026-09-26-free-tier-hardening-plan.md.
#
# A burst can also be *lost to the pipeline*: on 2026-09-30 a fan-out against a
# --max-instances=1 gatherer was refused with "no available instance". Those
# deliveries were retried to exhaustion and dead-lettered - the hold
# subscription kept 129 of them - while the gather subscriptions drained to
# zero, so 48 regions sat at zero attempts with nothing queued behind them. The
# backlog separates the two cases, so an empty backlog past this floor reads as
# dropped and is republished instead of waiting out the queued window. The floor
# stays above the metric's one-minute sampling so a fan-out is never mistaken
# for a drop.
GATHERER_RUNNING_STALE_MINUTES = 10
GATHERER_QUEUED_STALE_MINUTES = 120
GATHERER_DROPPED_STALE_MINUTES = 10
DOWNSTREAM_STALE_MINUTES = 10
GENERATOR_STALE_MINUTES = 15
SCHEDULER_SCAN_DAYS = int(os.environ.get("NEWSCLOUD_FINALIZER_SCAN_DAYS", "7"))
WATCHDOG_STATUSES = ["running", "failed", "completed", "export_claimed"]


def get_publisher() -> pubsub_v1.PublisherClient:
    return pubsub_v1.PublisherClient()


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_run_date() -> str:
    return utc_now().strftime("%Y-%m-%d")


def retry_backoff_minutes(attempts: int) -> int:
    if attempts <= 1:
        return 2
    return 5


def is_retry_due(region_run: dict, now: datetime) -> bool:
    next_retry_at = parse_timestamp(region_run.get("next_retry_at"))
    return next_retry_at is None or next_retry_at <= now


def is_stage_stale(
    region_run: dict, stage: str, now: datetime, *, backlog: float | None = None
) -> bool:
    """Is this stage's row stale enough to retry?

    ``backlog`` is the gatherer subscription's undelivered-message count, or
    ``None`` when it could not be read. Only the ``none`` case consults it: an
    empty backlog means the delivery was dropped rather than queued, which is the
    2026-09-30 failure. When it is ``None`` the conservative queued window wins.
    """
    status = region_run.get(f"{stage}_status")
    started_at = parse_timestamp(region_run.get(f"{stage}_started_at"))
    completed_at = parse_timestamp(region_run.get("gatherer_completed_at"))
    created_at = parse_timestamp(region_run.get("created_at"))
    if status == "running" and started_at:
        stale_minutes = (
            GENERATOR_STALE_MINUTES if stage == "generator" else GATHERER_RUNNING_STALE_MINUTES
        )
        return started_at <= now - timedelta(minutes=stale_minutes)
    if status == "none":
        if stage == "gatherer" and created_at:
            if backlog is not None and backlog <= 0:
                return created_at <= now - timedelta(minutes=GATHERER_DROPPED_STALE_MINUTES)
            return created_at <= now - timedelta(minutes=GATHERER_QUEUED_STALE_MINUTES)
        if stage in ("scorer", "generator") and completed_at:
            return completed_at <= now - timedelta(minutes=DOWNSTREAM_STALE_MINUTES)
    return False


def region_fully_completed(region_run: dict) -> bool:
    return all(
        region_run.get(f"{stage}_status") == "completed"
        for stage in ("gatherer", "scorer", "generator")
    )


def stage_exhausted(region_run: dict, stage: str) -> bool:
    status = region_run.get(f"{stage}_status")
    attempts = int(region_run.get(f"{stage}_attempts") or 0)
    return status != "completed" and attempts >= MAX_STAGE_ATTEMPTS


def fetch_daily_run(run_date: str) -> dict | None:
    supabase = get_supabase()
    response = (
        supabase.table("daily_runs")
        .select("*")
        .eq("run_date", run_date)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


def fetch_unpublished_daily_run_dates(
    *,
    days: int = SCHEDULER_SCAN_DAYS,
    current_only: bool = False,
) -> list[str]:
    since_date = (utc_now() - timedelta(days=days)).date().isoformat()
    supabase = get_supabase()
    query = (
        supabase.table("daily_runs")
        .select("run_date,status,published_at")
    )
    if current_only:
        query = query.eq("run_date", default_run_date())
    else:
        query = query.gte("run_date", since_date)
    response = (
        query.in_("status", WATCHDOG_STATUSES)
        .is_("published_at", "null")
        .order("run_date")
        .execute()
    )
    return [str(row["run_date"]) for row in (response.data or []) if row.get("run_date")]


def fetch_region_runs(run_date: str) -> list[dict]:
    supabase = get_supabase()
    response = (
        supabase.table("region_runs")
        .select("*")
        .eq("run_date", run_date)
        .execute()
    )
    return response.data or []


def fetch_frequencies(run_date: str, region: str) -> dict | None:
    supabase = get_supabase()
    response = (
        supabase.table("word_frequencies")
        .select("frequencies")
        .eq("date", run_date)
        .eq("region", region)
        .limit(1)
        .execute()
    )
    if response.data:
        return response.data[0].get("frequencies")
    return None


def claim_stage_retry(
    run_date: str,
    region: str,
    stage: str,
    attempts: int,
    *,
    allow_exhausted_recovery: bool = False,
) -> bool:
    supabase = get_supabase()
    next_retry_at = (utc_now() + timedelta(minutes=retry_backoff_minutes(attempts))).isoformat()
    response = supabase.rpc(
        "claim_region_stage_retry",
        {
            "p_run_date": run_date,
            "p_region": region,
            "p_stage": stage,
            "p_next_retry_at": next_retry_at,
            "p_max_attempts": MAX_STAGE_ATTEMPTS,
            "p_allow_recovery": allow_exhausted_recovery,
            "p_max_recoveries": MAX_STAGE_RECOVERIES,
        },
    ).execute()
    return bool(response.data)


def publish_gatherer_retry(run_date: str, region: str):
    publisher = get_publisher()
    topic_path = publisher.topic_path(get_project_id(), GATHERER_TOPIC_ID)
    payload = json.dumps({"region": region, "date": run_date}).encode("utf-8")
    future = publisher.publish(topic_path, data=payload)
    print(f"Republished gatherer retry {future.result()} for {region} {run_date}.")


def publish_legislative_signal_trigger(run_date: str) -> None:
    publisher = get_publisher()
    topic_path = publisher.topic_path(get_project_id(), LEGISLATIVE_SIGNAL_TOPIC_ID)
    payload = json.dumps({"date": run_date}).encode("utf-8")
    future = publisher.publish(topic_path, data=payload)
    print(f"Published legislative signal trigger {future.result()} for {run_date}.")


def publish_performance_brief_trigger(run_date: str) -> None:
    publisher = get_publisher()
    topic_path = publisher.topic_path(get_project_id(), PERFORMANCE_BRIEF_TOPIC_ID)
    payload = json.dumps({"run_date": run_date}).encode("utf-8")
    future = publisher.publish(topic_path, data=payload)
    print(f"Published performance brief trigger {future.result()} for {run_date}.")


def site_publication_owner() -> str:
    owner = os.environ.get("SITE_PUBLICATION_OWNER", "github").strip().lower()
    if owner not in {"github", "shadow", "gcp"}:
        raise ValueError(f"Unsupported SITE_PUBLICATION_OWNER: {owner}")
    return owner


def publish_site_publisher_trigger(run_date: str, *, mode: str, claim_id: str = "") -> None:
    publisher = get_publisher()
    topic_id = os.environ.get("SITE_PUBLISHER_TOPIC_ID", SITE_PUBLISHER_TOPIC_ID)
    topic_path = publisher.topic_path(get_project_id(), topic_id)
    payload = {"run_date": run_date, "mode": mode, "source": "finalizer"}
    if claim_id:
        payload["claim_id"] = claim_id
    future = publisher.publish(topic_path, data=json.dumps(payload).encode("utf-8"))
    print(f"Published site publisher {mode} trigger {future.result()} for {run_date}.")


def publish_downstream_retry(run_date: str, region: str, frequencies: dict):
    publisher = get_publisher()
    topic_path = publisher.topic_path(get_project_id(), DOWNSTREAM_TOPIC_ID)
    payload = json.dumps({"region": region, "date": run_date, "frequencies": frequencies}).encode("utf-8")
    future = publisher.publish(topic_path, data=payload)
    print(f"Republished downstream retry {future.result()} for {region} {run_date}.")


def update_daily_run_summary(run_date: str, region_runs: list[dict]) -> dict | None:
    daily_run = fetch_daily_run(run_date)
    if not daily_run:
        return None

    expected_count = int(daily_run.get("expected_region_count") or 0)
    completed_count = sum(1 for row in region_runs if region_fully_completed(row))
    failed_count = sum(
        1
        for row in region_runs
        if any(stage_exhausted(row, stage) for stage in ("gatherer", "scorer", "generator"))
    )
    current_status = daily_run.get("status")
    desired_status = current_status
    if current_status not in ("export_claimed", "published"):
        if completed_count >= expected_count and expected_count > 0:
            desired_status = "completed"
        elif failed_count > 0:
            desired_status = "failed"
        else:
            desired_status = "running"

    payload = {
        "completed_region_count": completed_count,
        "failed_region_count": failed_count,
        "last_reconciled_at": utc_now().isoformat(),
        "status": desired_status,
    }
    get_supabase().table("daily_runs").update(payload).eq("run_date", run_date).execute()
    daily_run.update(payload)
    return daily_run


def gatherer_backlog() -> float | None:
    """Undelivered messages waiting on the region gatherer's subscription(s).

    ``None`` means the metric could not be read, which keeps the age-based
    queued window as the fallback.
    """
    return cached_undelivered_messages(
        project=get_project_id(), include="gatherer", exclude="district"
    )


def _reconcile_gatherer_stage(
    run_date: str,
    region: str,
    region_run: dict,
    now,
    *,
    allow_exhausted_recovery: bool,
    backlog: float | None = None,
) -> None:
    gatherer_status = region_run.get("gatherer_status")
    attempts = int(region_run.get("gatherer_attempts") or 0)
    # `deferred` is a quota window denial: retryable, and counted against the
    # same attempt budget as a failure so a persistently denied region cannot
    # retry forever.
    exhausted = attempts >= MAX_STAGE_ATTEMPTS and gatherer_status in (
        "failed",
        "running",
        "deferred",
    )
    if exhausted and not allow_exhausted_recovery:
        return
    if backlog is None:
        backlog = gatherer_backlog()
    if gatherer_status in ("failed", "deferred") or is_stage_stale(
        region_run, "gatherer", now, backlog=backlog
    ):
        if is_retry_due(region_run, now):
            claimed = claim_stage_retry(
                run_date,
                region,
                "gatherer",
                attempts,
                allow_exhausted_recovery=allow_exhausted_recovery,
            )
            if claimed:
                publish_gatherer_retry(run_date, region)


def _reconcile_downstream_stage(run_date: str, region: str, region_run: dict, now, *, allow_exhausted_recovery: bool) -> None:
    scorer_status = region_run.get("scorer_status")
    generator_status = region_run.get("generator_status")
    downstream_incomplete = scorer_status != "completed" or generator_status != "completed"
    if not downstream_incomplete:
        return

    scorer_attempts = int(region_run.get("scorer_attempts") or 0)
    generator_attempts = int(region_run.get("generator_attempts") or 0)
    retry_stage = "scorer" if scorer_status != "completed" else "generator"
    retry_attempts = scorer_attempts if retry_stage == "scorer" else generator_attempts
    retry_status = scorer_status if retry_stage == "scorer" else generator_status
    exhausted = retry_attempts >= MAX_STAGE_ATTEMPTS and retry_status in ("failed", "running")
    if exhausted and not allow_exhausted_recovery:
        return

    retry_needed = (
        scorer_status == "failed"
        or generator_status == "failed"
        or is_stage_stale(region_run, "scorer", now)
        or is_stage_stale(region_run, "generator", now)
    )
    if not retry_needed or not is_retry_due(region_run, now):
        return

    frequencies = fetch_frequencies(run_date, region)
    if not frequencies:
        print(f"Cannot republish downstream for {region} {run_date}; frequencies missing.")
        return

    claimed = claim_stage_retry(
        run_date,
        region,
        retry_stage,
        retry_attempts,
        allow_exhausted_recovery=allow_exhausted_recovery,
    )
    if claimed:
        publish_downstream_retry(run_date, region, frequencies)


# District reconciliation. Districts gate nothing - they feed the board's
# district coverage - so this runs after the region stages and never blocks
# publication. It exists because on 2026-09-30 the whole district fan-out was
# dead-lettered: the dead-letter alert fired within minutes, but nothing recorded
# *which* districts were affected. `district_runs` did not exist then, so a
# district that was never reached looked exactly like one that reported nothing,
# and the coverage audit could not tell the loss apart from its chronic
# shortfall.
DISTRICT_TOPIC_ID = "topic-gather-district"
DISTRICT_RUNS_TABLE = "district_runs"
DISTRICT_CLAIM_RPC = "claim_district_gather"


def district_backlog() -> float | None:
    """Undelivered messages waiting on the district gatherer's subscription."""
    return cached_undelivered_messages(project=get_project_id(), include="gatherer-district")


def fetch_district_runs(run_date: str) -> list[dict]:
    """District rows for a run date; empty while the table is not deployed yet."""
    try:
        response = (
            get_supabase()
            .table(DISTRICT_RUNS_TABLE)
            .select("*")
            .eq("run_date", run_date)
            .execute()
        )
    except Exception as exc:
        print(f"district_runs unavailable for {run_date}: {exc}")
        return []
    return response.data or []


def claim_district_gather(run_date: str, district: str) -> bool:
    """Claim one district delivery: only ``claimed`` owns the provider call."""
    response = (
        get_supabase()
        .rpc(
            DISTRICT_CLAIM_RPC,
            {
                "p_run_date": run_date,
                "p_district": district,
                "p_stale_minutes": GATHERER_RUNNING_STALE_MINUTES,
            },
        )
        .execute()
    )
    return response.data == "claimed"


def publish_district_retry(run_date: str, district: str) -> None:
    publisher = get_publisher()
    topic_path = publisher.topic_path(get_project_id(), DISTRICT_TOPIC_ID)
    payload = json.dumps({"district": district, "date": run_date}).encode("utf-8")
    future = publisher.publish(topic_path, data=payload)
    print(f"Republished district retry {future.result()} for {district} {run_date}.")


def reconcile_districts(run_date: str, *, backlog: float | None = None) -> int:
    """Republish district deliveries the pipeline never got; returns the count.

    Uses the same windows as the region stages, including the backlog fast path,
    and the same attempt budget so a permanently failing district is recorded as
    short rather than retried forever.
    """
    rows = fetch_district_runs(run_date)
    if not rows:
        return 0
    if backlog is None:
        backlog = district_backlog()
    now = utc_now()
    republished = 0
    for row in rows:
        status = row.get("gatherer_status")
        if status == "completed":
            continue
        attempts = int(row.get("gatherer_attempts") or 0)
        if attempts >= MAX_STAGE_ATTEMPTS and status in ("failed", "running", "deferred"):
            continue
        if status not in ("failed", "deferred") and not is_stage_stale(
            row, "gatherer", now, backlog=backlog
        ):
            continue
        district = row["district"]
        if claim_district_gather(run_date, district):
            publish_district_retry(run_date, district)
            republished += 1
    return republished


def reconcile_run(run_date: str, *, allow_exhausted_recovery: bool = False):
    region_runs = fetch_region_runs(run_date)
    now = utc_now()
    # One read per pass: the answer is the same for every row, and doing it here
    # means each active run logs the backlog, which is the only way to tell from
    # the outside whether the in-function metric read works at all.
    backlog = gatherer_backlog()
    for region_run in region_runs:
        region = region_run["region"]
        gatherer_status = region_run.get("gatherer_status")

        if gatherer_status in ("none", "failed", "running", "deferred"):
            _reconcile_gatherer_stage(
                run_date,
                region,
                region_run,
                now,
                allow_exhausted_recovery=allow_exhausted_recovery,
                backlog=backlog,
            )
            continue

        _reconcile_downstream_stage(
            run_date, region, region_run, now, allow_exhausted_recovery=allow_exhausted_recovery
        )

    republished = reconcile_districts(run_date)
    if republished:
        print(f"Republished {republished} district deliveries for {run_date}.")

    return update_daily_run_summary(run_date, fetch_region_runs(run_date))


def get_github_config() -> dict[str, str]:
    token = os.environ.get("GITHUB_WORKFLOW_TOKEN")
    owner = os.environ.get("GITHUB_OWNER")
    repo = os.environ.get("GITHUB_REPO")
    workflow_id = os.environ.get("GITHUB_WORKFLOW_ID", "export-site-data.yml")
    ref = os.environ.get("GITHUB_REF", "main")
    if not token or not owner or not repo:
        raise ValueError("GITHUB_WORKFLOW_TOKEN, GITHUB_OWNER, and GITHUB_REPO must be set")
    return {
        "token": token,
        "owner": owner,
        "repo": repo,
        "workflow_id": workflow_id,
        "ref": ref,
    }


def claim_site_export(run_date: str, claim_id: str) -> bool:
    supabase = get_supabase()
    response = supabase.rpc(
        "claim_site_export",
        {"p_run_date": run_date, "p_claim_id": claim_id},
    ).execute()
    return bool(response.data)


def release_site_export_claim(run_date: str, claim_id: str) -> bool:
    supabase = get_supabase()
    response = supabase.rpc(
        "release_site_export_claim",
        {"p_run_date": run_date, "p_claim_id": claim_id},
    ).execute()
    return bool(response.data)


def dispatch_export_workflow(run_date: str, claim_id: str, *, workflow_id: str | None = None,
                             extra_inputs: dict | None = None):
    github = get_github_config()
    url = (
        f"https://api.github.com/repos/{github['owner']}/{github['repo']}/"
        f"actions/workflows/{workflow_id or github['workflow_id']}/dispatches"
    )
    payload = json.dumps(
        {
            "ref": github["ref"],
            "inputs": {"run_date": run_date, "claim_id": claim_id, **(extra_inputs or {})},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {github['token']}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30):
        return


def parse_finalizer_event(cloud_event) -> dict | None:
    if "message" not in cloud_event.data or "data" not in cloud_event.data["message"]:
        print("Error: Message data missing from Cloud Event")
        return None

    payload = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    try:
        event_json = json.loads(payload)
    except json.JSONDecodeError:
        print("Error: Invalid JSON payload in Pub/Sub message")
        return None

    source = event_json.get("source") or "stage-event"
    run_date = event_json.get("date")
    scan_unpublished = source == "scheduler" and not run_date
    if scan_unpublished:
        print("Scheduler nudge missing date; scanning recent unpublished daily runs.")
    if not run_date:
        if not scan_unpublished:
            print("Error: 'date' is required.")
            return None

    return {
        "run_date": run_date,
        "region": event_json.get("region"),
        "stage": event_json.get("stage"),
        "stage_status": event_json.get("status"),
        "source": source,
        "scan_unpublished": scan_unpublished,
    }


def _run_ready_to_export(daily_run: dict, run_date: str, event: dict) -> bool:
    if daily_run.get("status") not in ("completed", "export_claimed", "published"):
        print(
            f"Run {run_date} is not ready to export yet. "
            f"Event source={event['source']} region={event['region']} "
            f"stage={event['stage']} status={event['stage_status']}"
        )
        return False
    if daily_run.get("status") == "published":
        print(
            f"Run {run_date} already published. "
            f"Event source={event['source']} region={event['region']} "
            f"stage={event['stage']} status={event['stage_status']}"
        )
        return False
    return True


def _dispatch_site_export(run_date: str, claim_id: str, publication_owner: str) -> None:
    # Race scoring moved into the site publisher: it runs immediately before the
    # board export that reads the snapshots (jobs/site_publisher/race_board.py).

    publish_legislative_signal_trigger(run_date)
    if publication_owner == "shadow":
        publish_site_publisher_trigger(run_date, mode="shadow")
    if publication_owner in {"github", "shadow"}:
        with tracer.start_as_current_span(
            "github.dispatch_export_workflow", attributes={"run_date": run_date, "claim_id": claim_id}
        ):
            dispatch_export_workflow(run_date, claim_id)
    else:
        publish_site_publisher_trigger(run_date, mode="active", claim_id=claim_id)
    publish_performance_brief_trigger(run_date)


def process_run_date(event: dict, run_date: str) -> bool:
    print(
        f"Reconciling run_date={run_date} from source={event['source']} "
        f"region={event['region']} stage={event['stage']} status={event['stage_status']}"
    )

    is_current_run = run_date == default_run_date()
    with tracer.start_as_current_span("reconcile_run", attributes={"run_date": run_date}):
        daily_run = reconcile_run(
            run_date,
            allow_exhausted_recovery=event["source"] == "scheduler" and is_current_run,
        )
    if not daily_run:
        print(
            f"Run {run_date} does not exist. "
            f"Event source={event['source']} region={event['region']} "
            f"stage={event['stage']} status={event['stage_status']}"
        )
        return False

    if not is_current_run:
        print(
            f"Run {run_date} is historical; automatic export is suppressed. "
            "Use an explicit export workflow dispatch for historical publication."
        )
        return False

    if not _run_ready_to_export(daily_run, run_date, event):
        return False

    # Validate config before touching run state so misconfiguration does not orphan claims.
    publication_owner = site_publication_owner()
    if publication_owner in {"github", "shadow"}:
        get_github_config()
    if publication_owner in {"shadow", "gcp"}:
        get_project_id()

    claim_id = str(uuid.uuid4())
    claimed = claim_site_export(run_date, claim_id)
    if not claimed:
        print(
            f"Run {run_date} is not ready to export yet. "
            f"Event source={event['source']} region={event['region']} "
            f"stage={event['stage']} status={event['stage_status']}"
        )
        return False

    try:
        _dispatch_site_export(run_date, claim_id, publication_owner)
        print(
            f"Triggered site publication owner={publication_owner} "
            f"for run_date={run_date} with claim_id={claim_id}"
        )
        return True
    except urllib.error.HTTPError as exc:
        release_site_export_claim(run_date, claim_id)
        body = exc.read().decode("utf-8", errors="replace")
        print(f"GitHub workflow dispatch failed: {exc.code} {body}")
        raise
    except Exception:
        release_site_export_claim(run_date, claim_id)
        raise


@functions_framework.cloud_event
def finalize_daily_run(cloud_event):
    event = parse_finalizer_event(cloud_event)
    if not event:
        return

    if event["scan_unpublished"]:
        run_dates = fetch_unpublished_daily_run_dates(current_only=True)
        if not run_dates:
            print("Scheduler nudge found no unpublished daily runs to reconcile.")
            return
        print(f"Scheduler nudge reconciling unpublished daily runs: {', '.join(run_dates)}")
        for run_date in run_dates:
            with tracer.start_as_current_span("process_run_date", attributes={"run_date": run_date}):
                dispatched = process_run_date(event, run_date)
            if dispatched:
                print("Scheduler nudge dispatched one export workflow; remaining dates will wait for a later nudge.")
                break
        return

    with tracer.start_as_current_span("process_run_date", attributes={"run_date": event["run_date"]}):
        process_run_date(event, event["run_date"])

# deployment marker: workflow rebuild requested
