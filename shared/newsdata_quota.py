"""Account-wide NewsData.io credit reservations.

Both gatherers (``functions/gatherer/main.py`` and
``functions/gatherer/district_gatherer.py``) spend credits from one provider
account, so the ceilings must be durable and shared rather than per-process.
``reserve_credit`` asks ``public.reserve_newsdata_credit`` (see
``supabase/migrations/20260928120000_add_newsdata_quota.sql``) for one atomic
reservation immediately before each NewsData HTTP request; the table it writes
is the only counter, so restarts and new instances cannot reset it.

Ceilings
--------
Defaults are 160 credits per run date and 28 credits per rolling 15 minutes --
below NewsData's Free allowances of 200/day and 30/15 minutes -- and are
overridable with ``NEWSCLOUD_NEWSDATA_DAILY_CREDIT_LIMIT`` and
``NEWSCLOUD_NEWSDATA_WINDOW_CREDIT_LIMIT``. A denied reservation must skip the
provider request; it is never retried here, and NewsData 429s are never retried
either.

Denial policy
-------------
The RPC reports *why* it denied, because the two cases need opposite handling:

- ``window`` (rolling 15 minutes full) clears itself within a quarter hour. Both
  gatherers pace at 65 seconds, so while their sweeps overlap they already
  consume ~27.7 of the 28 credits per window: a window denial during the overlap
  is normal, not exceptional. The target is **deferred** -- the region keeps the
  RSS-only corpus it already gathered, its stage is left retryable, and the
  finalizer's bounded retry path (3 attempts, 2/5-minute backoff, up to two
  recovery cycles, driven by the 10-minute nudge) re-attempts it after the
  window drains. Waiting inside the invocation is not an option: the 65-second
  pacer already spends part of the 300-second Cloud Run timeout.
- ``daily`` (160 for the run date) cannot move until the next day. The target is
  **terminal**: the region publishes the RSS-only corpus, records a
  ``newsdata_quota_exhausted`` marker, and is not retried, because retrying can
  only burn attempt budget against a fixed ceiling.

Before this distinction existed, a denial left the region's stage at
``completed``, so the finalizer never retried it and the day's coverage quietly
thinned. A denial must never look like success.

Why no per-run-date pass-claim row
----------------------------------
One full scheduled pass costs 132 credits (53 state regions + 79 districts), so
the 160-credit daily ceiling rejects a duplicate full replay numerically: a
second pass needs 264 credits. No run date exists on which a second full pass
fits, so a separate pass-claim row would only re-state the ceiling. The slack
(160 - 132 = 28 credits) is useful work -- a retried source, a changed source
list, a single-region backfill -- and a reservation cannot tell a replay apart
from those; suppressing a duplicate fan-out belongs to the dispatcher (the
orchestrator), which owns pass identity. The one case the ceiling does not
reject is a district-only replay (79 + 79 = 158 credits) when the state pass
spent almost nothing, and that still stays inside both the internal budget and
the provider allowance, so it wastes allowance but cannot overspend it.

Deploy order (operator)
-----------------------
Apply ``supabase/migrations/20260928120000_add_newsdata_quota.sql`` to the
Supabase project *before* deploying the ``gatherer`` and ``gatherer-district``
functions:

1. Run the migration (``supabase db push`` or the SQL editor).
2. Confirm the function exists:
   ``select proname from pg_proc where proname = 'reserve_newsdata_credit';``
   (one row) and that ``public.newsdata_credit_reservations`` is empty.
3. Deploy both gatherers as usual (``scripts/stage_function.py`` copies
   ``shared/``, so this module ships with them).
4. Watch for ``newsdata_quota_denied`` (expected once the internal ceiling is
   reached) and for ``newsdata_quota_unavailable``.

No hard dependency exists in the other direction: this module is deployed by
code, the reservation function by migration. A missing table/RPC, a Supabase
outage, an unset ``SUPABASE_URL``/``SUPABASE_SECRET_KEY``, or an unexpected RPC
response logs one ``newsdata_quota_unavailable`` line per process and lets the
request proceed, so shipping the code first degrades the gate to "allow" instead
of breaking gathering. The per-instance 65-second pacer in
``shared.external_calls`` bounds that degradation, and it is the reason the
reverse order is tolerable for a short deploy window -- but not for long, since
it leaves the account without durable accounting.
"""

from __future__ import annotations

from datetime import date, datetime
import json
import os
import threading
from typing import NamedTuple

from shared.supabase_client import get_supabase

DAILY_LIMIT_ENV = "NEWSCLOUD_NEWSDATA_DAILY_CREDIT_LIMIT"
WINDOW_LIMIT_ENV = "NEWSCLOUD_NEWSDATA_WINDOW_CREDIT_LIMIT"
DEFAULT_DAILY_CREDIT_LIMIT = 160
DEFAULT_WINDOW_CREDIT_LIMIT = 28
RESERVE_RPC = "reserve_newsdata_credit"

# Sentinels returned by public.reserve_newsdata_credit (see the migration).
GRANTED = 1
DENIED_WINDOW = -1
DENIED_DAILY = -2

_client_lock = threading.Lock()
_client = None
_unavailable_logged = False


class Reservation(NamedTuple):
    """Outcome of one credit reservation.

    ``reason`` is one of ``granted``, ``window``, ``daily`` or ``unavailable``.
    The distinction is the caller's retry policy: a ``window`` denial clears
    itself within fifteen minutes and the target should be deferred, while a
    ``daily`` denial cannot move until the next run date and must not be
    retried.
    """

    granted: bool
    reason: str

    def __bool__(self) -> bool:
        return self.granted


def _limit_from_env(name: str, fallback: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return fallback
    try:
        value = int(raw)
    except ValueError:
        return fallback
    return value if value > 0 else fallback


def daily_credit_limit() -> int:
    """Credits allowed per run date (``NEWSCLOUD_NEWSDATA_DAILY_CREDIT_LIMIT``)."""
    return _limit_from_env(DAILY_LIMIT_ENV, DEFAULT_DAILY_CREDIT_LIMIT)


def window_credit_limit() -> int:
    """Credits allowed per rolling 15 minutes (``..._WINDOW_CREDIT_LIMIT``)."""
    return _limit_from_env(WINDOW_LIMIT_ENV, DEFAULT_WINDOW_CREDIT_LIMIT)


def _get_client():
    """Return one cached Supabase client per process (never per request)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = get_supabase()
    return _client


def _log(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True, default=str))


def _warn_unavailable(reason: str) -> None:
    """Log the first quota-accounting failure in this process, then stay quiet."""
    global _unavailable_logged
    if _unavailable_logged:
        return
    _unavailable_logged = True
    _log("newsdata_quota_unavailable", reason=reason)


def _normalize_run_date(run_date: date | str) -> str:
    if isinstance(run_date, datetime):
        return run_date.date().isoformat()
    if isinstance(run_date, date):
        return run_date.isoformat()
    return date.fromisoformat(str(run_date).strip()).isoformat()


def reserve_credit(
    *,
    run_date: date | str,
    source: str,
    daily_limit: int | None = None,
    window_limit: int | None = None,
) -> Reservation:
    """Reserve one NewsData credit for ``source`` on ``run_date``.

    Returns a truthy :class:`Reservation` when the caller may issue the provider
    request. When a ceiling is reached the reservation is falsy and carries the
    reason (``window`` or ``daily``); a denial also emits one
    ``newsdata_quota_denied`` line with that reason. ``daily_limit`` and
    ``window_limit`` override the environment defaults of 160 and 28.

    A missing migration, a Supabase outage, or an unreadable response logs one
    ``newsdata_quota_unavailable`` line per process and grants the reservation,
    so the gate fails open rather than stopping gathering.
    """
    try:
        normalized = _normalize_run_date(run_date)
    except (TypeError, ValueError):
        _warn_unavailable(f"invalid_run_date:{run_date!r}")
        return Reservation(True, "unavailable")

    source_name = str(source or "").strip() or "unknown"
    try:
        response = (
            _get_client()
            .rpc(
                RESERVE_RPC,
                {
                    "p_run_date": normalized,
                    "p_source": source_name,
                    "p_daily_limit": (
                        daily_credit_limit() if daily_limit is None else int(daily_limit)
                    ),
                    "p_window_limit": (
                        window_credit_limit() if window_limit is None else int(window_limit)
                    ),
                },
            )
            .execute()
        )
    except Exception as exc:  # missing migration, Supabase outage, bad limits
        _warn_unavailable(f"{type(exc).__name__}: {exc}")
        return Reservation(True, "unavailable")

    data = getattr(response, "data", None)
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    reason = _denial_reason(data)
    if reason is not None:
        _log("newsdata_quota_denied", run_date=normalized, source=source_name, reason=reason)
        return Reservation(False, reason)
    if data is True or data == GRANTED:  # `True` keeps a pre-sentinel RPC working
        return Reservation(True, "granted")
    _warn_unavailable(f"unexpected_response:{data!r}")
    return Reservation(True, "unavailable")


def _denial_reason(data: object) -> str | None:
    """Map an RPC response to a denial reason, or None when it granted.

    A bare ``False`` comes from a pre-sentinel version of the RPC and is read as
    a window denial: retryable, so a stale function cannot turn a transient
    denial into silent, terminal coverage loss.
    """
    if data is False or data == DENIED_WINDOW:
        return "window"
    if data == DENIED_DAILY:
        return "daily"
    return None
