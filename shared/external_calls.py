"""Telemetry, safe error summaries, and per-worker external-call pacing.

The optional pacer spaces a provider's requests within one function instance.
It does not coordinate across instances; deployment max-instance settings bound
the aggregate rate. HTTP 429s are classified but never retried here.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import re
import threading
import time
from typing import Iterator




_SENSITIVE_QUERY = re.compile(r"([?&](?:api_?key|token)=)[^&\s]+", re.IGNORECASE)

_last_request_started: dict[str, float] = {}
_request_pacing_lock = threading.Lock()


def _pace_external_call(provider: str, interval_seconds: float) -> None:
    if interval_seconds <= 0:
        return
    with _request_pacing_lock:
        now = time.monotonic()
        previous = _last_request_started.get(provider)
        if previous is not None:
            wait_seconds = interval_seconds - (now - previous)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
        _last_request_started[provider] = time.monotonic()



def external_error_summary(error: Exception) -> str:
    """Summarize an external-call error without leaking credentials in URLs."""
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None) or getattr(error, "code", None)
    if status_code is not None:
        return f"{type(error).__name__} (HTTP {status_code})"
    return _SENSITIVE_QUERY.sub(r"\1[redacted]", str(error))



def log_external_call(
    provider: str,
    *,
    status: str,
    latency_ms: int,
    detail: str | None = None,
    error: str | None = None,
) -> None:
    """Emit one ``external_call`` line. Never raises.

    ``status`` is one of ``ok``, ``empty`` (the provider answered with nothing),
    ``rate_limited`` (HTTP 429), or ``error`` (anything that raised).
    """
    payload = {
        "event": "external_call",
        "provider": provider,
        "status": status,
        "latency_ms": latency_ms,
    }
    if detail:
        payload["detail"] = detail
    if error:
        payload["error"] = error
    print(json.dumps(payload, sort_keys=True, default=str))


@contextmanager
def track_external_call(
    provider: str,
    *,
    detail: str | None = None,
    minimum_interval_seconds: float = 0.0,
) -> Iterator[dict]:
    """Time one external call, optionally pacing calls within this worker."""
    _pace_external_call(provider, minimum_interval_seconds)
    started = time.perf_counter()
    outcome: dict = {"status": "ok"}
    try:
        yield outcome
    except Exception as exc:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None) or getattr(exc, "code", None)
        log_external_call(
            provider,
            status="rate_limited" if status_code == 429 else "error",
            latency_ms=int((time.perf_counter() - started) * 1000),
            detail=detail,
            error=type(exc).__name__,
        )
        raise
    log_external_call(
        provider,
        status=str(outcome.get("status") or "ok"),
        latency_ms=int((time.perf_counter() - started) * 1000),
        detail=detail,
    )
