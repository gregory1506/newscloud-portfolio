"""Fail-closed adapter for the private U.S. ``last30days`` shadow pilot.

This module deliberately produces an attention-signal document, not a
NewsCloud coverage or sentiment input. It contains no scoring hooks into the
canonical daily pipeline.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


UPSTREAM_VERSION = "v3.23.0"
UPSTREAM_COMMIT = "1f378527b229ffcb00102b6440e49fa06c582443"
UPSTREAM_SCHEMA_VERSION = "1.2"
ADAPTER_VERSION = "newscloud-us-attention-v1"

SOURCE_STATUSES = {
    "ok",
    "no-results",
    "partial",
    "rate-limited",
    "auth-failed",
    "unreachable",
    "timeout",
    "schema-drift",
    "skipped-unconfigured",
    "error",
}
HEALTHY_SOURCE_STATUSES = {"ok", "no-results"}

PA_MARKERS = (
    "pennsylvania",
    "philadelphia",
    "philly",
    "pittsburgh",
    "harrisburg",
    "scranton",
    "allentown",
    "erie",
    "lancaster",
    "bethlehem",
    "pa legislature",
    "pa senate",
    "pa house",
    "governor of pa",
)


class AttentionContractError(ValueError):
    """Raised when an upstream report or local query violates the pin."""


def load_query_contract(path: str | Path | None = None) -> dict[str, Any]:
    if path is None:
        path = Path(__file__).resolve().parents[1] / "config" / "us_attention_queries.json"
    contract = json.loads(Path(path).read_text(encoding="utf-8"))
    if contract.get("contract_version") != "us-attention-queries-v1":
        raise AttentionContractError("unsupported query contract version")
    if contract.get("window_days") != 30:
        raise AttentionContractError("the v1 pilot must use a 30-day window")
    return contract


def get_query(query_id: str, scope: str, contract: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = contract or load_query_contract()
    if scope not in {"US", "US-PA"}:
        raise AttentionContractError(f"unsupported scope: {scope}")
    for query in contract["scopes"].get(scope, []):
        if query.get("id") == query_id:
            return deepcopy(query)
    raise AttentionContractError(f"query {query_id!r} is not defined for {scope}")


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    host = parts.hostname.encode("idna").decode("ascii").lower()
    try:
        parsed_port = parts.port
    except ValueError:
        return None
    port = f":{parsed_port}" if parsed_port else ""
    return urlunsplit((parts.scheme.lower(), host + port, parts.path or "/", parts.query, ""))


def _contains_term(text: str, terms: list[str]) -> bool:
    lowered = text.casefold()
    return any(re.search(rf"(?<!\w){re.escape(term.casefold())}(?!\w)", lowered) for term in terms)


def _pa_geographic_fit(text: str) -> bool:
    lowered = text.casefold()
    if any(marker in lowered for marker in PA_MARKERS):
        return True
    return bool(re.search(r"(?<![a-z])pa(?:'s)?(?![a-z])", lowered))


def _engagement(value: Any) -> dict[str, int | float]:
    if not isinstance(value, dict):
        return {}
    clean: dict[str, int | float] = {}
    for key, count in sorted(value.items()):
        if (
            isinstance(key, str)
            and key
            and isinstance(count, (int, float))
            and not isinstance(count, bool)
            and count >= 0
        ):
            clean[key] = count
    return clean


def _source_statuses(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        raise AttentionContractError("source_status must be an object")
    normalized: dict[str, str] = {}
    for source, status in sorted(value.items()):
        if not isinstance(source, str) or not source or status not in SOURCE_STATUSES:
            raise AttentionContractError("source_status contains an unknown source or status")
        normalized[source] = status
    return normalized


def _normalize_one_result(
    raw: Any, *, day_start: datetime, day_end: datetime, query: dict[str, Any], scope: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (accepted_item, None) or (None, rejection_reason)."""
    if not isinstance(raw, dict):
        return None, "malformed"
    candidate_id = raw.get("candidate_id")
    title = raw.get("title")
    source = raw.get("source")
    if not all(isinstance(item, str) and item.strip() for item in (candidate_id, title, source)):
        return None, "missing_provenance"
    url = _canonical_url(raw.get("url"))
    if url is None:
        return None, "unsafe_url"
    published_at = _parse_datetime(raw.get("published_at"))
    if published_at is None:
        return None, "missing_provenance"
    if published_at < day_start or published_at > day_end:
        return None, "outside_window"
    summary = raw.get("summary") if isinstance(raw.get("summary"), str) else ""
    searchable = f"{title} {summary}"
    if not _contains_term(searchable, query["match_terms"]):
        return None, "unmatched_issue"
    if scope == "US-PA" and not _pa_geographic_fit(searchable):
        return None, "geographic_mismatch"
    relevance = raw.get("relevance_score")
    if not isinstance(relevance, (int, float)) or isinstance(relevance, bool) or not 0 <= relevance <= 1:
        return None, "malformed"
    # The upstream scale includes 0.0, but a zero-relevance candidate is not
    # evidence of attention. The reassessment requires rejecting it explicitly
    # rather than letting it through as a weak signal.
    if relevance <= 0:
        return None, "zero_relevance"

    return {
        "candidate_id": candidate_id.strip(),
        "title": title.strip(),
        "summary": summary.strip(),
        "source": source.strip(),
        "url": url,
        "published_at": published_at.isoformat().replace("+00:00", "Z"),
        "engagement": _engagement(raw.get("engagement")),
        "relevance_score": float(relevance),
        "matched_issue": query["issue"],
        "geographic_scope": scope,
        "upstream_cluster": raw.get("cluster") if isinstance(raw.get("cluster"), int) else None,
    }, None


def normalize_report(
    report: dict[str, Any],
    *,
    scope: str,
    query_id: str,
    run_date: date,
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize one pinned agent JSON report into the shadow-data contract."""

    if report.get("schema_version") != UPSTREAM_SCHEMA_VERSION:
        raise AttentionContractError(
            f"expected upstream schema {UPSTREAM_SCHEMA_VERSION}, got {report.get('schema_version')!r}"
        )
    query = get_query(query_id, scope, contract)
    statuses = _source_statuses(report.get("source_status"))
    generated_at = _parse_datetime(report.get("generated_at"))
    if generated_at is None:
        raise AttentionContractError("generated_at must be an ISO-8601 timestamp")
    if report.get("window_days") != 30:
        raise AttentionContractError("upstream report must use the pinned 30-day window")

    day_end = datetime.combine(run_date, time.max, tzinfo=timezone.utc)
    day_start = datetime.combine(run_date - timedelta(days=29), time.min, tzinfo=timezone.utc)
    rejected = {
        "malformed": 0,
        "unsafe_url": 0,
        "outside_window": 0,
        "missing_provenance": 0,
        "unmatched_issue": 0,
        "geographic_mismatch": 0,
        "zero_relevance": 0,
        "duplicate": 0,
    }
    accepted: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()

    raw_results = report.get("results")
    if not isinstance(raw_results, list):
        raise AttentionContractError("results must be an array")

    for raw in raw_results:
        item, rejection_reason = _normalize_one_result(raw, day_start=day_start, day_end=day_end, query=query, scope=scope)
        if rejection_reason is not None:
            rejected[rejection_reason] += 1
            continue
        title_key = " ".join(item["title"].split()).casefold()
        if item["url"] in seen_urls or title_key in seen_titles:
            rejected["duplicate"] += 1
            continue
        seen_urls.add(item["url"])
        seen_titles.add(title_key)
        accepted.append(item)

    accepted.sort(key=lambda item: (-item["relevance_score"], item["candidate_id"]))
    return {
        "adapter_version": ADAPTER_VERSION,
        "job_status": "completed",
        "run_date": run_date.isoformat(),
        "scope": scope,
        "query_contract_version": (contract or load_query_contract())["contract_version"],
        "query": {"id": query["id"], "issue": query["issue"], "text": query["query"]},
        "upstream": {
            "version": UPSTREAM_VERSION,
            "commit": UPSTREAM_COMMIT,
            "schema_version": UPSTREAM_SCHEMA_VERSION,
            "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
            "window_days": 30,
        },
        "source_status": statuses,
        "degraded": any(status not in HEALTHY_SOURCE_STATUSES for status in statuses.values()),
        "results": accepted,
        "rejected_counts": rejected,
        # The agent profile carries no transcript or video fields, so per-source
        # accepted counts are the available diversity signal.
        "accepted_by_source": {
            source: sum(1 for item in accepted if item["source"] == source)
            for source in sorted({item["source"] for item in accepted})
        },
    }
