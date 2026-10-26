"""Public intake endpoint for NewsCloud email signups and customer research.

The browser never receives Supabase or Resend credentials. This function
accepts two tightly validated payload shapes:

* ``daily_brief`` activates an existing delivery subscription contract.
* ``client_research`` sends a structured field note to the operator inbox.

The endpoint deliberately stores no IP addresses. A small in-memory throttle
reduces accidental bursts within one warm function instance; the honeypot and
strict payload limits provide additional low-cost abuse resistance.
"""

from __future__ import annotations

import html
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from email.utils import parseaddr
from urllib import error, parse, request

from shared.email_budget import EmailRecipientBudgetExhausted, reserve_recipients
from shared.supabase_rest import SupabaseRest, SupabaseRestError

import functions_framework


RESEND_API_URL = "https://api.resend.com/emails"
MAX_BODY_BYTES = 16_384
RATE_LIMIT_REQUESTS = 8
RATE_LIMIT_WINDOW_SECONDS = 600

EDITION_CONTRACTS = {
    "race_board": {
        "region": "national",
        "artifact_type": "race_board_email",
        "audience": None,
    },
}

LEAN_PREFERENCES = {"democrat", "republican", "neutral"}
PROFILE_CADENCES = {"daily", "several-weekly", "weekly"}

ORGANIZATION_TYPES = {
    "consultancy",
    "advocacy",
    "campaign",
    "party-or-pac",
    "media-or-research",
    "corporate-public-affairs",
    "other",
}
STATE_RANGES = {"1-2", "3-4", "5-10", "11-25", "26-plus"}
BRIEFING_FREQUENCIES = {"daily", "several-weekly", "weekly", "ad-hoc", "never"}

_request_times: dict[str, deque[float]] = defaultdict(deque)


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not configured.")
    return value


def _allowed_origins() -> set[str]:
    configured = os.environ.get(
        "ALLOWED_ORIGINS",
        "https://dashboard.example.invalid;http://localhost:8000;http://127.0.0.1:8000",
    )
    return {item.strip().rstrip("/") for item in configured.split(";") if item.strip()}


def _cors_headers(origin: str | None) -> dict[str, str]:
    headers = {
        "Cache-Control": "no-store",
        "Content-Type": "application/json; charset=utf-8",
        "Vary": "Origin",
    }
    if origin and origin.rstrip("/") in _allowed_origins():
        headers["Access-Control-Allow-Origin"] = origin.rstrip("/")
        headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        headers["Access-Control-Allow-Headers"] = "Content-Type"
        headers["Access-Control-Max-Age"] = "600"
    return headers


def _response(payload: dict, status: int, origin: str | None):
    return payload, status, _cors_headers(origin)


def _clean_text(value: object, *, field: str, maximum: int, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field} is required.")
    if len(text) > maximum:
        raise ValueError(f"{field} must be {maximum} characters or fewer.")
    return text


def _email(value: object) -> str:
    candidate = _clean_text(value, field="email", maximum=254).lower()
    _, parsed = parseaddr(candidate)
    if parsed != candidate or "@" not in parsed or parsed.startswith("@") or parsed.endswith("@"):
        raise ValueError("Enter a valid email address.")
    return parsed


def _client_key(flask_request) -> str:
    forwarded = (flask_request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
    return forwarded or flask_request.remote_addr or "unknown"


def _rate_limited(client_key: str, now: float | None = None) -> bool:
    current = time.monotonic() if now is None else now
    cutoff = current - RATE_LIMIT_WINDOW_SECONDS
    attempts = _request_times[client_key]
    while attempts and attempts[0] < cutoff:
        attempts.popleft()
    if len(attempts) >= RATE_LIMIT_REQUESTS:
        return True
    attempts.append(current)
    return False


def _supabase_client() -> SupabaseRest:
    return SupabaseRest(_required_env("SUPABASE_URL"), _required_env("SUPABASE_SECRET_KEY"))


def _subscription_payload(payload: dict) -> dict:
    edition = _clean_text(payload.get("edition"), field="edition", maximum=32)
    if edition not in EDITION_CONTRACTS:
        raise ValueError("Choose a valid email edition.")
    if payload.get("consent") is not True:
        raise ValueError("Consent is required to receive the daily email.")

    contract = EDITION_CONTRACTS[edition]
    row = {
        "target": _email(payload.get("email")),
        "channel": "email",
        "region": contract["region"],
        "artifact_type": contract["artifact_type"],
        "active": True,
        "audience": contract["audience"],
        "metadata": {
            "signup_source": "public-board-signup-page",
            "consent_version": "daily-brief-v1",
            "edition": edition,
        },
    }
    return row


def _upsert_subscription(row: dict) -> None:
    _supabase_client().upsert(
        "subscriptions", row, on_conflict="target,channel,region,artifact_type", timeout=20,
    )


def _profile_payload(payload: dict) -> dict:
    if payload.get("consent") is not True:
        raise ValueError("Consent is required to receive the daily email.")
    states_raw = payload.get("states")
    states: list[str] = []
    if isinstance(states_raw, list):
        for value in states_raw[:15]:
            clean = _clean_text(value, field="state", maximum=5, required=False)
            if clean:
                states.append(clean.upper())
    lean = str(payload.get("lean_preference") or "").strip().lower()
    cadence = str(payload.get("cadence") or "").strip().lower()
    return {
        "email": _email(payload.get("email")),
        "consent_version": "race-board-v1",
        "signup_source": str(payload.get("source") or "public-board-page")[:64],
        "utm": payload.get("utm") if isinstance(payload.get("utm"), dict) else {},
        "role": _clean_text(payload.get("role"), field="role", maximum=80, required=False) or None,
        "states": states,
        "lean_preference": lean if lean in LEAN_PREFERENCES else None,
        "cadence": cadence if cadence in PROFILE_CADENCES else None,
    }


def _upsert_profile(row: dict) -> None:
    _supabase_client().upsert("subscriber_profiles", row, on_conflict="email", timeout=20)


def _deactivate_subscriptions(email: str) -> None:
    _supabase_client().call(
        "PATCH",
        f"subscriptions?target=eq.{parse.quote(email)}&active=eq.true",
        body={"active": False},
        timeout=20,
    )


def _soft_delete_profile(email: str) -> None:
    _supabase_client().call(
        "PATCH",
        f"subscriber_profiles?email=eq.{parse.quote(email)}",
        body={"deleted_at": datetime.now(timezone.utc).isoformat()},
        timeout=20,
    )


def _parse_one_click_unsubscribe(flask_request) -> str | None:
    """Return the recipient for an RFC 8058 one-click POST, else None."""
    content_type = (flask_request.headers.get("Content-Type") or "").lower()
    if "application/x-www-form-urlencoded" not in content_type:
        return None
    form = getattr(flask_request, "form", None)
    args = getattr(flask_request, "args", None)
    if form is None or args is None:
        return None
    if form.get("List-Unsubscribe") != "One-Click":
        return None
    raw_email = args.get("email")
    if not raw_email:
        return None
    try:
        return _email(raw_email)
    except ValueError:
        return None


def _research_payload(payload: dict) -> dict:
    if payload.get("consent") is not True:
        raise ValueError("Consent is required so NewsCloud can review your response.")

    organization_type = _clean_text(
        payload.get("organization_type"), field="organization type", maximum=48
    )
    if organization_type not in ORGANIZATION_TYPES:
        raise ValueError("Choose a valid organization type.")

    state_range = _clean_text(payload.get("state_range"), field="state range", maximum=16)
    if state_range not in STATE_RANGES:
        raise ValueError("Choose a valid number of states.")

    frequency = _clean_text(payload.get("frequency"), field="briefing frequency", maximum=24)
    if frequency not in BRIEFING_FREQUENCIES:
        raise ValueError("Choose a valid briefing frequency.")

    return {
        "name": _clean_text(payload.get("name"), field="name", maximum=100),
        "email": _email(payload.get("email")),
        "role": _clean_text(payload.get("role"), field="role", maximum=120),
        "organization": _clean_text(
            payload.get("organization"), field="organization", maximum=160
        ),
        "organization_type": organization_type,
        "state_range": state_range,
        "frequency": frequency,
        "recent_briefing": _clean_text(
            payload.get("recent_briefing"),
            field="recent briefing",
            maximum=3_000,
        ),
        "open_to_interview": payload.get("open_to_interview") is True,
    }


def _send_research_email(field_note: dict) -> None:
    inbox = _required_env("RESEARCH_INBOX")
    api_key = _required_env("EMAIL_API_KEY")
    from_address = _required_env("EMAIL_FROM_ADDRESS")

    lines = [
        "NewsCloud client research response",
        "",
        f"Name: {field_note['name']}",
        f"Email: {field_note['email']}",
        f"Role: {field_note['role']}",
        f"Organization: {field_note['organization']}",
        f"Organization type: {field_note['organization_type']}",
        f"States monitored: {field_note['state_range']}",
        f"Briefing frequency: {field_note['frequency']}",
        f"Open to interview: {'yes' if field_note['open_to_interview'] else 'no'}",
        "",
        "Most recent briefing workflow:",
        field_note["recent_briefing"],
    ]
    text_body = "\n".join(lines)
    escaped = {key: html.escape(str(value)) for key, value in field_note.items()}
    html_body = f"""
      <h1>NewsCloud client research response</h1>
      <table cellpadding="6" cellspacing="0" border="0">
        <tr><th align="left">Name</th><td>{escaped['name']}</td></tr>
        <tr><th align="left">Email</th><td>{escaped['email']}</td></tr>
        <tr><th align="left">Role</th><td>{escaped['role']}</td></tr>
        <tr><th align="left">Organization</th><td>{escaped['organization']}</td></tr>
        <tr><th align="left">Organization type</th><td>{escaped['organization_type']}</td></tr>
        <tr><th align="left">States monitored</th><td>{escaped['state_range']}</td></tr>
        <tr><th align="left">Briefing frequency</th><td>{escaped['frequency']}</td></tr>
        <tr><th align="left">Open to interview</th><td>{'yes' if field_note['open_to_interview'] else 'no'}</td></tr>
      </table>
      <h2>Most recent briefing workflow</h2>
      <p style="white-space:pre-wrap">{escaped['recent_briefing']}</p>
    """.strip()
    provider_payload = {
        "from": from_address,
        "to": [inbox],
        "reply_to": field_note["email"],
        "subject": f"NewsCloud field note — {field_note['organization']}",
        "text": text_body,
        "html": html_body,
    }
    # The pool is shared with the other senders, so reserve the recipient from
    # the account-wide Resend budget immediately before the provider request.
    if reserve_recipients(len(provider_payload["to"]), sender="intake") < 1:
        raise EmailRecipientBudgetExhausted("resend recipient budget exhausted")
    req = request.Request(
        RESEND_API_URL,
        data=json.dumps(provider_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "newscloud-intake/1.0",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=20):
        return None


def _handle_intake_submission(payload: dict) -> dict:
    intake_type = _clean_text(payload.get("type"), field="type", maximum=32)
    if intake_type == "race_board_signup":
        _upsert_subscription(_subscription_payload({**payload, "edition": "race_board"}))
        _upsert_profile(_profile_payload(payload))
        return {
            "ok": True,
            "message": "You’re in. The next Race Board email is on its way.",
        }
    if intake_type == "unsubscribe":
        address = _email(payload.get("email"))
        _deactivate_subscriptions(address)
        _soft_delete_profile(address)
        return {"ok": True, "message": "You’ve been unsubscribed."}
    if intake_type == "client_research":
        field_note = _research_payload(payload)
        _send_research_email(field_note)
        return {
            "ok": True,
            "message": "Thank you. Your field note will directly inform the NewsCloud pilot.",
        }
    raise ValueError("Choose a valid intake type.")


def _reject_non_post_intake_request(flask_request, origin: str | None, normalized_origin: str | None):
    if flask_request.method == "OPTIONS":
        if normalized_origin not in _allowed_origins():
            return _response({"error": "Origin not allowed."}, 403, origin)
        return _response({}, 204, origin)

    if flask_request.method != "POST":
        return _response({"error": "Method not allowed."}, 405, origin)
    if normalized_origin not in _allowed_origins():
        return _response({"error": "Origin not allowed."}, 403, origin)
    return None


def _reject_oversized_or_throttled_intake_request(flask_request, origin: str | None):
    content_length = flask_request.content_length or 0
    if content_length > MAX_BODY_BYTES:
        return _response({"error": "Request is too large."}, 413, origin)
    if _rate_limited(_client_key(flask_request)):
        return _response(
            {"error": "Too many attempts. Wait a few minutes and try again."},
            429,
            origin,
        )
    return None


@functions_framework.http
def public_intake(flask_request):
    origin = flask_request.headers.get("Origin")
    normalized_origin = origin.rstrip("/") if origin else None

    # RFC 8058 one-click unsubscribe: mailbox providers POST form-encoded data
    # with no Origin header, so handle it before the origin/JSON checks.
    one_click = _parse_one_click_unsubscribe(flask_request)
    if one_click is not None:
        _deactivate_subscriptions(one_click)
        _soft_delete_profile(one_click)
        return _response({"ok": True}, 200, origin)

    rejection = _reject_non_post_intake_request(flask_request, origin, normalized_origin)
    if rejection is not None:
        return rejection

    rejection = _reject_oversized_or_throttled_intake_request(flask_request, origin)
    if rejection is not None:
        return rejection

    payload = flask_request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _response({"error": "A JSON request body is required."}, 400, origin)

    # Bots fill hidden fields. Return an ordinary success so the endpoint does
    # not teach them which control triggered the rejection.
    if str(payload.get("website") or "").strip():
        return _response({"ok": True, "message": "Thanks — your response was received."}, 201, origin)

    try:
        return _response(_handle_intake_submission(payload), 201, origin)
    except ValueError as exc:
        return _response({"error": str(exc)}, 400, origin)
    except (error.HTTPError, SupabaseRestError):
        # A storage failure is the caller's problem to retry, not a server bug:
        # the shared client raises its own error type instead of HTTPError.
        return _response(
            {"error": "The service could not save your response. Please try again."},
            502,
            origin,
        )
    except EmailRecipientBudgetExhausted:
        # The account-wide Resend recipient budget is spent, so the field note
        # was not sent. Reject it as retryable rather than accepting data the
        # operator will never see.
        return _response(
            {"error": "The research inbox is at capacity right now. Please try again later."},
            503,
            origin,
        )
    except Exception:
        return _response(
            {"error": "The service is temporarily unavailable. Please try again."},
            500,
            origin,
        )
