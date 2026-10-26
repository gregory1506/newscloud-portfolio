"""Launch the immutable site-publisher Cloud Run Job from Pub/Sub."""

from __future__ import annotations

import base64
from datetime import date
import json
import os
import urllib.request

import functions_framework
import google.auth
from google.auth.transport.requests import Request as AuthRequest
from shared.env import require_env


VALID_MODES = {"shadow", "active"}


def allowed_mode() -> str:
    mode = os.environ.get("SITE_PUBLISHER_ALLOWED_MODE", "shadow").strip().lower()
    if mode not in VALID_MODES:
        raise RuntimeError(f"Unsupported SITE_PUBLISHER_ALLOWED_MODE: {mode}")
    return mode


def parse_event(cloud_event) -> dict | None:
    try:
        encoded = cloud_event.data["message"]["data"]
        payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"site_publisher_launcher ignored malformed event: {exc}")
        return None

    run_date = str(payload.get("run_date") or "")
    try:
        date.fromisoformat(run_date)
    except ValueError:
        print(f"site_publisher_launcher ignored invalid run_date: {run_date!r}")
        return None

    requested_mode = str(payload.get("mode") or "shadow").strip().lower()
    if requested_mode not in VALID_MODES:
        print(f"site_publisher_launcher ignored invalid mode: {requested_mode!r}")
        return None
    configured_mode = allowed_mode()
    if requested_mode != configured_mode:
        raise RuntimeError(
            f"publisher mode escalation rejected: requested={requested_mode} allowed={configured_mode}"
        )

    claim_id = str(payload.get("claim_id") or "").strip()
    if requested_mode == "active" and not claim_id:
        raise RuntimeError("active site publisher event requires claim_id")
    return {"run_date": run_date, "mode": requested_mode, "claim_id": claim_id}


def job_name() -> str:
    return (
        f"projects/{require_env('GCP_PROJECT')}/locations/"
        f"{os.environ.get('GCP_REGION', 'us-central1')}/jobs/"
        f"{os.environ.get('SITE_PUBLISHER_JOB', 'test-project-site-publisher')}"
    )


def launch_job(event: dict, *, opener=urllib.request.urlopen) -> str:
    env = [
        {"name": "RUN_DATE", "value": event["run_date"]},
        {"name": "SITE_PUBLISHER_MODE", "value": event["mode"]},
    ]
    if event["claim_id"]:
        env.append({"name": "EXPORT_CLAIM_ID", "value": event["claim_id"]})
    url = f"https://run.googleapis.com/v2/{job_name()}:run"
    headers = {"Content-Type": "application/json"}
    credentials, _project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    credentials.before_request(AuthRequest(), "POST", url, headers)
    request = urllib.request.Request(
        url,
        data=json.dumps({"overrides": {"containerOverrides": [{"env": env}]}}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with opener(request, timeout=30) as response:
        operation_name = str(json.loads(response.read().decode("utf-8")).get("name") or "")
    if not operation_name:
        raise RuntimeError("Cloud Run Jobs API returned no operation name")
    print(json.dumps({"event": "site_publisher_job_started", **event, "operation": operation_name}))
    return operation_name


@functions_framework.cloud_event
def launch_site_publisher(cloud_event):
    event = parse_event(cloud_event)
    if event is None:
        return
    launch_job(event)
