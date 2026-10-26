"""Account-wide Resend recipient budget shared by every sending function.

Resend counts recipients against the whole account, not against the function
that made the request, so ``emailer``, ``intake``, and ``performance_brief``
reserve from one pooled counter before they issue a provider POST. No function
has its own ceiling: a reservation made by one sender is capacity the others
can no longer spend.

The counter lives in Supabase (``public.reserve_email_recipients`` from
migration ``20260928130000_add_email_recipient_budget``) so the ceilings survive
instance restarts and are enforced across concurrent instances.

Enforcement must not block customer mail while the migration is being rolled
out. When the RPC is missing or unreachable, the reservation fails open — the
send proceeds, and one ``email_recipient_budget_unavailable`` marker is printed
per process — so functions can be deployed before or after the migration.

Deploy order (Phase 2, Resend):

1. Apply ``supabase/migrations/20260928130000_add_email_recipient_budget.sql``
   first so the pooled counter exists.
2. Then deploy the three senders (``emailer``, ``intake``,
   ``performance_brief``). ``intake`` gains the ``supabase`` runtime dependency
   in ``functions/intake/requirements.in``, so it must be redeployed (not just
   updated) for its reservation to reach Supabase.
3. No functional gate is required: applying the migration later is also safe.
   The senders keep sending while ``reserve_email_recipients`` is missing, log
   ``email_recipient_budget_unavailable`` once per instance, and start enforcing
   as soon as the RPC exists — no redeploy needed.
4. Rollback: drop ``public.reserve_email_recipients`` (or the table) and the
   senders degrade back to provider-limit-only behaviour. Never drop the table
   while sends are in flight if you intend to keep the day's usage ledger.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from shared.external_calls import external_error_summary
from shared.supabase_client import get_supabase

DEFAULT_DAILY_RECIPIENT_LIMIT = 90
DEFAULT_MONTHLY_RECIPIENT_LIMIT = 2700

DAILY_LIMIT_ENV = "NEWSCLOUD_EMAIL_DAILY_RECIPIENT_LIMIT"
MONTHLY_LIMIT_ENV = "NEWSCLOUD_EMAIL_MONTHLY_RECIPIENT_LIMIT"

BUDGET_EXHAUSTED_EVENT = "email_recipient_budget_exhausted"
BUDGET_UNAVAILABLE_EVENT = "email_recipient_budget_unavailable"

# ``reserve_email_recipients`` answers 0 for the daily ceiling and -1 for the
# monthly one; any other non-positive value is treated as a denial too.
MONTHLY_CAP_SENTINEL = -1

_budget_unavailable_reported = False


class EmailRecipientBudgetExhausted(RuntimeError):
    """Raised by a sender when the pooled Resend recipient budget denies a send.

    The sender must not contact the provider. The shared counter already logged
    an ``email_recipient_budget_exhausted`` marker with the exhausted period.
    """


def get_daily_recipient_limit() -> int:
    """Recipients allowed per UTC day across every sender (default 90)."""
    return _positive_int_env(DAILY_LIMIT_ENV, DEFAULT_DAILY_RECIPIENT_LIMIT)


def get_monthly_recipient_limit() -> int:
    """Recipients allowed per calendar month across every sender (default 2700)."""
    return _positive_int_env(MONTHLY_LIMIT_ENV, DEFAULT_MONTHLY_RECIPIENT_LIMIT)


def reserve_recipients(count: int = 1, *, sender: str | None = None) -> int:
    """Reserve ``count`` Resend recipient slots from the pooled budget.

    Returns ``count`` when both the daily and monthly ceilings allow the send,
    and ``0`` when the send must be paused. A denial prints one
    ``email_recipient_budget_exhausted`` marker naming the exhausted ``period``.

    Fails open when the Supabase counter is unavailable, so a rollout or outage
    degrades to the provider's own cap instead of dropping mail.
    """
    if count < 1:
        raise ValueError("count must be a positive integer")

    day_limit = get_daily_recipient_limit()
    month_limit = get_monthly_recipient_limit()

    try:
        response = get_supabase().rpc(
            "reserve_email_recipients",
            {
                "p_day": datetime.now(timezone.utc).date().isoformat(),
                "p_count": count,
                "p_day_limit": day_limit,
                "p_month_limit": month_limit,
            },
        ).execute()
    except Exception as exc:  # migration missing, network fault, bad credentials
        report_budget_unavailable(exc)
        return count

    granted = _granted_from(response.data)
    if granted is None:
        report_budget_unavailable(ValueError(f"unexpected reserve_email_recipients payload: {response.data!r}"))
        return count
    if granted >= count:
        return count

    log_budget_exhausted(
        period="month" if granted == MONTHLY_CAP_SENTINEL else "day",
        requested=count,
        day_limit=day_limit,
        month_limit=month_limit,
        sender=sender,
    )
    return 0


def log_budget_exhausted(
    *,
    period: str,
    requested: int,
    day_limit: int,
    month_limit: int,
    sender: str | None = None,
) -> None:
    """Emit the structured marker telling operators which ceiling paused sends."""
    payload = {
        "event": BUDGET_EXHAUSTED_EVENT,
        "period": period,
        "requested": requested,
        "daily_limit": day_limit,
        "monthly_limit": month_limit,
    }
    if sender:
        payload["sender"] = sender
    print(json.dumps(payload, sort_keys=True, default=str), flush=True)


def report_budget_unavailable(exc: Exception) -> None:
    """Warn once per process that reservations are not being enforced."""
    global _budget_unavailable_reported
    if _budget_unavailable_reported:
        return
    _budget_unavailable_reported = True
    print(
        json.dumps(
            {
                "event": BUDGET_UNAVAILABLE_EVENT,
                "error": external_error_summary(exc),
                "action": "sends proceed without a pooled recipient reservation",
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _granted_from(data: object) -> int | None:
    """Normalize the PostgREST payload of an integer-returning RPC."""
    if isinstance(data, list):
        if len(data) != 1:
            return None
        data = data[0]
    if data is None or isinstance(data, bool):
        return None
    try:
        return int(data)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _positive_int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default
