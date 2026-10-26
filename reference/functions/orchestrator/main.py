import functions_framework
import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from google import auth as google_auth
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import pubsub_v1
from shared.supabase_client import get_supabase
from shared.gcp_env import get_project_id
from shared.regions import ALL_REGIONS
from shared.districts import load_district_targets, select_district_targets
from shared.publication_schedule import publication_date_on_or_before

from shared.tracing import get_tracer

tracer = get_tracer("orchestrator")


PROJECT_ID = get_project_id()
DISTRICT_TOPIC_ID = "topic-gather-district"
DISTRICT_TARGETS_PATH = Path(__file__).with_name("district_targets_2026.json")
# Ad-spend rows for a run_date are written by the legislative-signal gather.
# Publishing its trigger at fan-out time (hours before party synthesis runs)
# guarantees money-vs-momentum reads attach; the finalizer still re-triggers at
# export-claim time to refresh the data for the export workflow.
LEGISLATIVE_SIGNAL_TOPIC_ID = "topic-gather-legislative-signals"

# Region fan-out goes through Cloud Tasks. The queue is the pacer: each task gets a
# fresh instance whose first provider call does not wait, so the scheduled times are
# what hold NewsData inside its per-window limit. Pub/Sub is no longer the
# orchestrator's path, but the topic stays wired - the finalizer republishes to
# topic-trigger-gatherer for recovery.
GATHER_QUEUE_ID = os.environ.get("NEWSCLOUD_GATHER_QUEUE", "region-gathers")
TASKS_LOCATION = os.environ.get("NEWSCLOUD_CLOUD_TASKS_LOCATION", "us-central1")
GATHER_TASK_URL = os.environ.get("NEWSCLOUD_GATHER_TASK_URL", "")
GATHER_TASK_SERVICE_ACCOUNT = os.environ.get("NEWSCLOUD_GATHER_TASK_SERVICE_ACCOUNT", "")
# Seconds between the scheduled times of consecutive region tasks. This is the
# pace that keeps NewsData inside its per-window limit; the queue's own rate is a
# slower safety net, because a queue's default burst of 10 would otherwise let ten
# gathers fire back to back as soon as they finish.
GATHER_TASK_SPACING_SECONDS = float(
    os.environ.get("NEWSCLOUD_GATHER_TASK_SPACING_SECONDS", "65")
)

REGIONS = list(ALL_REGIONS)

# Instantiate the Pub/Sub client globally to reuse connection pools
publisher = pubsub_v1.PublisherClient()
legislative_signal_topic_path = publisher.topic_path(PROJECT_ID, LEGISLATIVE_SIGNAL_TOPIC_ID)


def district_targets() -> list[str]:
    """Bounded district regions to gather, from the bundled target policy."""
    if not DISTRICT_TARGETS_PATH.exists():
        return []
    config = load_district_targets(DISTRICT_TARGETS_PATH)
    return select_district_targets(config.get("priority_regions", []), config)


def publish_district_fanout(run_date: str) -> None:
    targets = district_targets()
    if not targets:
        return
    topic_path = publisher.topic_path(PROJECT_ID, DISTRICT_TOPIC_ID)
    for region in targets:
        payload = json.dumps({"district": region, "date": run_date}).encode("utf-8")
        publisher.publish(topic_path, data=payload).result()
    print(f"Published {len(targets)} district gather messages for {run_date}.")


def enqueue_region_tasks(run_date: str) -> int:
    """Hand one Cloud Tasks task per region to the gatherer's HTTP entry point.

    The body is the same payload the topic carries, so the gatherer's validator and
    claim are unchanged. Cloud Tasks holds the tasks and its queue rate paces them.
    A failure here propagates: the fan-out must not report success while the day's
    gathering was never dispatched, and Pub/Sub redelivers when the handler fails.
    """
    if not GATHER_TASK_URL or not GATHER_TASK_SERVICE_ACCOUNT:
        raise RuntimeError(
            "NEWSCLOUD_GATHER_TASK_URL and NEWSCLOUD_GATHER_TASK_SERVICE_ACCOUNT "
            "must be set to dispatch region gathers through Cloud Tasks"
        )
    endpoint = (
        f"https://cloudtasks.googleapis.com/v2/projects/{PROJECT_ID}"
        f"/locations/{TASKS_LOCATION}/queues/{GATHER_QUEUE_ID}/tasks"
    )
    credentials, _ = google_auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.refresh(GoogleAuthRequest())
    base = datetime.now(timezone.utc)
    enqueued = 0
    for index, region in enumerate(REGIONS):
        scheduled = base + timedelta(seconds=index * GATHER_TASK_SPACING_SECONDS)
        payload = json.dumps({"region": region, "date": run_date}).encode("utf-8")
        task = {
            "task": {
                # Spacing the scheduled times is what paces the provider calls. A
                # queue's default burst of 10 would otherwise let ten gathers run
                # back to back the moment they finish, whatever the queue rate.
                "scheduleTime": scheduled.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "httpRequest": {
                    "httpMethod": "POST",
                    "url": GATHER_TASK_URL,
                    "headers": {"Content-Type": "application/json"},
                    "body": base64.b64encode(payload).decode("ascii"),
                    "oidcToken": {
                        "serviceAccountEmail": GATHER_TASK_SERVICE_ACCOUNT,
                        "audience": GATHER_TASK_URL,
                    },
                },
            }
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(task).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {credentials.token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30):
            enqueued += 1
    return enqueued


def build_region_run_rows(run_date: str) -> list[dict]:
    return [{"run_date": run_date, "region": region} for region in REGIONS]


def seed_region_runs(run_date: str, *, reset: bool):
    supabase = get_supabase()
    rows = build_region_run_rows(run_date)
    if reset:
        rows = [
            {
                "run_date": run_date,
                "region": region,
                "gatherer_status": "none",
                "scorer_status": "none",
                "generator_status": "none",
                "gatherer_attempts": 0,
                "scorer_attempts": 0,
                "generator_attempts": 0,
                "gatherer_recovery_attempts": 0,
                "scorer_recovery_attempts": 0,
                "generator_recovery_attempts": 0,
                "gatherer_last_error": None,
                "scorer_last_error": None,
                "generator_last_error": None,
                "gatherer_started_at": None,
                "scorer_started_at": None,
                "generator_started_at": None,
                "gatherer_completed_at": None,
                "scorer_completed_at": None,
                "generator_completed_at": None,
                "next_retry_at": None,
            }
            for region in REGIONS
        ]
    supabase.table("region_runs").upsert(rows, on_conflict="run_date,region").execute()


def build_district_run_rows(run_date: str) -> list[dict]:
    return [{"run_date": run_date, "district": district} for district in district_targets()]


def seed_district_runs(run_date: str, *, reset: bool):
    targets = district_targets()
    if not targets:
        return
    supabase = get_supabase()
    if reset:
        rows = [
            {
                "run_date": run_date,
                "district": district,
                "gatherer_status": "none",
                "gatherer_attempts": 0,
                "gatherer_started_at": None,
                "next_retry_at": None,
                "last_error": None,
            }
            for district in targets
        ]
    else:
        rows = build_district_run_rows(run_date)
    supabase.table("district_runs").upsert(rows, on_conflict="run_date,district").execute()


def initialize_daily_run(run_date: str):
    supabase = get_supabase()
    existing = (
        supabase.table("daily_runs")
        .select("run_date,status,published_at")
        .eq("run_date", run_date)
        .limit(1)
        .execute()
    )
    if existing.data:
        existing_run = existing.data[0]
        if existing_run.get("published_at") or existing_run.get("status") == "published":
            supabase.table("daily_runs").update(
                {
                    "expected_region_count": len(REGIONS),
                    "expected_regions": REGIONS,
                    "status": "running",
                    "completed_region_count": 0,
                    "failed_region_count": 0,
                    "last_reconciled_at": None,
                    "last_error": None,
                    "export_claim_id": None,
                    "export_claimed_at": None,
                    "published_at": None,
                }
            ).eq("run_date", run_date).execute()
            seed_district_runs(run_date, reset=True)
            seed_region_runs(run_date, reset=True)
            print(f"daily_runs already published for {run_date}; reopened run for republish.")
        else:
            seed_district_runs(run_date, reset=False)
            seed_region_runs(run_date, reset=False)
            print(f"daily_runs already exists for {run_date}; leaving barrier state unchanged.")
        return

    supabase.table("daily_runs").insert(
        {
            "run_date": run_date,
            "expected_region_count": len(REGIONS),
            "expected_regions": REGIONS,
            "status": "running",
            "completed_region_count": 0,
            "failed_region_count": 0,
        }
    ).execute()
    seed_district_runs(run_date, reset=False)
    seed_region_runs(run_date, reset=False)

@functions_framework.cloud_event
def orchestrate_pipeline(cloud_event):
    """
    Daily Scheduler heartbeat; fan out only on scheduled publication dates.
    """
    today = datetime.now(timezone.utc).date()
    run_date = today.isoformat()
    if publication_date_on_or_before(today) != today:
        print(json.dumps({
            "event": "orchestrator_publication_skipped",
            "run_date": run_date,
            "reason": "every_other_day",
            "next_run_date": (today + timedelta(days=1)).isoformat(),
        }))
        return "Skipped: non-publication day"
    with tracer.start_as_current_span(
        "orchestrate_pipeline", attributes={"run_date": run_date, "region_count": len(REGIONS)}
    ):
        initialize_daily_run(run_date)
        print(f"Orchestrator triggered. Fanning out to {len(REGIONS)} regions...")

        dispatched = enqueue_region_tasks(run_date)
        print(f"Dispatched {dispatched} region gathers for {run_date} via Cloud Tasks.")

        # Kick off the legislative-signal gather (FEC ad-spend, Congress.gov,
        # press releases) at fan-out time so ad_spend_signals rows exist before
        # party synthesis reads them later in the day. Publish failures here are
        # non-fatal: the finalizer re-triggers the gather at export-claim time.
        try:
            ls_payload = json.dumps({"date": run_date}).encode("utf-8")
            ls_future = publisher.publish(legislative_signal_topic_path, data=ls_payload)
            ls_future.result()
            print(f"Published legislative-signal trigger to {LEGISLATIVE_SIGNAL_TOPIC_ID} for {run_date}.")
        except Exception as exc:
            print(f"Legislative-signal trigger publish failed for {run_date}: {exc}")

        # Bounded district fan-out for the Race Board's House coverage.
        try:
            publish_district_fanout(run_date)
        except Exception as exc:
            print(f"District gather fan-out failed for {run_date}: {exc}")

        return "OK"

# deployment marker: workflow rebuild requested
