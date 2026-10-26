"""Daily pipeline-health brief, sent once the day's run finishes its work.

Triggered by finalizer.publish_performance_brief_trigger() via
topic-performance-brief, right when the finalizer claims the day's export.
Reads pipeline-health metrics from Supabase and emails them directly via
Resend - independent of the emailer Cloud Function and its
customer-facing email_deliveries table.
"""
from __future__ import annotations

import base64
import json
import os
from urllib import request

import functions_framework
from shared.email_budget import EmailRecipientBudgetExhausted, reserve_recipients
from shared.supabase_client import get_supabase

from brief import render_brief
from metrics import (
    compute_gemini_fallback_usage,
    compute_legislative_coverage,
    compute_party_status,
    compute_run_duration_minutes,
    compute_stage_completion,
    compute_stage_issues,
)
from shared.tracing import get_tracer

tracer = get_tracer("performance_brief")

RESEND_API_URL = "https://api.resend.com/emails"
USER_AGENT = "newscloud-performance-brief/1.0"


def get_recipient() -> str:
    value = os.environ.get("PERFORMANCE_BRIEF_RECIPIENT")
    if not value:
        raise ValueError("PERFORMANCE_BRIEF_RECIPIENT must be set in environment variables")
    return value


def get_email_api_key() -> str:
    value = os.environ.get("EMAIL_API_KEY")
    if not value:
        raise ValueError("EMAIL_API_KEY must be set in environment variables")
    return value


def get_from_address() -> str:
    value = os.environ.get("EMAIL_FROM_ADDRESS")
    if not value:
        raise ValueError("EMAIL_FROM_ADDRESS must be set in environment variables")
    return value


def fetch_daily_run(run_date: str) -> dict | None:
    response = get_supabase().table("daily_runs").select("*").eq("run_date", run_date).limit(1).execute()
    return response.data[0] if response.data else None


def fetch_region_runs(run_date: str) -> list[dict]:
    response = get_supabase().table("region_runs").select("*").eq("run_date", run_date).execute()
    return response.data or []


def fetch_gemini_source_contributions(run_date: str) -> list[dict]:
    response = (
        get_supabase()
        .table("source_contributions")
        .select("status")
        .eq("date", run_date)
        .eq("provider", "gemini_google_search")
        .execute()
    )
    return response.data or []


def fetch_legislative_signals(run_date: str) -> list[dict]:
    response = (
        get_supabase()
        .table("legislative_signals")
        .select("fec_coverage,member_coverage")
        .eq("run_date", run_date)
        .execute()
    )
    return response.data or []


def fetch_party_syntheses(run_date: str) -> dict[str, dict]:
    response = (
        get_supabase()
        .table("party_syntheses")
        .select("audience,status,attempts")
        .eq("run_date", run_date)
        .execute()
    )
    return {row["audience"]: row for row in (response.data or [])}


def send_via_resend(*, subject: str, html_content: str, text_content: str) -> str:
    payload = {
        "from": get_from_address(),
        "to": [get_recipient()],
        "subject": subject,
        "html": html_content,
        "text": text_content,
    }
    # Pooled with the customer-facing senders, so reserve the recipient from the
    # shared Resend budget immediately before the provider request.
    if reserve_recipients(len(payload["to"]), sender="performance_brief") < 1:
        raise EmailRecipientBudgetExhausted("resend recipient budget exhausted")
    req = request.Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {get_email_api_key()}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body.get("id", "")


@functions_framework.cloud_event
def send_performance_brief(cloud_event):
    if "message" not in cloud_event.data or "data" not in cloud_event.data["message"]:
        print("Error: Message data missing from Cloud Event")
        return

    payload = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
    try:
        event_json = json.loads(payload)
    except json.JSONDecodeError:
        print("Error: Invalid JSON payload in Pub/Sub message")
        return

    run_date = event_json.get("run_date")
    if not run_date:
        print("Error: 'run_date' missing from performance brief trigger payload.")
        return

    with tracer.start_as_current_span("send_performance_brief", attributes={"run_date": run_date}):
        with tracer.start_as_current_span("supabase.fetch_metrics", attributes={"run_date": run_date}):
            daily_run = fetch_daily_run(run_date)
            if not daily_run:
                print(f"Error: no daily_runs row found for {run_date}; skipping performance brief.")
                return

            region_runs = fetch_region_runs(run_date)
            gemini_rows = fetch_gemini_source_contributions(run_date)
            legislative_rows = fetch_legislative_signals(run_date)
            party_rows = fetch_party_syntheses(run_date)

        expected_region_count = int(daily_run.get("expected_region_count") or 0)
        brief = render_brief(
            run_date=run_date,
            status=daily_run.get("status", "unknown"),
            duration_minutes=compute_run_duration_minutes(
                daily_run.get("created_at"), daily_run.get("export_claimed_at")
            ),
            stage_completion=compute_stage_completion(region_runs, expected_region_count),
            stage_issues=compute_stage_issues(region_runs),
            gemini_usage=compute_gemini_fallback_usage(gemini_rows),
            legislative_coverage=compute_legislative_coverage(legislative_rows, expected_region_count),
            party_status=compute_party_status(party_rows),
        )

        try:
            with tracer.start_as_current_span("resend.send", attributes={"run_date": run_date}):
                message_id = send_via_resend(
                    subject=brief["subject"],
                    html_content=brief["html"],
                    text_content=brief["text"],
                )
            print(f"Performance brief sent for {run_date} (message_id={message_id}).")
        except EmailRecipientBudgetExhausted as exc:
            # Pub/Sub would redeliver a raised error, but the shared budget is
            # already spent: acknowledge the event and skip today's brief.
            print(f"Performance brief paused for {run_date}: {exc}.")
        except Exception as exc:
            print(f"Error: failed to send performance brief for {run_date}: {exc}")
