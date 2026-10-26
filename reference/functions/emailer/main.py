import json
import os
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from urllib import error, parse, request

import functions_framework
from shared.email_budget import (
    BUDGET_EXHAUSTED_EVENT,
    EmailRecipientBudgetExhausted,
    reserve_recipients,
)
from shared.supabase_client import get_supabase

from emailer_object_store import (
    get_bytes as get_r2_bytes,
    storage_provider,
)

from shared.tracing import get_tracer
from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace

tracer = get_tracer("emailer")


EMAIL_PROVIDER_RESEND = "resend"
RESEND_API_URL = "https://api.resend.com/emails"
RESEND_USER_AGENT = "newscloud-emailer/1.0"
DELIVERY_STATUS_SENDING = "sending"
DELIVERY_STATUS_SENT = "sent"
DELIVERY_STATUS_FAILED = "failed"
DELIVERY_STATUS_RETRY_SCHEDULED = "retry_scheduled"
DELIVERY_STATUS_SKIPPED = "skipped"
DEFAULT_RETRY_DELAY_MINUTES = 15
DEFAULT_MAX_ATTEMPTS = 3
EMAIL_ARTIFACT_REGION = "battleground"
EMAIL_ARTIFACT_TYPE = "email_brief"
ARTIFACT_BUCKET = "artifacts"


def battleground_email_enabled() -> bool:
    # Retired September 12, 2026. Only an explicit operator rollout can restore
    # this product; force_resend must never bypass the retirement gate.
    return os.environ.get("BATTLEGROUND_EMAIL_ENABLED", "false").lower() == "true"


def retired_response() -> tuple[dict, int]:
    return {"sent_count": 0, "skipped_count": 1, "failed_count": 0,
            "reason": "battleground_template_retired"}, 200


def get_dispatch_token() -> str:
    token = os.environ.get("EMAIL_DISPATCH_TOKEN")
    if not token:
        raise ValueError("EMAIL_DISPATCH_TOKEN must be set in environment variables")
    return token


def get_email_provider() -> str:
    return os.environ.get("EMAIL_PROVIDER", EMAIL_PROVIDER_RESEND).strip().lower()


def get_email_api_key() -> str:
    key = os.environ.get("EMAIL_API_KEY")
    if not key:
        raise ValueError("EMAIL_API_KEY must be set in environment variables")
    return key


def get_from_address() -> str:
    value = os.environ.get("EMAIL_FROM_ADDRESS")
    if not value:
        raise ValueError("EMAIL_FROM_ADDRESS must be set in environment variables")
    return value


def get_reply_to_address() -> str | None:
    value = os.environ.get("EMAIL_REPLY_TO")
    return value or None


def get_subject_prefix() -> str:
    value = os.environ.get("EMAIL_SUBJECT_PREFIX")
    if value is None:
        return "NewsCloud | "
    return value or "NewsCloud | "


def get_user_agent() -> str:
    return os.environ.get("EMAIL_USER_AGENT", RESEND_USER_AGENT).strip() or RESEND_USER_AGENT


def get_unsubscribe_url() -> str:
    return os.environ.get("NEWSCLOUD_UNSUBSCRIBE_URL", "").strip()


def get_unsubscribe_mailto() -> str:
    return os.environ.get("EMAIL_UNSUBSCRIBE_MAILTO", "").strip()


def build_unsubscribe_headers(recipient: str) -> dict[str, str]:
    """RFC 8058 one-click unsubscribe headers, when configured.

    Emits ``List-Unsubscribe`` for the configured HTTPS page and/or mailto, and
    ``List-Unsubscribe-Post`` only when an HTTPS target exists (mailbox
    providers POST ``List-Unsubscribe=One-Click`` to that URL).
    """
    url = get_unsubscribe_url()
    mailto = get_unsubscribe_mailto()
    targets: list[str] = []
    if url:
        targets.append(f"<{url}?email={parse.quote(recipient, safe='')}>")
    if mailto:
        targets.append(f"<mailto:{mailto}?subject=unsubscribe>")
    if not targets:
        return {}
    headers = {"List-Unsubscribe": ", ".join(targets)}
    if url:
        headers["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    return headers


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_dispatch_token(received_token: str | None) -> None:
    expected = get_dispatch_token()
    if not received_token or received_token != expected:
        raise PermissionError("Unauthorized dispatch token.")


def validate_email_address(value: str) -> str:
    _, parsed = parseaddr(value or "")
    if not parsed or "@" not in parsed:
        raise ValueError(f"Invalid email address: {value!r}")
    return parsed


def build_default_subject(run_date: str) -> str:
    dt = datetime.strptime(run_date, "%Y-%m-%d")
    return f"{get_subject_prefix()}Battleground Morning Brief | {dt.strftime('%b %d, %Y')}"


def get_retry_delay_minutes() -> int:
    value = os.environ.get("EMAIL_RETRY_DELAY_MINUTES")
    if value is None:
        return DEFAULT_RETRY_DELAY_MINUTES
    delay = int(value)
    if delay < 1:
        raise ValueError("EMAIL_RETRY_DELAY_MINUTES must be at least 1.")
    return delay


def get_max_attempts() -> int:
    value = os.environ.get("EMAIL_MAX_ATTEMPTS")
    if value is None:
        return DEFAULT_MAX_ATTEMPTS
    attempts = int(value)
    if attempts < 1:
        raise ValueError("EMAIL_MAX_ATTEMPTS must be at least 1.")
    return attempts


def fetch_active_recipients() -> list[dict]:
    response = (
        get_supabase()
        .table("email_recipients")
        .select("email,name,client_name,delivery_format,subject_override,metadata")
        .eq("active", True)
        .order("email")
        .execute()
    )
    return response.data or []


def fetch_recipient_by_email(email: str) -> dict | None:
    response = (
        get_supabase()
        .table("email_recipients")
        .select("email,name,client_name,active,delivery_format,subject_override,metadata")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def fetch_subscription_recipient(
    *, target: str, channel: str, region: str, artifact_type: str
) -> dict | None:
    response = (
        get_supabase()
        .table("subscriptions")
        .select("target,active,metadata")
        .eq("target", target)
        .eq("channel", channel)
        .eq("region", region)
        .eq("artifact_type", artifact_type)
        .eq("active", True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return None
    row = rows[0]
    return {
        "email": row["target"],
        "name": None,
        "client_name": None,
        "active": row["active"],
        "delivery_format": "email_html",
        "subject_override": None,
        "metadata": row.get("metadata") or {},
    }


def filter_recipients(recipients: list[dict], allowed_emails: list[str] | None) -> list[dict]:
    if not allowed_emails:
        return recipients

    normalized = [validate_email_address(email) for email in allowed_emails]
    allowed_set = set(normalized)
    filtered = [recipient for recipient in recipients if recipient.get("email") in allowed_set]
    missing = sorted(allowed_set - {recipient.get("email") for recipient in filtered})
    if missing:
        raise ValueError(
            "Requested recipient_emails are not active recipients: " + ", ".join(missing)
        )
    return filtered


def fetch_existing_deliveries(
    run_date: str,
    *,
    region: str = EMAIL_ARTIFACT_REGION,
    artifact_type: str = EMAIL_ARTIFACT_TYPE,
) -> dict[str, dict]:
    response = (
        get_supabase()
        .table("email_deliveries")
        .select(
            "recipient_email,status,provider_message_id,error_message,metadata,"
            "attempt_count,next_retry_at,last_attempt_at"
        )
        .eq("run_date", run_date)
        .eq("region", region)
        .eq("artifact_type", artifact_type)
        .execute()
    )
    return {
        row["recipient_email"]: row
        for row in (response.data or [])
    }


def fetch_delivery_job(job_id: int) -> dict | None:
    response = (
        get_supabase()
        .table("delivery_jobs")
        .select(
            "id,run_date,region,artifact_type,channel,target,status,provider,provider_message_id,"
            "subject,error_message,metadata,attempt_count,last_attempt_at,next_retry_at,sent_at"
        )
        .eq("id", job_id)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def upsert_delivery_job(
    *,
    job: dict,
    job_id: int,
    status: str,
    provider: str | None = None,
    subject: str | None = None,
    provider_message_id: str | None = None,
    error_message: str | None = None,
    metadata: dict | None = None,
    attempt_count: int | None = None,
    last_attempt_at: str | None = None,
    next_retry_at: str | None = None,
) -> None:
    payload = {
        "id": job_id,
        "run_date": job["run_date"],
        "region": job["region"],
        "artifact_type": job["artifact_type"],
        "channel": job["channel"],
        "target": job["target"],
        "status": status,
        "provider": provider,
        "subject": subject,
        "provider_message_id": provider_message_id,
        "error_message": error_message,
        "metadata": metadata or {},
        "attempt_count": attempt_count,
        "last_attempt_at": last_attempt_at,
        "next_retry_at": next_retry_at,
        "sent_at": utc_now_iso() if status == DELIVERY_STATUS_SENT else None,
    }
    get_supabase().table("delivery_jobs").upsert(payload, on_conflict="id").execute()


def fetch_artifact_rows(run_date: str, region: str, artifact_type: str) -> dict[str, dict]:
    response = (
        get_supabase()
        .table("artifacts")
        .select("format,storage_bucket,storage_path")
        .eq("run_date", run_date)
        .eq("region", region)
        .eq("artifact_type", artifact_type)
        .execute()
    )
    return {row["format"]: row for row in (response.data or []) if row.get("format")}


def download_storage_object(*, bucket: str, path: str) -> str:
    # The Supabase Storage copy was deleted on 2026-09-30, so a missing R2 object
    # is terminal: there is no duplicate left to fall back to.
    if storage_provider() == "r2":
        return get_r2_bytes(bucket_role=bucket, key=path).decode("utf-8")

    base_url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not base_url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set in environment variables")

    encoded_path = parse.quote(path, safe="/")
    req = request.Request(
        f"{base_url.rstrip('/')}/storage/v1/object/{bucket}/{encoded_path}",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
        },
        method="GET",
    )
    with request.urlopen(req, timeout=60) as response:
        return response.read().decode("utf-8")


def upsert_delivery_log(
    *,
    run_date: str,
    region: str = EMAIL_ARTIFACT_REGION,
    artifact_type: str = EMAIL_ARTIFACT_TYPE,
    recipient: dict,
    status: str,
    provider: str,
    subject: str,
    provider_message_id: str | None = None,
    error_message: str | None = None,
    metadata: dict | None = None,
    attempt_count: int | None = None,
    last_attempt_at: str | None = None,
    next_retry_at: str | None = None,
) -> None:
    payload = {
        "run_date": run_date,
        "region": region,
        "artifact_type": artifact_type,
        "recipient_email": recipient["email"],
        "recipient_name": recipient.get("name"),
        "client_name": recipient.get("client_name"),
        "status": status,
        "provider": provider,
        "provider_message_id": provider_message_id,
        "subject": subject,
        "error_message": error_message,
        "metadata": metadata or {},
        "sent_at": utc_now_iso() if status == DELIVERY_STATUS_SENT else None,
        "attempt_count": attempt_count,
        "last_attempt_at": last_attempt_at,
        "next_retry_at": next_retry_at,
    }
    get_supabase().table("email_deliveries").upsert(
        payload,
        on_conflict="run_date,region,artifact_type,recipient_email",
    ).execute()


def should_send_delivery(
    *,
    prior: dict | None,
    force_resend: bool,
    now: datetime,
    run_date: str,
) -> tuple[bool, str | None]:
    if force_resend or not prior:
        return True, None

    # Enable re-sending historical test dates (older than 3 days) multiple times
    try:
        run_dt = datetime.strptime(run_date, "%Y-%m-%d").date()
        if (now.date() - run_dt).days > 3:
            return True, None
    except Exception:
        pass

    status = prior.get("status")
    if status == DELIVERY_STATUS_SENT:
        return False, "already_sent"
    if status == DELIVERY_STATUS_SENDING:
        return False, "already_in_progress"
    if status == DELIVERY_STATUS_RETRY_SCHEDULED:
        retry_at = parse_iso_datetime(prior.get("next_retry_at"))
        if retry_at and retry_at > now:
            return False, "retry_not_due"
        return True, None
    if status == DELIVERY_STATUS_FAILED:
        return True, None
    if status == DELIVERY_STATUS_SKIPPED:
        return True, None

    return True, None


def get_next_retry_at(*, now: datetime) -> str:
    retry_dt = now + timedelta(minutes=get_retry_delay_minutes())
    return retry_dt.replace(microsecond=0).isoformat()


def send_via_resend(*, recipient: str, subject: str, html_content: str, text_content: str) -> str:
    payload = {
        "from": get_from_address(),
        "to": [recipient],
        "subject": subject,
        "html": html_content,
        "text": text_content,
    }
    reply_to = get_reply_to_address()
    if reply_to:
        payload["reply_to"] = reply_to
    unsubscribe_headers = build_unsubscribe_headers(recipient)
    if unsubscribe_headers:
        payload["headers"] = unsubscribe_headers

    # Pooled across every sending function: reserve the recipient from the
    # shared Resend budget immediately before the provider request. A denial
    # means no HTTP POST happens at all.
    if reserve_recipients(len(payload["to"]), sender="emailer") < 1:
        raise EmailRecipientBudgetExhausted("resend recipient budget exhausted")

    req = request.Request(
        RESEND_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {get_email_api_key()}",
            "Content-Type": "application/json",
            "User-Agent": get_user_agent(),
        },
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body.get("id", "")


def deliver_email(*, recipient: dict, subject: str, html_content: str, text_content: str) -> str:
    provider = get_email_provider()
    if provider != EMAIL_PROVIDER_RESEND:
        raise ValueError(f"Unsupported EMAIL_PROVIDER: {provider}")
    return send_via_resend(
        recipient=recipient["email"],
        subject=subject,
        html_content=html_content,
        text_content=text_content,
    )


def parse_request_payload(flask_request) -> dict:
    dispatch_token = flask_request.headers.get("X-Dispatch-Token")
    validate_dispatch_token(dispatch_token)

    payload = flask_request.get_json(silent=True)
    if not payload:
        raise ValueError("Request JSON body is required.")

    delivery_job_id = payload.get("delivery_job_id")
    run_date = payload.get("run_date")
    html_content = payload.get("html_content")
    text_content = payload.get("text_content")
    force_resend = bool(payload.get("force_resend", False))
    recipient_emails = payload.get("recipient_emails")

    if delivery_job_id is not None:
        try:
            delivery_job_id = int(delivery_job_id)
        except (TypeError, ValueError):
            raise ValueError("delivery_job_id must be an integer.") from None
        return {
            "mode": "delivery_job",
            "delivery_job_id": delivery_job_id,
            "force_resend": force_resend,
        }

    if not run_date:
        raise ValueError("run_date is required.")
    datetime.strptime(run_date, "%Y-%m-%d")
    if not html_content or not text_content:
        raise ValueError("html_content and text_content are required.")
    subject = payload.get("subject") or build_default_subject(run_date)
    if recipient_emails is not None:
        if not isinstance(recipient_emails, list) or not recipient_emails:
            raise ValueError("recipient_emails must be a non-empty list when provided.")

    return {
        "mode": "raw_payload",
        "run_date": run_date,
        "html_content": html_content,
        "text_content": text_content,
        "subject": subject,
        "force_resend": force_resend,
        "recipient_emails": recipient_emails,
    }


def _resolve_delivery_job_context(payload: dict) -> tuple[dict | None, tuple[dict, int] | None]:
    job = fetch_delivery_job(payload["delivery_job_id"])
    if not job:
        return None, ({"error": f"delivery_job_id {payload['delivery_job_id']} not found"}, 404)

    if (job["region"] == EMAIL_ARTIFACT_REGION
            and job["artifact_type"] == EMAIL_ARTIFACT_TYPE
            and not battleground_email_enabled()):
        # Preserve sent provider IDs and in-flight records. Pending retries
        # become terminal without reading artifacts or contacting Resend.
        if job.get("status") not in {DELIVERY_STATUS_SENT, DELIVERY_STATUS_SENDING}:
            upsert_delivery_job(
                job=job, job_id=job["id"], status=DELIVERY_STATUS_SKIPPED,
                provider=job.get("provider"), subject=job.get("subject"),
                attempt_count=int(job.get("attempt_count") or 0),
                last_attempt_at=job.get("last_attempt_at"),
                metadata={**(job.get("metadata") or {}),
                          "skip_reason": "battleground_template_retired"},
            )
        return None, retired_response()

    run_date = job["run_date"]
    artifact_rows = fetch_artifact_rows(run_date, job["region"], job["artifact_type"])
    html_row = artifact_rows.get("html")
    txt_row = artifact_rows.get("txt")
    if not html_row or not txt_row:
        return None, ({"error": f"Stored artifacts missing for delivery job {job['id']}"}, 409)

    recipient = fetch_recipient_by_email(job["target"])
    if not recipient:
        recipient = fetch_subscription_recipient(
            target=job["target"],
            channel=job["channel"],
            region=job["region"],
            artifact_type=job["artifact_type"],
        )
    if not recipient:
        return None, ({"error": f"Recipient {job['target']} not found for delivery job {job['id']}"}, 404)

    html_content = download_storage_object(bucket=html_row["storage_bucket"], path=html_row["storage_path"])
    text_content = download_storage_object(bucket=txt_row["storage_bucket"], path=txt_row["storage_path"])
    subject = job.get("subject") or recipient.get("subject_override") or build_default_subject(run_date)
    recipient_email = validate_email_address(recipient["email"])
    recipients = [{**recipient, "email": recipient_email}]
    # A delivery job is the idempotency boundary for stored artifacts. Using
    # the legacy run-date/recipient delivery row here would collapse two
    # distinct subscription products that share one address.
    existing = {recipient_email: job}
    return {
        "job": job,
        "run_date": run_date,
        "html_content": html_content,
        "text_content": text_content,
        "subject": subject,
        "recipients": recipients,
        "existing": existing,
        "delivery_region": job["region"],
        "delivery_artifact_type": job["artifact_type"],
    }, None


def _resolve_raw_payload_context(payload: dict) -> tuple[dict | None, tuple[dict, int] | None]:
    if not battleground_email_enabled():
        return None, retired_response()
    run_date = payload["run_date"]
    delivery_region = EMAIL_ARTIFACT_REGION
    delivery_artifact_type = EMAIL_ARTIFACT_TYPE
    return {
        "job": None,
        "run_date": run_date,
        "html_content": payload["html_content"],
        "text_content": payload["text_content"],
        "subject": payload["subject"],
        "recipients": filter_recipients(fetch_active_recipients(), payload["recipient_emails"]),
        "existing": fetch_existing_deliveries(
            run_date,
            region=delivery_region,
            artifact_type=delivery_artifact_type,
        ),
        "delivery_region": delivery_region,
        "delivery_artifact_type": delivery_artifact_type,
    }, None


def _sync_skipped_delivery_job_status(job: dict, prior: dict | None, provider: str, effective_subject: str) -> None:
    # If the email was already sent or is in progress, we must NOT downgrade the status to 'skipped' in the database!
    # Instead, we should synchronize the job status to match 'sent' or 'sending' if they are out of sync,
    # but leave the database untouched if it is already correct.
    prior_status = (prior or {}).get("status")
    if prior_status and job.get("status") != prior_status:
        upsert_delivery_job(
            job=job,
            job_id=job["id"],
            status=prior_status,
            provider=provider,
            subject=effective_subject,
            provider_message_id=(prior or {}).get("provider_message_id"),
            error_message=(prior or {}).get("error_message"),
            metadata=(prior or {}).get("metadata"),
            attempt_count=(prior or {}).get("attempt_count", int(job.get("attempt_count") or 0)),
            last_attempt_at=(prior or {}).get("last_attempt_at") or job.get("last_attempt_at"),
            next_retry_at=(prior or {}).get("next_retry_at") or job.get("next_retry_at"),
        )


def _record_budget_skip(
    *,
    job: dict | None,
    run_date: str,
    delivery_region: str,
    delivery_artifact_type: str,
    recipient: dict,
    provider: str,
    effective_subject: str,
    prior: dict | None,
    attempt_count: int,
    last_attempt_at: str,
) -> None:
    """Park one recipient at the pooled Resend budget ceiling.

    The recipient was already marked ``sending`` for this attempt, so put the
    record back: running out of budget defers a send, it does not fail one.
    Without a prior record the row is written as ``skipped`` — the same status
    the retired-template path uses — and keeps its pre-attempt ``attempt_count``
    because no delivery attempt was made. The record stays eligible
    (``should_send_delivery`` treats ``skipped`` as sendable, so a later
    dispatch of that delivery job can still send it), while ``ops_maintenance``'s
    retry scanner only re-queues ``pending`` and ``retry_scheduled`` jobs, so a
    spent budget pauses the remaining edition instead of looping on the
    provider. A prior ``sent`` record is restored verbatim so a forced resend
    that hit the budget can never downgrade it.
    """
    prior = prior or {}
    keep_sent = prior.get("status") == DELIVERY_STATUS_SENT
    status = DELIVERY_STATUS_SENT if keep_sent else DELIVERY_STATUS_SKIPPED
    provider_message_id = prior.get("provider_message_id") if keep_sent else None
    error_message = prior.get("error_message") if keep_sent else None
    next_retry_at = prior.get("next_retry_at") if keep_sent else None
    prior_metadata = prior.get("metadata")
    metadata = {
        **(prior_metadata if isinstance(prior_metadata, dict) else {}),
        "phase": "budget_exhausted",
        "skip_reason": BUDGET_EXHAUSTED_EVENT,
    }
    if job is not None:
        upsert_delivery_job(
            job=job,
            job_id=job["id"],
            status=status,
            provider=provider,
            subject=effective_subject,
            provider_message_id=provider_message_id,
            error_message=error_message,
            metadata=metadata,
            attempt_count=attempt_count,
            last_attempt_at=last_attempt_at,
            next_retry_at=next_retry_at,
        )
    upsert_delivery_log(
        run_date=run_date,
        region=delivery_region,
        artifact_type=delivery_artifact_type,
        recipient=recipient,
        status=status,
        provider=provider,
        subject=effective_subject,
        provider_message_id=provider_message_id,
        error_message=error_message,
        metadata=metadata,
        attempt_count=attempt_count,
        last_attempt_at=last_attempt_at,
        next_retry_at=next_retry_at,
    )


def _record_dispatch_failure(
    *,
    job: dict | None,
    run_date: str,
    delivery_region: str,
    delivery_artifact_type: str,
    recipient: dict,
    provider: str,
    effective_subject: str,
    message: str,
    attempt_count: int,
    last_attempt_at: str,
) -> str:
    retry_status = (
        DELIVERY_STATUS_RETRY_SCHEDULED
        if attempt_count < get_max_attempts()
        else DELIVERY_STATUS_FAILED
    )
    next_retry_at = None
    if retry_status == DELIVERY_STATUS_RETRY_SCHEDULED:
        next_retry_at = get_next_retry_at(now=datetime.now(timezone.utc))
    will_retry = retry_status == DELIVERY_STATUS_RETRY_SCHEDULED
    if job is not None:
        upsert_delivery_job(
            job=job,
            job_id=job["id"],
            status=retry_status,
            provider=provider,
            subject=effective_subject,
            error_message=message,
            metadata={"phase": "dispatch_failed", "will_retry": will_retry},
            attempt_count=attempt_count,
            last_attempt_at=last_attempt_at,
            next_retry_at=next_retry_at,
        )
    upsert_delivery_log(
        run_date=run_date,
        region=delivery_region,
        artifact_type=delivery_artifact_type,
        recipient=recipient,
        status=retry_status,
        provider=provider,
        subject=effective_subject,
        error_message=message,
        metadata={"phase": "dispatch_failed", "will_retry": will_retry},
        attempt_count=attempt_count,
        last_attempt_at=last_attempt_at,
        next_retry_at=next_retry_at,
    )
    return message


def _dispatch_one_recipient(
    *,
    job: dict | None,
    recipient: dict,
    subject: str,
    run_date: str,
    delivery_region: str,
    delivery_artifact_type: str,
    existing: dict,
    force_resend: bool,
    now: datetime,
    provider: str,
    html_content: str,
    text_content: str,
) -> tuple[str, dict | None]:
    """Send (or skip) one recipient. Returns (outcome, failure_record)."""
    recipient_email = validate_email_address(recipient["email"])
    recipient = {**recipient, "email": recipient_email}
    prior = existing.get(recipient_email)

    effective_subject = recipient.get("subject_override") or subject
    should_send, _skip_reason = should_send_delivery(
        prior=prior,
        force_resend=force_resend,
        now=now,
        run_date=run_date,
    )
    if not should_send:
        if job is not None:
            _sync_skipped_delivery_job_status(job, prior, provider, effective_subject)
        return "skipped", None

    prior_attempt_count = int((prior or {}).get("attempt_count") or 0)
    attempt_count = prior_attempt_count + 1
    last_attempt_at = utc_now_iso()
    if job is not None:
        upsert_delivery_job(
            job=job,
            job_id=job["id"],
            status=DELIVERY_STATUS_SENDING,
            provider=provider,
            subject=effective_subject,
            metadata={"phase": "dispatch_started"},
            attempt_count=attempt_count,
            last_attempt_at=last_attempt_at,
            next_retry_at=None,
        )
    upsert_delivery_log(
        run_date=run_date,
        region=delivery_region,
        artifact_type=delivery_artifact_type,
        recipient=recipient,
        status=DELIVERY_STATUS_SENDING,
        provider=provider,
        subject=effective_subject,
        metadata={"phase": "dispatch_started"},
        attempt_count=attempt_count,
        last_attempt_at=last_attempt_at,
        next_retry_at=None,
    )

    try:
        with tracer.start_as_current_span("email.deliver", attributes={"provider": provider}):
            message_id = deliver_email(
                recipient=recipient,
                subject=effective_subject,
                html_content=html_content,
                text_content=text_content,
            )
        upsert_delivery_log(
            run_date=run_date,
            region=delivery_region,
            artifact_type=delivery_artifact_type,
            recipient=recipient,
            status=DELIVERY_STATUS_SENT,
            provider=provider,
            subject=effective_subject,
            provider_message_id=message_id,
            attempt_count=attempt_count,
            last_attempt_at=last_attempt_at,
        )
        if job is not None:
            upsert_delivery_job(
                job=job,
                job_id=job["id"],
                status=DELIVERY_STATUS_SENT,
                provider=provider,
                subject=effective_subject,
                provider_message_id=message_id,
                attempt_count=attempt_count,
                last_attempt_at=last_attempt_at,
            )
        return "sent", None
    except EmailRecipientBudgetExhausted:
        _record_budget_skip(
            job=job, run_date=run_date, delivery_region=delivery_region,
            delivery_artifact_type=delivery_artifact_type, recipient=recipient,
            provider=provider, effective_subject=effective_subject, prior=prior,
            attempt_count=prior_attempt_count, last_attempt_at=last_attempt_at,
        )
        return "budget_paused", None
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        message = _record_dispatch_failure(
            job=job, run_date=run_date, delivery_region=delivery_region,
            delivery_artifact_type=delivery_artifact_type, recipient=recipient,
            provider=provider, effective_subject=effective_subject,
            message=f"{exc.code} {body}", attempt_count=attempt_count,
            last_attempt_at=last_attempt_at,
        )
        return "failed", {"email": recipient_email, "error": message}
    except Exception as exc:
        message = _record_dispatch_failure(
            job=job, run_date=run_date, delivery_region=delivery_region,
            delivery_artifact_type=delivery_artifact_type, recipient=recipient,
            provider=provider, effective_subject=effective_subject,
            message=str(exc), attempt_count=attempt_count,
            last_attempt_at=last_attempt_at,
        )
        return "failed", {"email": recipient_email, "error": message}


@functions_framework.http
def send_brief_email(request_):
    try:
        payload = parse_request_payload(request_)
    except PermissionError as exc:
        return {"error": str(exc)}, 401
    except Exception as exc:
        return {"error": str(exc)}, 400

    force_resend = payload["force_resend"]
    provider = get_email_provider()

    if payload["mode"] == "delivery_job":
        context, error_response = _resolve_delivery_job_context(payload)
    else:
        context, error_response = _resolve_raw_payload_context(payload)
    if error_response is not None:
        return error_response

    job = context["job"]
    run_date = context["run_date"]
    html_content = context["html_content"]
    text_content = context["text_content"]
    subject = context["subject"]
    recipients = context["recipients"]
    existing = context["existing"]
    delivery_region = context["delivery_region"]
    delivery_artifact_type = context["delivery_artifact_type"]

    now = datetime.now(timezone.utc)

    sent_count = 0
    skipped_count = 0
    failed_count = 0
    paused_count = 0
    failures: list[dict] = []

    dispatch_span = tracer.start_span(
        "send_brief_email", attributes={"run_date": run_date, "mode": payload["mode"], "recipient_count": len(recipients)}
    )
    dispatch_span_token = otel_context.attach(otel_trace.set_span_in_context(dispatch_span))

    for recipient in recipients:
        outcome, failure = _dispatch_one_recipient(
            job=job,
            recipient=recipient,
            subject=subject,
            run_date=run_date,
            delivery_region=delivery_region,
            delivery_artifact_type=delivery_artifact_type,
            existing=existing,
            force_resend=force_resend,
            now=now,
            provider=provider,
            html_content=html_content,
            text_content=text_content,
        )
        if outcome == "sent":
            sent_count += 1
        elif outcome == "skipped":
            skipped_count += 1
        elif outcome == "budget_paused":
            # The pooled recipient budget is spent: stop so the remaining
            # recipients are not offered to the provider this pass.
            paused_count += 1
            break
        else:
            failed_count += 1
            failures.append(failure)

    otel_context.detach(dispatch_span_token)
    dispatch_span.end()

    status_code = 200 if failed_count == 0 else 207
    return {
        "run_date": run_date,
        "delivery_job_id": payload.get("delivery_job_id"),
        "provider": provider,
        "recipient_count": len(recipients),
        "sent_count": sent_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "paused_count": paused_count,
        "failures": failures,
    }, status_code
