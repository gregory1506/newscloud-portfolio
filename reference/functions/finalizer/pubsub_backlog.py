"""Read the Pub/Sub backlog behind the gatherer subscriptions.

A region or district row still at ``gatherer_status='none'`` is ambiguous: its
message may be waiting behind the pacer, or it may never have been delivered at
all. On 2026-09-30 the orchestrator's fan-out burst hit a ``--max-instances=1``
gatherer and outpaced its request timeout. The refused deliveries were retried
to exhaustion and dead-lettered, so the gather subscriptions drained to zero
while 48 regions sat at ``gatherer_attempts=0`` - the messages were parked where
the pipeline could not see them.

Only the backlog tells those two apart, and it lives in Cloud Monitoring rather
than the Pub/Sub Admin API, whose Subscription resource carries no message count.

Every failure here is soft: ``None`` means "not readable" and the caller falls
back to the age-based queued window, which is the conservative choice - it
delays a dropped run rather than re-spending provider credits on a queued one.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
import time
import urllib.parse
import urllib.request

BACKLOG_METRIC = "pubsub.googleapis.com/subscription/num_undelivered_messages"
MONITORING_SCOPE = "https://www.googleapis.com/auth/monitoring.read"
_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
)

# The reconciler asks about every region in a run, so the answer is cached for a
# couple of minutes: one Monitoring read instead of one per region, and the
# metric is only sampled once a minute anyway.
_CACHE_TTL_SECONDS = 120
_cache: dict[str, tuple[float, float | None]] = {}


def _access_token() -> str | None:
    """Return a monitoring.read token from the runtime service account."""
    query = urllib.parse.urlencode({"scopes": MONITORING_SCOPE})
    request = urllib.request.Request(
        f"{_METADATA_TOKEN_URL}?{query}", headers={"Metadata-Flavor": "Google"}
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read())["access_token"]
    except Exception:
        return None


def undelivered_messages(
    *,
    project: str,
    include: str,
    exclude: str | None = None,
    window_minutes: int = 6,
) -> float | None:
    """Total undelivered messages across matching subscriptions.

    Returns ``None`` when the metric cannot be read, so callers can tell "nothing
    is queued" apart from "we cannot tell".
    """
    token = _access_token()
    if not token:
        return None

    end = datetime.now(timezone.utc)
    start = end - timedelta(minutes=window_minutes)
    query = urllib.parse.urlencode(
        {
            "filter": f'metric.type="{BACKLOG_METRIC}"',
            "interval.startTime": start.isoformat().replace("+00:00", "Z"),
            "interval.endTime": end.isoformat().replace("+00:00", "Z"),
        }
    )
    request = urllib.request.Request(
        f"https://monitoring.googleapis.com/v3/projects/{project}/timeSeries?{query}",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read() or b"{}")
    except Exception:
        return None

    # Points arrive newest first and the metric is sampled once a minute, so the
    # first point of each series is the current backlog.
    total = 0.0
    for series in payload.get("timeSeries", []):
        labels = series.get("resource", {}).get("labels", {})
        subscription = labels.get("subscription_id", "")
        if include not in subscription or (exclude and exclude in subscription):
            continue
        points = series.get("points") or []
        if not points:
            continue
        value = points[0].get("value", {})
        total += float(value.get("int64Value") or value.get("doubleValue") or 0)
    return total


def cached_undelivered_messages(
    *,
    project: str,
    include: str,
    exclude: str | None = None,
    window_minutes: int = 6,
    ttl_seconds: int = _CACHE_TTL_SECONDS,
) -> float | None:
    """``undelivered_messages`` with a short process-level cache."""
    key = f"{project}|{include}|{exclude}"
    now = time.monotonic()
    cached = _cache.get(key)
    if cached and now - cached[0] < ttl_seconds:
        return cached[1]
    value = undelivered_messages(
        project=project, include=include, exclude=exclude, window_minutes=window_minutes
    )
    _cache[key] = (now, value)
    # Logged on each cache miss so a production run shows whether the read worked:
    # an unreadable metric takes the conservative path silently, which would
    # otherwise be indistinguishable from a healthy one.
    if value is None:
        print(f"Pub/Sub backlog unreadable for {key}; keeping the queued window")
    else:
        print(f"Pub/Sub backlog for {key}: {value}")
    return value
