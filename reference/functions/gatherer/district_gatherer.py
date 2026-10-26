"""Self-contained congressional-district gatherer (Race Board Phase 1).

Chosen approach B: this module shares nothing with the state gatherer's
``main.py`` at runtime. It owns its fetch, corpus, and headline-selection logic,
which keeps the 53-region state pipeline untouched. The small amount of
duplicated ranking logic is pinned by tests.

Hard invariants:

- District regions are ``US-<ST>-<DD>`` (see ``shared.districts``).
- This path writes **no** ``region_runs`` rows, so finalizer reconciliation and
  ``daily_runs`` readiness are unaffected.
- It writes district ``word_frequencies`` and ``source_contributions`` only.

Entry point: ``gather_district_news`` (Pub/Sub).
"""

from __future__ import annotations

import base64
from collections import Counter
from datetime import datetime, timezone
import html
import json
import os
import re

import functions_framework
import requests
from shared.districts import district_display_name, district_label, parse_district_region
from shared.regions import STATE_DISPLAY_NAMES
from shared.coverage_quality import assess_corpus
from shared.external_calls import external_error_summary, track_external_call
from shared.newsdata_quota import reserve_credit
from shared.supabase_client import get_supabase

from district_sources import get_district_sources

NEWSDATA_LATEST_ENDPOINT = "https://newsdata.io/api/1/latest"
NEWSDATA_MAX_RESULTS = int(os.environ.get("NEWSDATA_MAX_RESULTS", "10"))
NEWSDATA_TIMEOUT_SECONDS = float(os.environ.get("NEWSDATA_TIMEOUT_SECONDS", "15"))

NEWSDATA_MIN_REQUEST_INTERVAL_SECONDS = float(
    os.environ.get("NEWSCLOUD_NEWSDATA_MIN_REQUEST_INTERVAL_SECONDS", "65")
)
WORD_FREQUENCIES_TABLE = "word_frequencies"
PROVENANCE_TABLE = "source_contributions"
DISTRICT_RUNS_TABLE = "district_runs"
# The claim RPC mirrors claim_region_gather; see
# supabase/migrations/20260930120000_add_district_runs.sql and
# tests/test_district_gatherer.py.
DISTRICT_CLAIM_RPC = "claim_district_gather"
GATHER_CLAIM_STALE_MINUTES = 10
_claim_unavailable_logged = False
DISTRICT_SCORER_TOPIC_ID = "topic-score-district"
SUPPORTING_HEADLINE_LIMIT = int(os.environ.get("NEWSCLOUD_DISTRICT_HEADLINE_LIMIT", "6"))
TOP_FREQUENCY_LIMIT = 150

_COMPACT_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
    "from", "had", "has", "have", "he", "her", "his", "in", "into", "is", "it",
    "its", "new", "of", "on", "or", "said", "says", "say", "she", "that", "the",
    "their", "them", "then", "there", "these", "they", "this", "those", "to",
    "update", "video", "was", "were", "while", "who", "will", "with", "you",
    "also", "back", "can", "day", "days", "first", "get", "just", "last",
    "latest", "like", "made", "make", "may", "more", "most", "now", "one",
    "over", "some", "time", "today", "top", "two", "week", "world", "year",
}

_CIVIC_SIGNAL = re.compile(
    r"\b(government|legislature|legislative|lawmaker|senate|house|congress|"
    r"congressional|representative|candidate|campaign|election|primary|ballot|"
    r"voting|vote|democrat|republican|gop|court|judge|policy|budget|tax|funding|"
    r"federal|committee|district)\b",
    re.IGNORECASE,
)

_LOW_SIGNAL = re.compile(
    r"\b(promo code|bonus bet|draftkings|polymarket|kalshi|free livestream|"
    r"athletics|football|basketball|baseball|soccer|tournament|playoffs|ncaa)\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# Text helpers (kept local so the module does not import the state gatherer)
# --------------------------------------------------------------------------

def clean_text(text: str | None) -> str:
    return re.sub(r"[^a-z0-9\s'-]", " ", (text or "").lower())


def clean_display_text(text: str | None) -> str:
    unescaped = html.unescape(text or "")
    return re.sub(r"\s+", " ", unescaped).strip()


def truncate_text(text: str | None, limit: int = 240) -> str:
    return clean_display_text(text)[:limit]


def _natural_name(fec_name: str) -> str:
    """Convert an FEC ``LAST, FIRST MIDDLE`` name to ``First Last``."""
    name = fec_name.strip()
    if "," not in name:
        return name.title()
    last, _, rest = name.partition(",")
    first = rest.strip().split()[0] if rest.strip() else ""
    return f"{first.title()} {last.strip().title()}".strip()


def fetch_candidate_names(region: str, run_date: str) -> list[str]:
    """Candidate names for a district from gathered FEC ad-spend rows.

    Best-effort: returns [] if the lookup fails, so gathering still runs.
    """
    parsed = parse_district_region(region)
    if not parsed:
        return []
    postal, district = parsed
    label = district_label(postal, district)
    try:
        rows = (
            get_supabase()
            .table("ad_spend_signals")
            .select("candidate_name")
            .eq("run_date", run_date)
            .eq("district", label)
            .execute()
            .data
        ) or []
    except Exception as exc:  # best-effort enrichment
        print(f"district_gatherer candidate lookup failed for {region}: {exc}")
        return []
    names: list[str] = []
    for row in rows:
        raw = str(row.get("candidate_name") or "").strip()
        name = _natural_name(raw) if raw else ""
        if name and name not in names:
            names.append(name)
    return names[:3]


def district_tokens(region: str) -> set[str]:
    """Stop-token set for a district: label parts plus its state's words."""
    parsed = parse_district_region(region)
    if not parsed:
        return set()
    postal, district = parsed
    tokens = {postal.lower(), f"{postal.lower()}-{district:02d}", str(district)}
    state_name = STATE_DISPLAY_NAMES.get(f"US-{postal}", postal)
    tokens.update(clean_text(state_name).split())
    return {token for token in tokens if token}


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------

def get_newsdata_api_key() -> str:
    api_key = os.environ.get("NEWSDATA_API_KEY")
    if not api_key:
        raise ValueError("NEWSDATA_API_KEY must be set in environment variables")
    return api_key


def log_event(event: str, **fields) -> None:
    """One structured line per event, matching functions/gatherer/main.py."""
    print(json.dumps({"event": event, **fields}, sort_keys=True, default=str))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _warn_claim_unavailable(reason: str) -> None:
    """Log one missing-claim warning per process, like the state gatherer."""
    global _claim_unavailable_logged
    if _claim_unavailable_logged:
        return
    _claim_unavailable_logged = True
    log_event("district_claim_unavailable", reason=reason)


def _fetch_district_attempts(supabase, run_date: str, district: str) -> int:
    response = (
        supabase.table(DISTRICT_RUNS_TABLE)
        .select("gatherer_attempts")
        .eq("run_date", run_date)
        .eq("district", district)
        .limit(1)
        .execute()
    )
    if response.data:
        return int(response.data[0].get("gatherer_attempts") or 0)
    return 0


def record_district_state(
    run_date: str,
    district: str,
    status: str,
    *,
    error_message: str | None = None,
    increment_attempt: bool = False,
) -> None:
    """Upsert this district's gather row, mirroring update_stage_state.

    ``completed`` clears the error and any pending retry; ``failed`` and
    ``deferred`` keep the reason so the coverage audit and the finalizer can see
    why the district is short.
    """
    supabase = get_supabase()
    now_iso = _utc_now_iso()
    payload: dict[str, object] = {
        "run_date": run_date,
        "district": district,
        "gatherer_status": status,
        "last_event_at": now_iso,
    }
    if increment_attempt:
        payload["gatherer_attempts"] = (
            _fetch_district_attempts(supabase, run_date, district) + 1
        )
        payload["gatherer_started_at"] = now_iso
    if status == "completed":
        payload["last_error"] = None
        payload["next_retry_at"] = None
    elif status in ("failed", "deferred"):
        payload["last_error"] = error_message
    else:
        payload["last_error"] = None
    supabase.table(DISTRICT_RUNS_TABLE).upsert(
        payload, on_conflict="run_date,district"
    ).execute()


def _record_legacy_district_attempt(run_date: str, district: str) -> None:
    """Move the attempt counter when the claim RPC cannot be used.

    ``gatherer_attempts`` is the retry budget the finalizer reads, so a missing
    migration must fall back to the write the claim replaced.
    """
    try:
        record_district_state(run_date, district, "running", increment_attempt=True)
    except Exception as exc:  # the database is unreachable; nothing else will work either
        _warn_claim_unavailable(f"legacy_attempt_write:{type(exc).__name__}: {exc}")


def claim_district_gather(run_date: str, district: str) -> str:
    """Claim the gather stage for this delivery; see the migration.

    Returns ``claimed``, ``in_progress`` or ``already_completed``. A duplicate
    delivery must return without gathering, because the work spends a provider
    credit. A missing RPC -- the migration is applied before the function
    deploys, but the reverse order must not stop the pipeline -- logs one
    ``district_claim_unavailable`` line per process, records the attempt the old
    way, and allows the work.
    """
    try:
        response = (
            get_supabase()
            .rpc(
                DISTRICT_CLAIM_RPC,
                {
                    "p_run_date": run_date,
                    "p_district": district,
                    "p_stale_minutes": GATHER_CLAIM_STALE_MINUTES,
                },
            )
            .execute()
        )
    except Exception as exc:
        _warn_claim_unavailable(f"{type(exc).__name__}: {exc}")
        _record_legacy_district_attempt(run_date, district)
        return "claimed"

    data = getattr(response, "data", None)
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if isinstance(data, str) and data:
        return data
    _warn_claim_unavailable(f"unexpected_response:{data!r}")
    _record_legacy_district_attempt(run_date, district)
    return "claimed"



def fetch_newsdata_text(
    source: dict, run_date: str
) -> tuple[str, int, list[dict], str | None]:
    """Fetch one NewsData query.

    Returns ``(text, result_count, headline_dicts, quota_reason)``. The reason is
    None on a normal result, ``window`` or ``daily`` when the shared reservation
    denied the credit; both denials skip the provider request (see
    ``shared/newsdata_quota.py``).
    """
    params = {
        "q": source["query"],
        "country": source.get("country"),
        "language": source.get("language"),
        "size": NEWSDATA_MAX_RESULTS,
        "removeduplicate": "1",
        "apikey": get_newsdata_api_key(),
    }
    # Reserve the account-wide credit before pacing or calling out: a denied
    # reservation skips the request and the district continues with its
    # remaining sources. See shared/newsdata_quota.py.
    reservation = reserve_credit(run_date=run_date, source=str(source.get("name") or ""))
    if not reservation.granted:
        return "", 0, [], reservation.reason
    with track_external_call(
        "newsdata_io",
        detail=str(source.get("label") or ""),
        minimum_interval_seconds=NEWSDATA_MIN_REQUEST_INTERVAL_SECONDS,
    ) as call:
        response = requests.get(
            NEWSDATA_LATEST_ENDPOINT,
            params={k: v for k, v in params.items() if v is not None},
            timeout=NEWSDATA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        if not results:
            call["status"] = "empty"
    pieces: list[str] = []
    headlines: list[dict] = []
    for result in results:
        title = result.get("title", "")
        description = result.get("description") or result.get("content") or ""
        pieces.append(" ".join(piece for piece in (title, title, description) if piece))
        clean_title = clean_display_text(title)
        if not clean_title:
            continue
        headlines.append(
            {
                "title": clean_title,
                "excerpt": truncate_text(description),
                "url": result.get("link"),
                "source_name": source["name"],
                "provider": source["type"],
            }
        )
    return " ".join(pieces), len(results), headlines, None


# --------------------------------------------------------------------------
# Corpus and headline selection
# --------------------------------------------------------------------------

def _candidate_score(candidate: dict, top_frequencies: dict[str, int]) -> int:
    title_terms = set(clean_text(candidate.get("title", "")).split())
    excerpt_terms = set(clean_text(candidate.get("excerpt", "")).split())
    score = 0
    for term, count in top_frequencies.items():
        if term in title_terms:
            score += 2 * count
        elif term in excerpt_terms:
            score += count
    return score


def select_supporting_headlines(
    candidates: list[dict],
    top_frequencies: dict[str, int],
    stop_words: set[str],
    *,
    region: str,
    limit: int = SUPPORTING_HEADLINE_LIMIT,
) -> list[dict]:
    """Deterministically pick district-relevant, civic headlines.

    A headline must (a) avoid low-signal patterns, (b) carry civic signal, and
    (c) match a district/state token. Selection prefers distinct source families
    with a per-family cap so one outlet cannot dominate.
    """
    region_tokens = district_tokens(region)
    ranked: list[tuple[int, str, str, dict]] = []
    seen_titles: set[str] = set()
    for candidate in candidates:
        title = clean_display_text(candidate.get("title", ""))
        if not title or title.lower() in seen_titles:
            continue
        blob = f"{title} {candidate.get('excerpt', '')}"
        if _LOW_SIGNAL.search(blob):
            continue
        if not _CIVIC_SIGNAL.search(blob):
            continue
        if region_tokens and not (set(clean_text(blob).split()) & region_tokens):
            continue
        seen_titles.add(title.lower())
        ranked.append(
            (
                _candidate_score(candidate, top_frequencies),
                (candidate.get("source_name") or "").lower(),
                title,
                candidate,
            )
        )

    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))

    family_counts: Counter[str] = Counter()
    family_cap = max(1, (limit + 1) // 2)
    selected: list[dict] = []
    for _, _, _, candidate in ranked:
        family = (candidate.get("source_name") or "").lower()
        if family_counts[family] >= family_cap:
            continue
        family_counts[family] += 1
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def build_district_corpus(
    *,
    region: str,
    run_date: str,
    sources: list[dict],
    all_text_parts: list[str],
    headline_candidates: list[dict],
) -> dict:
    all_text = " ".join(all_text_parts)
    stop_words = set(_COMPACT_STOP_WORDS)
    stop_words.update(district_tokens(region))
    for source in sources:
        stop_words.update(clean_text(source["name"]).split())
    words = clean_text(all_text).split()
    filtered = [word for word in words if word not in stop_words and len(word) > 2]
    top_frequencies = dict(Counter(filtered).most_common(TOP_FREQUENCY_LIMIT))
    supporting = select_supporting_headlines(
        headline_candidates,
        top_frequencies,
        stop_words,
        region=region,
        limit=SUPPORTING_HEADLINE_LIMIT,
    )
    return {
        "region": region,
        "run_date": run_date,
        "frequencies": top_frequencies,
        "supporting_headlines": supporting,
    }


def build_source_record(
    region: str,
    run_date: str,
    source: dict,
    *,
    result_count: int,
    text: str,
    status: str,
    error_message: str | None = None,
) -> dict:
    return {
        "region": region,
        "date": run_date,
        "provider": source["type"],
        "source_name": source["name"],
        "source_query": source.get("query"),
        "source_url": source.get("url"),
        "result_count": result_count,
        "text_char_count": len(text),
        "token_count": len(clean_text(text).split()),
        "status": status,
        "error_message": error_message,
    }


def publish_district_frequencies(region: str, run_date: str, frequencies: dict) -> None:
    """Publish district frequencies to the district scorer topic.

    Kept on its own topic so the generator (which shares the state scorer's
    topic) never tries to render a wordcloud for a district region. Publishing
    failures are the caller's to swallow: gathering has already persisted.
    """
    from google.cloud import pubsub_v1
    from shared.gcp_env import get_project_id

    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(get_project_id(), DISTRICT_SCORER_TOPIC_ID)
    payload = json.dumps({"region": region, "date": run_date, "frequencies": frequencies})
    publisher.publish(topic_path, data=payload.encode("utf-8")).result()


def persist_district(    *,
    region: str,
    run_date: str,
    frequencies: dict,
    supporting_headlines: list[dict],
    source_records: list[dict],
) -> None:
    supabase = get_supabase()
    if source_records:
        supabase.table(PROVENANCE_TABLE).upsert(
            source_records,
            on_conflict="region,date,provider,source_name",
        ).execute()
    supabase.table(WORD_FREQUENCIES_TABLE).upsert(
        {
            "region": region,
            "date": run_date,
            "frequencies": frequencies,
            "supporting_headlines": supporting_headlines or [],
            "term_metrics": {},
            "topic_clusters": {},
        },
        on_conflict="region,date",
    ).execute()


def _current_district_attempt(run_date: str, district: str) -> int:
    """Return the attempt number ``claim_district_gather`` just incremented.

    Falls back to 1 when it cannot be read: deferring once is safer than
    retrying forever, and the next retry cannot defer again.
    """
    try:
        return _fetch_district_attempts(get_supabase(), run_date, district)
    except Exception:
        return 1


def _finish_district_gather(
    run_date: str,
    district: str,
    quota_reasons: list[str],
    *,
    attempt: int,
    has_corpus: bool,
) -> None:
    """Record the district's terminal gather status, mirroring the region path.

    A window denial that left the district without a corpus on the first
    attempt leaves it retryable (``deferred``) so the bounded retry can pick the
    call up once the window has room. Anything else is terminal: a district with
    a corpus is ``completed``, a district without one is ``failed`` with the
    reason, so a district that produced nothing is recorded instead of leaving
    no row at all.
    """
    window_denied = "window" in quota_reasons
    if window_denied and not has_corpus and attempt <= 1:
        record_district_state(
            run_date,
            district,
            "deferred",
            error_message="newsdata_quota_window_denied",
        )
        log_event(
            "district_gather_deferred",
            region=district,
            run_date=run_date,
            attempt=attempt,
            denied_source_count=len(quota_reasons),
        )
        return

    if not has_corpus:
        if "daily" in quota_reasons:
            reason = "newsdata_quota_exhausted"
        elif window_denied:
            reason = "newsdata_quota_window_exhausted"
        else:
            reason = "empty_corpus"
        record_district_state(run_date, district, "failed", error_message=reason)
        log_event(
            "district_gather_short",
            region=district,
            run_date=run_date,
            attempt=attempt,
            reason=reason,
        )
        return

    record_district_state(run_date, district, "completed")


def _collect_district_sources(
    region: str, run_date: str, sources: list[dict]
) -> tuple[list[str], list[dict], list[dict], list[str]]:
    """Fetch every source, degrading per source.

    Returns ``(all_text_parts, headline_candidates, source_records,
    quota_reasons)``. A quota denial is recorded as its own source status rather
    than "empty" so coverage audits can tell it apart from a quiet provider (see
    ``shared/newsdata_quota.py``).
    """
    all_text_parts: list[str] = []
    headline_candidates: list[dict] = []
    source_records: list[dict] = []
    quota_reasons: list[str] = []
    for source in sources:
        try:
            text, result_count, headlines, quota_reason = fetch_newsdata_text(source, run_date)
            if quota_reason == "window":
                status = "quota_deferred"
            elif quota_reason == "daily":
                status = "quota_exhausted"
            else:
                status = "success"
            if quota_reason:
                quota_reasons.append(quota_reason)
                log_event(
                    "newsdata_quota_deferred" if quota_reason == "window"
                    else "newsdata_quota_exhausted",
                    stage="district",
                    region=region,
                    run_date=run_date,
                    source=str(source.get("name") or ""),
                    reason=quota_reason,
                    retry_supported=False,
                )
            source_records.append(
                build_source_record(
                    region, run_date, source,
                    result_count=result_count, text=text, status=status,
                )
            )
            all_text_parts.append(text)
            headline_candidates.extend(headlines)
        except Exception as exc:  # degrade per source; district gathering is enrichment
            source_records.append(
                build_source_record(
                    region, run_date, source,
                    result_count=0, text="", status="error",
                    error_message=external_error_summary(exc),
                )
            )
            print(
                f"district_gatherer source failed for {region} ({source['name']}): "
                f"{external_error_summary(exc)}"
            )
    return all_text_parts, headline_candidates, source_records, quota_reasons


def _persist_district_result(
    region: str, run_date: str, corpus: dict, source_records: list[dict]
) -> None:
    """Persist a district corpus and forward it to the scorer topic.

    A corpus too thin to move the rating's coverage half still produces a band,
    which is how a district looks measured when it is not. Name it here; the
    leaning half of the same check belongs to the scorer, which holds the
    lexicon. See shared/coverage_quality.py.
    """
    quality = assess_corpus(corpus["supporting_headlines"])
    if not quality["ok"]:
        log_event("district_corpus_thin", region=region, run_date=run_date, **quality)

    persist_district(
        region=region,
        run_date=run_date,
        frequencies=corpus["frequencies"],
        supporting_headlines=corpus["supporting_headlines"],
        source_records=source_records,
    )
    try:
        publish_district_frequencies(region, run_date, corpus["frequencies"])
    except Exception as exc:  # non-fatal: frequencies are already persisted
        print(f"district_gatherer publish failed for {region}: {exc}")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def parse_district_event(cloud_event) -> tuple[str, str, tuple[str, ...]] | None:
    try:
        encoded = cloud_event.data["message"]["data"]
        payload = json.loads(base64.b64decode(encoded).decode("utf-8"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"district_gatherer ignored malformed event: {exc}")
        return None

    region = payload.get("district") or payload.get("region")
    run_date = payload.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not parse_district_region(str(region or "")):
        print(f"district_gatherer ignored invalid district: {region!r}")
        return None
    names = tuple(str(n) for n in (payload.get("candidate_names") or []) if str(n).strip())
    return str(region), str(run_date), names


@functions_framework.cloud_event
def gather_district_news(cloud_event):
    parsed = parse_district_event(cloud_event)
    if parsed is None:
        return
    region, run_date, candidate_names = parsed

    # Claim before doing anything: Pub/Sub delivers at least once, so this
    # delivery may be a duplicate. Losing the claim is cheap; gathering again
    # spends another provider credit.
    claim = claim_district_gather(run_date, region)
    if claim != "claimed":
        log_event(
            "gather_claim_skipped",
            stage="district",
            region=region,
            run_date=run_date,
            reason=claim,
        )
        return

    postal, district = parse_district_region(region)
    state_name = STATE_DISPLAY_NAMES.get(f"US-{postal}", postal)
    attempt = _current_district_attempt(run_date, region)

    try:
        # Merge any event-provided names with FEC candidate names for this district.
        candidate_names = tuple(
            dict.fromkeys([*candidate_names, *fetch_candidate_names(region, run_date)])
        )

        sources = get_district_sources(
            postal=postal,
            district=district,
            state_name=state_name,
            candidate_names=candidate_names,
        )

        all_text_parts, headline_candidates, source_records, quota_reasons = (
            _collect_district_sources(region, run_date, sources)
        )

        corpus = build_district_corpus(
            region=region,
            run_date=run_date,
            sources=sources,
            all_text_parts=all_text_parts,
            headline_candidates=headline_candidates,
        )
        has_corpus = bool(corpus["frequencies"])
        if has_corpus:
            _persist_district_result(region, run_date, corpus, source_records)
        else:
            # No frequencies to persist, but the district_runs row below still
            # records the attempt and its reason.
            print(f"district_gatherer empty corpus for {region} on {run_date}")

        _finish_district_gather(
            run_date,
            region,
            quota_reasons,
            attempt=attempt,
            has_corpus=has_corpus,
        )

        if has_corpus:
            print(json.dumps({
                "event": "district_gather_completed",
                "region": region,
                "run_date": run_date,
                "label": district_label(postal, district),
                "display_name": district_display_name(postal, district, state_name),
                "term_count": len(corpus["frequencies"]),
                "supporting_headline_count": len(corpus["supporting_headlines"]),
            }, sort_keys=True))
    except Exception as exc:
        reason = external_error_summary(exc)
        record_district_state(run_date, region, "failed", error_message=reason)
        log_event("district_gather_failed", region=region, run_date=run_date, error=reason)
        print(f"district_gatherer failed for {region} on {run_date}: {exc}")
