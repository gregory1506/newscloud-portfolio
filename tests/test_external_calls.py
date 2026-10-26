"""Unit coverage for the external-call telemetry helper."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.external_calls import external_error_summary, track_external_call

pytestmark = pytest.mark.unit


def lines(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


def test_successful_call_logs_provider_latency_and_detail(capsys):
    with track_external_call("newsdata_io", detail="Pennsylvania news") as call:
        call["status"] = "empty"

    entry = lines(capsys)[0]
    assert entry["event"] == "external_call"
    assert entry["provider"] == "newsdata_io"
    assert entry["status"] == "empty"
    assert entry["detail"] == "Pennsylvania news"
    assert entry["latency_ms"] >= 0
    assert "error" not in entry


def test_default_status_is_ok(capsys):
    with track_external_call("fec"):
        pass

    assert lines(capsys)[0]["status"] == "ok"


def test_failure_logs_the_error_type_and_reraises(capsys):
    with pytest.raises(ValueError, match="boom"):
        with track_external_call("fec", detail="https://api.open.fec.gov/v1/candidates/") as call:
            call["status"] = "rate_limited"
            raise ValueError("boom")

    entry = lines(capsys)[0]
    assert entry["status"] == "error"
    assert entry["error"] == "ValueError"
    assert entry["detail"].endswith("/candidates/")


def test_http_429_logs_rate_limited_and_summary_drops_request_credentials(capsys):
    error = RuntimeError(
        "429 Client Error for https://example.test/?apikey=secret-value",
    )
    error.response = type("Response", (), {"status_code": 429})()

    with pytest.raises(RuntimeError):
        with track_external_call("newsdata_io"):
            raise error

    entry = lines(capsys)[0]
    assert entry["status"] == "rate_limited"
    assert external_error_summary(error) == "RuntimeError (HTTP 429)"
    assert "secret-value" not in external_error_summary(error)


def test_timeout_summary_redacts_api_key_query_value():
    summary = external_error_summary(
        TimeoutError("GET https://example.test/?api_key=secret-value timed out")
    )

    assert summary == "GET https://example.test/?api_key=[redacted] timed out"
    assert "secret-value" not in summary



def test_external_calls_respect_per_worker_minimum_interval(monkeypatch, capsys):
    from shared import external_calls

    clock = [10.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(external_calls.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(external_calls.time, "sleep", sleep)
    external_calls._last_request_started.clear()

    with track_external_call("newsdata_io", minimum_interval_seconds=65):
        pass
    clock[0] += 0.3
    with track_external_call("newsdata_io", minimum_interval_seconds=65):
        pass

    capsys.readouterr()
    assert sleeps == pytest.approx([64.7])
    external_calls._last_request_started.clear()

