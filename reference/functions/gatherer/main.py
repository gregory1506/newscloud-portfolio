import base64
from collections import Counter
from datetime import datetime, timezone
import email.utils
import html
import json
import os
import re
import socket
import urllib.error
import urllib.request

import feedparser
import functions_framework
from google.cloud import pubsub_v1
import requests
from shared.supabase_client import get_supabase
from shared.external_calls import external_error_summary, track_external_call
from shared.gcp_env import get_project_id
from shared.newsdata_quota import reserve_credit
from supabase import Client

from config import (
    Region,
    get_extra_stop_words_for_region,
    get_region_display_name,
    get_region_stop_term_version,
    get_region_stop_tokens,
    get_sources_for_region,
)
# Race Board district gatherer entry point (deployed separately from this same
# source tree with --entry-point=gather_district_news). Imported here so the
# Cloud Functions runtime can resolve the target from the main module.
from district_gatherer import gather_district_news  # noqa: F401
from term_valence import normalized_term_valence
from topic_model import build_topic_clusters
from gemini_fallback_agent import fetch_headlines_via_adk
from shared.tracing import get_tracer
from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace

tracer = get_tracer("gatherer")

NEWSDATA_LATEST_ENDPOINT = "https://newsdata.io/api/1/latest"
NEWSDATA_MAX_RESULTS = int(os.environ.get("NEWSDATA_MAX_RESULTS", "10"))
NEWSDATA_TIMEOUT_SECONDS = float(os.environ.get("NEWSDATA_TIMEOUT_SECONDS", "15"))

NEWSDATA_MIN_REQUEST_INTERVAL_SECONDS = float(
    os.environ.get("NEWSCLOUD_NEWSDATA_MIN_REQUEST_INTERVAL_SECONDS", "65")
)
PROVENANCE_TABLE = "source_contributions"
GEMINI_API_KEY_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
GEMINI_GATHERER_MODEL = os.environ.get("NEWSCLOUD_GEMINI_GATHERER_MODEL", "gemini-3.1-flash-lite")
GEMINI_GATHERER_TIMEOUT_SECONDS = float(os.environ.get("NEWSCLOUD_GEMINI_GATHERER_TIMEOUT_SECONDS", "20"))
GEMINI_MAX_RESULTS = int(os.environ.get("NEWSCLOUD_GEMINI_MAX_RESULTS", "8"))
GEMINI_FALLBACK_MODE = os.environ.get("NEWSCLOUD_GEMINI_FALLBACK_MODE", "adk").strip().lower()
GEMINI_FALLBACK_SUPPORTING_HEADLINE_FLOOR = int(os.environ.get("NEWSCLOUD_GEMINI_FALLBACK_SUPPORTING_HEADLINE_FLOOR", "2"))
GEMINI_FALLBACK_DISTINCT_SOURCE_FLOOR = int(os.environ.get("NEWSCLOUD_GEMINI_FALLBACK_DISTINCT_SOURCE_FLOOR", "2"))
GEMINI_FALLBACK_FILTERED_TOKEN_FLOOR = int(os.environ.get("NEWSCLOUD_GEMINI_FALLBACK_FILTERED_TOKEN_FLOOR", "120"))
GEMINI_FALLBACK_MAX_ACCEPTED_HEADLINES = int(os.environ.get("NEWSCLOUD_GEMINI_FALLBACK_MAX_ACCEPTED_HEADLINES", "3"))
RSS_STALE_DAYS = max(0, int(os.environ.get("NEWSCLOUD_RSS_STALE_DAYS", "30")))
RSS_FETCH_TIMEOUT_SECONDS = max(
    1.0, float(os.environ.get("NEWSCLOUD_RSS_FETCH_TIMEOUT_SECONDS", "10"))
)
RSS_ITEM_MAX_AGE_DAYS = max(
    0, int(os.environ.get("NEWSCLOUD_RSS_ITEM_MAX_AGE_DAYS", "7"))
)
RSS_USER_AGENT = os.environ.get(
    "NEWSCLOUD_RSS_USER_AGENT",
    "NewsCloud/1.0 (+https://tt.example.invalid/)",
).strip() or "NewsCloud/1.0 (+https://tt.example.invalid/)"
TERM_METRICS_VERSION = "tt-term-v2"
TERM_METRICS_LIMIT = 50
GEMINI_FALLBACK_REGIONS = {
    value.strip().upper()
    for value in os.environ.get(
        "NEWSCLOUD_GEMINI_FALLBACK_REGIONS",
        ",".join(region.value for region in Region),
    ).split(",")
    if value.strip()
}
GEMINI_SOURCE = {
    "name": "Gemini Google Search",
    "type": "gemini_google_search",
}


def get_newsdata_api_key() -> str:
    api_key = os.environ.get("NEWSDATA_API_KEY")
    if not api_key:
        raise ValueError("NEWSDATA_API_KEY must be set in environment variables")
    return api_key


PROJECT_ID = get_project_id()
TOPIC_ID = "topic-generate-wordcloud"
FINALIZER_TOPIC_ID = "topic-finalize-run"
WORD_FREQUENCIES_TABLE = "word_frequencies"
STAGE_NAME = "gatherer"

# Source-record statuses for a NewsData credit that was denied by the shared
# reservation. They are distinct from "empty" so the finalizer's retry path and
# the coverage audit can tell a quota decision from a quiet provider.
SOURCE_STATUS_QUOTA_DEFERRED = "quota_deferred"
SOURCE_STATUS_QUOTA_EXHAUSTED = "quota_exhausted"

# The gather stage is claimed before any work so a duplicate delivery costs a
# database read instead of a NewsData credit; see
# supabase/migrations/20260928140000_add_region_gather_claim.sql.
CLAIM_RPC = "claim_region_gather"
GATHER_CLAIM_STALE_MINUTES = 10
_claim_unavailable_logged = False

# A basic static set of English stop words to keep the function lightweight (no heavy NLTK downloads)
STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't", "as", "at",
    "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can't", "cannot", "could",
    "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during", "each", "few", "for",
    "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's",
    "her", "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm",
    "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't",
    "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours",
    "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't",
    "so", "some", "such", "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there",
    "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't",
    "what", "what's", "when", "when's", "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's",
    "with", "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself",
    "yourselves", "will", "new", "says", "say", "said", "update", "video", "nbsp", "amp", "quot",
    "also", "back", "best", "can", "day", "days", "feel", "first", "get", "gets", "getting", "got", "just",
    "last", "latest", "life", "like", "live", "made", "make", "man", "many", "may", "moment", "month", "months",
    "much", "newest", "now", "old", "one", "people", "read", "reading", "review", "second", "see",
    "set", "three", "time", "today", "top", "two", "way", "week", "weeks", "woman", "world", "year", "years",
    "yesterday",
}

LOW_SIGNAL_HEADLINE_PATTERNS = [
    r"\bpromo code\b",
    r"\bbonus bets?\b",
    r"\bdraftkings\b",
    r"\bpolymarket\b",
    r"\bkalshi\b",
    r"\bfree livestream\b",
    r"\bathletics?\b",
    r"\bofficial athletics website\b",
    r"\bfootball\b",
    r"\bbasketball\b",
    r"\bbaseball\b",
    r"\bsoftball\b",
    r"\bsoccer\b",
    r"\btrack (and|&) field\b",
    r"\btournament\b",
    r"\bchampionships?\b",
    r"\bplayoffs?\b",
    r"\bncaa\b",
    r"\bsec\b",
    r"\bbig ten\b",
    r"\bmountain west\b",
    r"\buniversity athletics\b",
    r"\bfelony charges?\b",
    r"\bcriminal case\b",
    r"\baccused\b",
    r"\bbachelor\b",
]

CIVIC_SIGNAL_PATTERNS = [
    r"\bgovernment\b",
    r"\bstatehouse\b",
    r"\bcapitol\b",
    r"\blegislature\b",
    r"\blegislation\b",
    r"\blegislative\b",
    r"\blegislator(s)?\b",
    r"\blawmaker(s)?\b",
    r"\bsenate\b",
    r"\bassembly\b",
    r"\bhouse speaker\b",
    r"\bhouse district\b",
    r"\blegislative house\b",
    r"\bu\.?s\.? house\b",
    r"\bstate house\b",
    r"\bgovernor\b",
    r"\bmayor(al)?\b",
    r"\bcity council\b",
    r"\bcouncilman\b",
    r"\bcouncilwoman\b",
    r"\bcouncilmember\b",
    r"\bschool board\b",
    r"\bboard of education\b",
    r"\bsecretary of state\b",
    r"\battorney general\b",
    r"\bstate treasurer\b",
    r"\bspeaker\b",
    r"\belection(s)?\b",
    r"\bprimary\b",
    r"\bballot\b",
    r"\bvoting\b",
    r"\bvote\b",
    r"\bcampaign\b",
    r"\bcandidate(s)?\b",
    r"\bdemocrat(ic)?\b",
    r"\brepublican(s)?\b",
    r"\bgop\b",
    r"\bcourt(s)?\b",
    r"\bjudge(s)?\b",
    r"\blawsuit(s)?\b",
    r"\bpolicy\b",
    r"\bbudget\b",
    r"\btax(es)?\b",
    r"\bspending\b",
    r"\bfunding\b",
    r"\bfederal\b",
    r"\bpublic hearing\b",
    r"\bcommittee\b",
    r"\bunion\b",
]

BOILERPLATE_PATTERNS = (
    r"\bcontinue reading\b",
    r"\bread more\b",
    r"\bclick here\b",
    r"\bsign up\b",
    r"\blive updates\b",
    r"\blive update\b",
)
RSS_SUMMARY_TRAILING_PATTERNS = (
    r"\bthe post\b.*?\b(?:first\s+)?appeared on\b.*$",
    r"\bfor more (?:local )?stories\b.*$",
    r"\b(?:read|continue reading) (?:the )?(?:full )?(?:article|story)\b.*$",
    r"\bsubscribe (?:to|for)\b.*$",
)
RSS_SUMMARY_LABEL_PATTERNS = (
    r"\b(?:image|media)\s+(?:caption|source)\b\s*[:,-]?",
    r"\bcaption\s*[:,-]",
    r"\badvertisement\b",
)
MAX_SUPPORTING_HEADLINES = 5
GEMINI_ALLOWED_TOPICS_BY_REGION = {
    "US-PA": [
        "Pennsylvania state politics",
        "Pennsylvania elections",
        "Pennsylvania legislature",
        "Pennsylvania governor",
        "Pennsylvania courts",
        "Pennsylvania public policy",
        "Pennsylvania labor",
        "Pennsylvania education policy",
        "Pennsylvania housing policy",
        "Pennsylvania energy policy",
    ],
}


def normalize_run_date(run_date: str | None) -> str:
    if not run_date:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return datetime.strptime(run_date, "%Y-%m-%d").date().isoformat()


def clean_text(text: str) -> str:
    """Removes HTML tags and punctuation, returns lowercase text."""
    text = html.unescape(text or "")
    text = text.replace("\xa0", " ")
    text = normalize_contractions(text)
    text = re.sub(r"<[^>]+>", " ", text)
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[^a-zA-Z\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def normalize_contractions(text: str) -> str:
    """Expand common contractions before punctuation stripping creates fragments."""
    text = (text or "").replace("’", "'").replace("‘", "'")
    text = re.sub(r"\bwon't\b", "will not", text, flags=re.IGNORECASE)
    text = re.sub(r"\bcan't\b", "cannot", text, flags=re.IGNORECASE)
    text = re.sub(r"n't\b", " not", text, flags=re.IGNORECASE)
    text = re.sub(r"'(?:re|ve|ll|d|m|s)\b", "", text, flags=re.IGNORECASE)
    return text


def clean_display_text(text: str) -> str:
    text = html.unescape(text or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def truncate_text(text: str, *, max_length: int = 180) -> str:
    text = clean_display_text(text)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 1].rstrip()}…"


def clean_rss_summary(summary: str) -> str:
    """Keep article summary prose while removing RSS/CMS presentation furniture."""
    summary = html.unescape(summary or "").replace("\xa0", " ")
    summary = re.sub(
        r"<(?:figure|figcaption)\b[^>]*>.*?</(?:figure|figcaption)>",
        " ",
        summary,
        flags=re.IGNORECASE | re.DOTALL,
    )
    summary = re.sub(r"<img\b[^>]*>", " ", summary, flags=re.IGNORECASE | re.DOTALL)

    paragraphs = re.findall(
        r"<p\b[^>]*>(.*?)</p>",
        summary,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if paragraphs:
        kept_paragraphs = []
        for paragraph in paragraphs:
            paragraph_text = clean_display_text(paragraph)
            if re.search(
                r"^\s*(?:the post\b|(?:image|media)\s+(?:caption|source)\b|"
                r"caption\s*[:,-]|advertisement\b|subscribe\b)",
                paragraph_text,
                re.IGNORECASE,
            ):
                continue
            kept_paragraphs.append(paragraph)
        if kept_paragraphs:
            summary = " ".join(kept_paragraphs)

    summary = clean_display_text(summary)
    for pattern in RSS_SUMMARY_TRAILING_PATTERNS:
        summary = re.sub(pattern, " ", summary, flags=re.IGNORECASE | re.DOTALL)
    for pattern in RSS_SUMMARY_LABEL_PATTERNS:
        summary = re.sub(pattern, " ", summary, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", summary).strip()


def get_gemini_api_key() -> str | None:
    for env_var in GEMINI_API_KEY_ENV_VARS:
        value = os.environ.get(env_var)
        if value:
            return value
    return None


def log_event(event: str, **fields):
    payload = {"event": event, **fields}
    print(json.dumps(payload, sort_keys=True))


def build_rss_headline(entry: dict, source: dict) -> dict | None:
    title = entry.get("title", "")
    clean_title = clean_display_text(title)
    if not clean_title:
        return None
    return {
        "title": clean_title,
        "excerpt": truncate_text(clean_rss_summary(entry.get("summary", ""))),
        "url": entry.get("link"),
        "published_date": extract_entry_run_date(entry),
        "source_name": source["name"],
        "provider": source["type"],
    }


def rss_entry_is_excluded(entry: dict, source: dict) -> bool:
    """Reject source-declared non-editorial URL categories before the corpus."""
    url = str(entry.get("link") or "").lower()
    return any(
        str(pattern).lower() in url
        for pattern in source.get("exclude_url_patterns", [])
        if pattern
    )


def select_rss_entries_for_run(
    entries: list[dict],
    *,
    run_date: str,
    max_age_days: int = RSS_ITEM_MAX_AGE_DAYS,
) -> tuple[list[dict], dict]:
    """Select current RSS items, falling back only when every item is undated."""
    target_date = datetime.strptime(run_date, "%Y-%m-%d").date()
    dated_entries = [
        (entry, published_date)
        for entry in entries
        if (published_date := extract_entry_run_date(entry))
    ]
    if not dated_entries:
        return entries, {
            "fetched_count": len(entries),
            "accepted_count": len(entries),
            "dropped_count": 0,
            "dated_count": 0,
            "undated_count": len(entries),
            "used_undated_fallback": bool(entries),
            "max_age_days": max_age_days,
        }

    accepted = []
    for entry, published_date in dated_entries:
        item_date = datetime.strptime(published_date, "%Y-%m-%d").date()
        age_days = (target_date - item_date).days
        # A historical retry must never borrow articles published after its
        # run date.  ``abs`` looked harmless for same-day collection (where
        # future items do not exist yet) but contaminated retrospective runs.
        if 0 <= age_days <= max_age_days:
            accepted.append(entry)
    return accepted, {
        "fetched_count": len(entries),
        "accepted_count": len(accepted),
        "dropped_count": len(entries) - len(accepted),
        "dated_count": len(dated_entries),
        "undated_count": len(entries) - len(dated_entries),
        "used_undated_fallback": False,
        "max_age_days": max_age_days,
    }


def extract_rss_source_content(
    source: dict,
    *,
    run_date: str,
    max_age_days: int = RSS_ITEM_MAX_AGE_DAYS,
) -> dict:
    # feedparser delegates remote URLs to urllib without exposing a timeout.
    # Gen2 runs this function at concurrency 1, so a tightly scoped process
    # default safely bounds one source without affecting another request.
    previous_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(RSS_FETCH_TIMEOUT_SECONDS)
    try:
        feed = feedparser.parse(source["url"], agent=RSS_USER_AGENT)
    finally:
        socket.setdefaulttimeout(previous_timeout)
    fetched_entries = list(feed.entries)
    entries = [entry for entry in fetched_entries if not rss_entry_is_excluded(entry, source)]
    selected_entries, recency = select_rss_entries_for_run(
        entries,
        run_date=run_date,
        max_age_days=max_age_days,
    )
    excluded_count = len(fetched_entries) - len(entries)
    recency["fetched_count"] = len(fetched_entries)
    recency["dropped_count"] = len(fetched_entries) - len(selected_entries)
    recency["excluded_count"] = excluded_count
    pieces = []
    headlines = []
    raw_headlines = []
    for entry in entries:
        headline = build_rss_headline(entry, source)
        if headline:
            raw_headlines.append(headline)
    for entry in selected_entries:
        title = entry.get("title", "")
        summary = clean_rss_summary(entry.get("summary", ""))
        pieces.append(f"{title} {title} {summary}")
        headline = build_rss_headline(entry, source)
        if headline:
            headlines.append(headline)
    return {
        "text": " ".join(piece for piece in pieces if piece),
        "result_count": len(selected_entries),
        "headlines": headlines,
        "raw_headlines": raw_headlines,
        "recency": recency,
    }


def extract_rss_source_text(source: dict, run_date: str | None = None) -> tuple[str, int, list[dict]]:
    """Compatibility wrapper returning only accepted RSS content."""
    content = extract_rss_source_content(
        source,
        run_date=normalize_run_date(run_date),
    )
    return content["text"], content["result_count"], content["headlines"]


def build_rss_staleness_warning(
    region: Region,
    source: dict,
    headlines: list[dict],
    *,
    run_date: str,
    as_of: datetime | None = None,
    stale_days: int = RSS_STALE_DAYS,
) -> dict | None:
    """Return a structured warning when an RSS source's newest dated item is stale."""
    dated_items = []
    for headline in headlines:
        published_date = headline.get("published_date")
        if not published_date:
            continue
        try:
            dated_items.append(datetime.strptime(published_date, "%Y-%m-%d").date())
        except (TypeError, ValueError):
            continue

    if not dated_items:
        return None

    newest_item_date = max(dated_items)
    observed_at = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    age_days = max(0, (observed_at - newest_item_date).days)
    if age_days <= stale_days:
        return None

    return {
        "severity": "WARNING",
        "marker": "rss_source_stale",
        "region": region.value,
        "provider": source["type"],
        "source_name": source["name"],
        "source_url": source["url"],
        "run_date": run_date,
        "newest_item_date": newest_item_date.isoformat(),
        "age_days": age_days,
        "stale_days": stale_days,
    }


def extract_newsdata_result_text(result: dict) -> str:
    title = result.get("title", "")
    description = result.get("description") or result.get("content") or ""
    pieces = [title, title, description]
    return " ".join(piece for piece in pieces if piece)


def extract_headline_candidate_text(candidate: dict) -> str:
    parts = [
        candidate.get("title", ""),
        candidate.get("title", ""),
        candidate.get("excerpt", ""),
    ]
    return " ".join(part for part in parts if part)


def extract_result_run_date(result: dict) -> str | None:
    for field in ("pubDate", "pubdate", "published_at", "publishedAt"):
        value = result.get(field)
        if not value:
            continue
        match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
        if match:
            return match.group(0)
    return None


def _entry_run_date_from_text(entry: dict) -> str | None:
    for field in ("published", "updated"):
        value = entry.get(field)
        if value:
            match = re.search(r"\d{4}-\d{2}-\d{2}", str(value))
            if match:
                return match.group(0)
    return None


def _entry_run_date_from_parsed_tuple(entry: dict) -> str | None:
    for field in ("published_parsed", "updated_parsed"):
        value = entry.get(field)
        if value and len(value) >= 6:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc).date().isoformat()
            except (TypeError, ValueError):
                continue
    return None


def _entry_run_date_from_rfc2822(entry: dict) -> str | None:
    for field in ("published", "updated", "created"):
        value = entry.get(field)
        if not value:
            continue
        try:
            parsed = email.utils.parsedate_to_datetime(str(value))
        except (TypeError, ValueError, OverflowError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).date().isoformat()
    return None


def extract_entry_run_date(entry: dict) -> str | None:
    return (
        _entry_run_date_from_text(entry)
        or _entry_run_date_from_parsed_tuple(entry)
        or _entry_run_date_from_rfc2822(entry)
    )


def fetch_newsdata_source_text(
    source: dict, run_date: str
) -> tuple[str, int, list[dict], str | None]:
    """Fetch one NewsData source.

    Returns ``(text, result_count, headlines, quota_reason)``. ``quota_reason``
    is None for a normal result, ``window`` when the rolling 15-minute ceiling
    denied the credit, and ``daily`` when the run date's ceiling did. Both
    denials skip the provider request; the caller decides whether the region is
    deferred or published thin (see shared/newsdata_quota.py).
    """
    params = {
        "q": source["query"],
        "country": source.get("country"),
        "language": source.get("language"),
        "category": source.get("category"),
        "domain": source.get("domain"),
        "domainurl": source.get("domainurl"),
        "size": NEWSDATA_MAX_RESULTS,
        "removeduplicate": "1",
    }
    # Resolve configuration that can fail before spending a credit on it.
    api_key = get_newsdata_api_key()
    with tracer.start_as_current_span(
        "newsdata.fetch", attributes={"source_name": source["name"], "run_date": run_date}
    ):
        # Reserve the account-wide credit before pacing or calling out: a denied
        # reservation skips the request and the region continues with its RSS
        # sources. See shared/newsdata_quota.py.
        reservation = reserve_credit(run_date=run_date, source=str(source.get("name") or ""))
        if not reservation.granted:
            return "", 0, [], reservation.reason
        with track_external_call(
            "newsdata_io",
            detail=str(source.get("name") or ""),
            minimum_interval_seconds=NEWSDATA_MIN_REQUEST_INTERVAL_SECONDS,
        ) as call:
            response = requests.get(
                NEWSDATA_LATEST_ENDPOINT,
                params={
                    key: value
                    for key, value in {
                        **params,
                        "apikey": api_key,
                    }.items()
                    if value is not None
                },
                timeout=NEWSDATA_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            if not (response.json().get("results") or []):
                call["status"] = "empty"
    payload = response.json()
    results = payload.get("results") or []
    matching_results = [result for result in results if extract_result_run_date(result) == run_date]

    # Free-tier NewsData only exposes recent windows. If date metadata is absent,
    # keep the recent results rather than dropping the source entirely.
    effective_results = matching_results or [result for result in results if not extract_result_run_date(result)]
    pieces = [extract_newsdata_result_text(result) for result in effective_results]
    headlines = []
    for result in effective_results:
        clean_title = clean_display_text(result.get("title", ""))
        if not clean_title:
            continue
        headlines.append(
            {
                "title": clean_title,
                "excerpt": truncate_text(result.get("description") or result.get("content") or ""),
                "url": result.get("link"),
                "source_name": source["name"],
                "provider": source["type"],
            }
        )
    return " ".join(piece for piece in pieces if piece), len(effective_results), headlines, None


def build_gemini_fallback_prompt(region: Region, run_date: str) -> str:
    state_name = get_region_display_name(region)
    allowed_topics = GEMINI_ALLOWED_TOPICS_BY_REGION.get(region.value) or [f"{state_name} state politics"]
    topic_lines = "\n".join(f"- {topic}" for topic in allowed_topics)
    return f"""Find recent {state_name} political or state-government news for run_date={run_date}.

Return JSON only with this shape:
{{
  "results": [
    {{
      "title": "...",
      "source_name": "...",
      "url": "https://...",
      "published_date": "YYYY-MM-DD",
      "excerpt": "...",
      "why_relevant": "one sentence"
    }}
  ]
}}

Priorities:
{topic_lines}

Rules:
- Prefer local reporting, statehouse reporting, and credible statewide outlets.
- Exclude sports, university athletics, gambling, promotions, crime-blotter-only items, and generic national stories that only mention the state in passing.
- Exclude items not published on {run_date} unless no same-day items exist; if you use an older item, keep its exact published_date.
- Do not invent URLs, titles, sources, or dates.
- Return at most {GEMINI_MAX_RESULTS} results.
"""


def call_gemini_grounded_json(*, api_key: str, prompt: str) -> dict:
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "object",
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "source_name": {"type": "string"},
                                "url": {"type": "string"},
                                "published_date": {"type": "string"},
                                "excerpt": {"type": "string"},
                                "why_relevant": {"type": "string"},
                            },
                            "required": ["title", "source_name", "url", "published_date", "excerpt", "why_relevant"],
                        },
                    }
                },
                "required": ["results"],
            },
        },
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_GATHERER_MODEL}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=GEMINI_GATHERER_TIMEOUT_SECONDS) as response:
        response_payload = json.loads(response.read().decode("utf-8"))
    candidates = response_payload.get("candidates") or []
    if not candidates:
        return {"results": []}
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    text = "".join(part.get("text", "") for part in parts if part.get("text")).strip()
    if not text:
        return {"results": []}
    parsed = json.loads(text)
    return parsed if isinstance(parsed, dict) else {"results": []}


def fetch_gemini_fallback_payload(region: Region, run_date: str) -> dict:
    allowed_topics = GEMINI_ALLOWED_TOPICS_BY_REGION.get(region.value) or [
        f"{get_region_display_name(region)} state politics"
    ]
    if GEMINI_FALLBACK_MODE == "rest":
        api_key = get_gemini_api_key()
        if not api_key:
            return {"results": []}
        return call_gemini_grounded_json(
            api_key=api_key,
            prompt=build_gemini_fallback_prompt(region, run_date),
        )
    if GEMINI_FALLBACK_MODE != "adk":
        raise ValueError(f"Unsupported NEWSCLOUD_GEMINI_FALLBACK_MODE: {GEMINI_FALLBACK_MODE}")
    return fetch_headlines_via_adk(
        model=GEMINI_GATHERER_MODEL,
        region_code=region.value,
        region_name=get_region_display_name(region),
        run_date=run_date,
        allowed_topics=allowed_topics,
        max_results=GEMINI_MAX_RESULTS,
    )


def is_valid_gemini_result_date(run_date: str, published_date: str) -> bool:
    if published_date == run_date:
        return True
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published_date or ""):
        return False
    try:
        run_dt = datetime.strptime(run_date, "%Y-%m-%d").date()
        published_dt = datetime.strptime(published_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    return abs((run_dt - published_dt).days) <= 2


def validate_gemini_headline_candidates(
    results: list[dict],
    *,
    run_date: str,
    existing_candidates: list[dict],
) -> list[dict]:
    validated = []
    seen = {
        (clean_text(candidate.get("title", "")), (candidate.get("url") or "").strip())
        for candidate in existing_candidates
    }
    for result in results:
        title = clean_display_text(result.get("title", ""))
        source_name = clean_display_text(result.get("source_name", ""))
        url = (result.get("url") or "").strip()
        excerpt = truncate_text(result.get("excerpt", ""))
        published_date = (result.get("published_date") or "").strip()
        if not title or not source_name or not url or not published_date:
            continue
        if not is_valid_gemini_result_date(run_date, published_date):
            continue
        normalized_title = clean_text(title)
        dedupe_key = (normalized_title, url)
        if not normalized_title or dedupe_key in seen:
            continue
        haystack = f"{title} {excerpt} {source_name}".lower()
        if any(re.search(pattern, haystack) for pattern in LOW_SIGNAL_HEADLINE_PATTERNS):
            continue
        validated.append(
            {
                "title": title,
                "excerpt": excerpt,
                "url": url,
                "source_name": source_name,
                "provider": GEMINI_SOURCE["type"],
            }
        )
        seen.add(dedupe_key)
        if len(validated) >= GEMINI_FALLBACK_MAX_ACCEPTED_HEADLINES:
            break
    return validated


def should_enable_gemini_fallback(region: Region) -> bool:
    enabled = os.environ.get("NEWSCLOUD_USE_GEMINI_FALLBACK", "").strip().lower() in {"1", "true", "yes", "on"}
    return enabled and region.value in GEMINI_FALLBACK_REGIONS and bool(get_gemini_api_key())


def should_use_gemini_fallback(
    region: Region,
    *,
    filtered_token_count: int,
    supporting_headlines: list[dict],
) -> bool:
    if not should_enable_gemini_fallback(region):
        return False
    distinct_sources = {
        (headline.get("source_name") or "").strip().lower()
        for headline in supporting_headlines
        if (headline.get("source_name") or "").strip()
    }
    return (
        len(supporting_headlines) < GEMINI_FALLBACK_SUPPORTING_HEADLINE_FLOOR
        or len(distinct_sources) < GEMINI_FALLBACK_DISTINCT_SOURCE_FLOOR
        or filtered_token_count < GEMINI_FALLBACK_FILTERED_TOKEN_FLOOR
    )


def fetch_gemini_fallback_headlines(
    region: Region,
    run_date: str,
    *,
    existing_candidates: list[dict],
) -> list[dict]:
    payload = fetch_gemini_fallback_payload(region, run_date)
    return validate_gemini_headline_candidates(
        payload.get("results") or [],
        run_date=run_date,
        existing_candidates=existing_candidates,
    )


def build_corpus_outputs(
    *,
    region: Region,
    run_date: str,
    sources: list[dict],
    all_text_parts: list[str],
    headline_candidates: list[dict],
) -> dict:
    all_text = " ".join(all_text_parts)
    cleaned_text = clean_text(all_text)
    words = cleaned_text.split()
    dynamic_stop_words = build_dynamic_stop_words(region, sources)
    filtered_words = [word for word in words if word not in dynamic_stop_words and len(word) > 2]
    word_counts = Counter(filtered_words)
    top_frequencies = dict(word_counts.most_common(150))
    supporting_headlines = build_supporting_headlines(
        headline_candidates,
        top_frequencies,
        dynamic_stop_words,
        region,
        run_date,
    )
    term_metrics = (
        build_article_term_metrics(
            headline_candidates,
            top_frequencies=top_frequencies,
            stop_words=dynamic_stop_words,
        )
        if region == Region.TT
        else {}
    )
    topic_clusters = build_topic_clusters(
        headline_candidates,
        region=region.value,
        stop_words=dynamic_stop_words,
    )
    return {
        "all_text": all_text,
        "words": words,
        "filtered_words": filtered_words,
        "word_counts": word_counts,
        "top_frequencies": top_frequencies,
        "supporting_headlines": supporting_headlines,
        "term_metrics": term_metrics,
        "topic_clusters": topic_clusters,
        "dynamic_stop_words": dynamic_stop_words,
    }


def build_dynamic_stop_words(region: Region, sources: list[dict]) -> set[str]:
    dynamic_stop_words = set(STOP_WORDS)
    for token in clean_text(region.value).split():
        dynamic_stop_words.add(token)
    dynamic_stop_words.update(get_region_stop_tokens(region))
    dynamic_stop_words.update(get_extra_stop_words_for_region(region))
    for source in sources:
        for token in clean_text(source["name"]).split():
            dynamic_stop_words.add(token)
    dynamic_stop_words.update(["news", "local", "google", "times", "post", "tribune", "express", "daily"])
    return dynamic_stop_words


def normalize_source_family(source_name: str) -> str:
    cleaned = clean_display_text(source_name).lower()
    if cleaned.startswith("google news"):
        return "google news"
    if cleaned.startswith("local news"):
        return "local news"
    return cleaned


def build_article_term_metrics(
    headline_candidates: list[dict],
    *,
    top_frequencies: dict[str, int],
    stop_words: set[str],
    limit: int = TERM_METRICS_LIMIT,
) -> dict:
    """Build a TT map contract without retaining or publishing article bodies."""
    articles = []
    seen_articles: set[str] = set()
    for candidate in headline_candidates:
        title = clean_display_text(candidate.get("title", ""))
        excerpt = truncate_text(candidate.get("excerpt", ""))
        if not title:
            continue
        article_key = (candidate.get("url") or clean_text(title)).strip().lower()
        if not article_key or article_key in seen_articles:
            continue
        seen_articles.add(article_key)
        tokens = [
            token
            for token in clean_text(f"{title} {excerpt}").split()
            if len(token) > 2 and token not in stop_words
        ]
        if not tokens:
            continue
        articles.append(
            {
                "tokens": tokens,
                "token_set": set(tokens),
                "source_family": normalize_source_family(candidate.get("source_name", "")),
                "headline": {
                    "title": title,
                    "url": candidate.get("url"),
                    "source_name": clean_display_text(candidate.get("source_name", "")),
                },
            }
        )

    article_count = len(articles)
    if not article_count:
        return {
            "methodology_version": TERM_METRICS_VERSION,
            "article_count": 0,
            "distinct_source_count": 0,
            "terms": {},
        }

    ranked_terms = list(top_frequencies.items())[:limit]
    metrics = {}
    for term, raw_count in ranked_terms:
        matching_articles = [article for article in articles if term in article["token_set"]]
        if not matching_articles:
            continue
        source_families = {
            article["source_family"]
            for article in matching_articles
            if article["source_family"]
        }
        metrics[term] = {
            "raw_count": int(raw_count),
            "article_count": len(matching_articles),
            "article_share": round(len(matching_articles) / article_count, 6),
            "source_breadth": len(source_families),
            "valence": normalized_term_valence(term),
            "headlines": [article["headline"] for article in matching_articles[:3]],
        }

    distinct_sources = {
        article["source_family"] for article in articles if article["source_family"]
    }
    return {
        "methodology_version": TERM_METRICS_VERSION,
        "article_count": article_count,
        "distinct_source_count": len(distinct_sources),
        "terms": metrics,
    }


def is_aggregator_source(source_name: str, provider: str | None) -> bool:
    family = normalize_source_family(source_name)
    return family in {"google news", "newsdata.io"} or provider == "newsdata_io"


def has_region_signal_in_text(region: Region, title: str, excerpt: str) -> bool:
    haystack_tokens = set(clean_text(" ".join(part for part in (title, excerpt) if part)).split())
    region_tokens = {
        token
        for token in clean_text(get_region_display_name(region)).split()
        if len(token) > 2
    }
    return bool(haystack_tokens & region_tokens)


def has_civic_signal_in_text(title: str, excerpt: str, source_name: str = "") -> bool:
    haystack = " ".join(part for part in (title, excerpt, source_name) if part).lower()
    return any(re.search(pattern, haystack) for pattern in CIVIC_SIGNAL_PATTERNS)


def _candidate_match_terms_and_score(
    title: str, excerpt: str, stop_words: set[str], top_frequencies: dict[str, int]
) -> tuple[list[str], int]:
    title_tokens = [
        token
        for token in clean_text(title).split()
        if token not in stop_words and len(token) > 2
    ]
    excerpt_tokens = [
        token
        for token in clean_text(excerpt).split()
        if token not in stop_words and len(token) > 2
    ]
    matched_terms = sorted(
        {token for token in title_tokens + excerpt_tokens if token in top_frequencies},
        key=lambda token: (-top_frequencies[token], token),
    )
    match_score = (
        sum(top_frequencies[token] * 2 for token in title_tokens if token in top_frequencies)
        + sum(top_frequencies[token] for token in excerpt_tokens if token in top_frequencies)
    )
    return matched_terms, match_score


def _rank_supporting_candidates(
    candidates: list[dict],
    top_frequencies: dict[str, int],
    stop_words: set[str],
    region: Region,
    run_date: str,
) -> list[dict]:
    ranked = []
    seen_titles: set[str] = set()

    for index, candidate in enumerate(candidates):
        title = clean_display_text(candidate.get("title", ""))
        if not title:
            continue

        normalized_title = clean_text(title)
        if not normalized_title or normalized_title in seen_titles:
            continue
        seen_titles.add(normalized_title)

        excerpt = truncate_text(candidate.get("excerpt", ""))
        haystack = " ".join(
            part
            for part in (title, excerpt, candidate.get("source_name", ""))
            if part
        ).lower()
        if any(re.search(pattern, haystack) for pattern in LOW_SIGNAL_HEADLINE_PATTERNS):
            continue
        candidate_run_date = (candidate.get("published_date") or "").strip()
        if candidate_run_date and not is_valid_gemini_result_date(run_date, candidate_run_date):
            continue
        if not has_civic_signal_in_text(title, excerpt, candidate.get("source_name", "")):
            continue
        if candidate.get("provider") in {"newsdata_io", GEMINI_SOURCE["type"]} and not has_region_signal_in_text(
            region,
            title,
            excerpt,
        ):
            continue
        matched_terms, match_score = _candidate_match_terms_and_score(
            title, excerpt, stop_words, top_frequencies
        )
        if match_score <= 0:
            continue

        ranked.append(
            {
                "title": title,
                "excerpt": excerpt,
                "url": candidate.get("url"),
                "source_name": candidate.get("source_name"),
                "provider": candidate.get("provider"),
                "source_family": normalize_source_family(candidate.get("source_name", "")),
                "is_aggregator": is_aggregator_source(
                    candidate.get("source_name", ""),
                    candidate.get("provider"),
                ),
                "matched_terms": matched_terms[:3],
                "match_score": match_score,
                "_ordinal": index,
            }
        )

    ranked.sort(
        key=lambda item: (
            item["is_aggregator"],
            -item["match_score"],
            -len(item["matched_terms"]),
            item["_ordinal"],
        )
    )
    return ranked


def _headline_from_ranked_item(item: dict) -> dict:
    return {
        "title": item["title"],
        "excerpt": item["excerpt"],
        "url": item["url"],
        "source_name": item["source_name"],
        "provider": item["provider"],
        "matched_terms": item["matched_terms"],
    }


def _select_supporting_headlines(ranked: list[dict], limit: int) -> list[dict]:
    selected = []
    seen_families: set[str] = set()
    family_counts: dict[str, int] = {}

    for item in ranked:
        family = item["source_family"]
        if family in seen_families:
            continue
        selected.append(_headline_from_ranked_item(item))
        seen_families.add(family)
        family_counts[family] = family_counts.get(family, 0) + 1
        if len(selected) >= limit:
            return selected

    # Per-family cap in the fallback: no family fills more than ceil(limit/2) total slots,
    # so at least 2 families are represented when multiple families exist.
    distinct_family_count = len(seen_families)
    per_family_cap = (limit + 1) // 2 if distinct_family_count > 1 else limit

    for item in ranked:
        if len(selected) >= limit:
            break
        if any(
            existing["title"] == item["title"] and (existing.get("source_name") or "") == (item.get("source_name") or "")
            for existing in selected
        ):
            continue
        family = item["source_family"]
        if family_counts.get(family, 0) >= per_family_cap:
            continue
        selected.append(_headline_from_ranked_item(item))
        family_counts[family] = family_counts.get(family, 0) + 1
    return selected


def build_supporting_headlines(
    candidates: list[dict],
    top_frequencies: dict[str, int],
    stop_words: set[str],
    region: Region,
    run_date: str,
    *,
    limit: int = MAX_SUPPORTING_HEADLINES,
) -> list[dict]:
    ranked = _rank_supporting_candidates(candidates, top_frequencies, stop_words, region, run_date)
    return _select_supporting_headlines(ranked, limit)


def persist_source_contributions(records: list[dict]):
    if not records:
        return
    supabase = get_supabase()
    supabase.table(PROVENANCE_TABLE).upsert(
        records,
        on_conflict="region,date,provider,source_name",
    ).execute()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _warn_claim_unavailable(reason: str) -> None:
    """Log the first claim-accounting failure in this process, then stay quiet."""
    global _claim_unavailable_logged
    if _claim_unavailable_logged:
        return
    _claim_unavailable_logged = True
    log_event("gather_claim_unavailable", reason=reason)


def _record_legacy_attempt(run_date: str, region: str) -> None:
    """Keep the attempt counter moving when the claim RPC cannot be used.

    The claim owns the increment while it exists. Without it nothing else writes
    ``gatherer_attempts`` -- the finalizer's retry claim only resets it at the
    budget and counts recoveries -- and that column *is* the retry budget. So a
    missing migration (or an unreadable response) must fall back to the write the
    claim replaced, or a permanently failing region would be retried forever
    instead of being exhausted.
    """
    try:
        update_stage_state(run_date, region, STAGE_NAME, "running", increment_attempt=True)
    except Exception as exc:  # the database is unreachable; nothing else will work either
        _warn_claim_unavailable(f"legacy_attempt_write:{type(exc).__name__}: {exc}")


def claim_gather_stage(run_date: str, region: str) -> str:
    """Claim the gather stage for this delivery; see the migration.

    Returns the RPC's reason (``claimed``, ``in_progress``, ``already_completed``).
    A duplicate delivery must return without gathering, because the work spends a
    NewsData credit. A missing RPC -- the migration is applied before the
    function deploys, but the reverse order must not stop the pipeline -- logs
    one ``gather_claim_unavailable`` line per process, records the attempt the
    old way, and allows the work.
    """
    try:
        response = (
            get_supabase()
            .rpc(
                CLAIM_RPC,
                {
                    "p_run_date": run_date,
                    "p_region": region,
                    "p_stale_minutes": GATHER_CLAIM_STALE_MINUTES,
                },
            )
            .execute()
        )
    except Exception as exc:
        _warn_claim_unavailable(f"{type(exc).__name__}: {exc}")
        _record_legacy_attempt(run_date, region)
        return "claimed"

    data = getattr(response, "data", None)
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if isinstance(data, str) and data:
        return data
    _warn_claim_unavailable(f"unexpected_response:{data!r}")
    _record_legacy_attempt(run_date, region)
    return "claimed"


def _fetch_stage_attempts(supabase: Client, run_date: str, region: str, stage: str) -> int:
    response = (
        supabase.table("region_runs")
        .select(f"{stage}_attempts")
        .eq("run_date", run_date)
        .eq("region", region)
        .limit(1)
        .execute()
    )
    if response.data:
        return int(response.data[0].get(f"{stage}_attempts") or 0)
    return 0


def update_stage_state(
    run_date: str,
    region: str,
    stage: str,
    status: str,
    *,
    error_message: str | None = None,
    increment_attempt: bool = False,
):
    supabase = get_supabase()
    now_iso = _utc_now_iso()
    payload: dict[str, object] = {
        "run_date": run_date,
        "region": region,
        f"{stage}_status": status,
        "last_event_at": now_iso,
    }
    if increment_attempt:
        payload[f"{stage}_attempts"] = _fetch_stage_attempts(supabase, run_date, region, stage) + 1
        payload[f"{stage}_started_at"] = now_iso
    if status == "completed":
        payload[f"{stage}_completed_at"] = now_iso
        payload[f"{stage}_last_error"] = None
        payload["next_retry_at"] = None
    elif status == "failed":
        payload[f"{stage}_last_error"] = error_message
    elif status == "running":
        payload[f"{stage}_last_error"] = None
    supabase.table("region_runs").upsert(payload, on_conflict="run_date,region").execute()


def persist_region_frequencies(
    region: str,
    run_date: str,
    frequencies: dict,
    supporting_headlines: list[dict] | None = None,
    term_metrics: dict | None = None,
    topic_clusters: dict | None = None,
):
    supabase = get_supabase()
    supabase.table(WORD_FREQUENCIES_TABLE).upsert(
        {
            "region": region,
            "date": run_date,
            "frequencies": frequencies,
            "supporting_headlines": supporting_headlines or [],
            "term_metrics": term_metrics or {},
            "topic_clusters": topic_clusters or {},
        },
        on_conflict="region,date",
    ).execute()


def build_source_record(
    region: Region,
    run_date: str,
    source: dict,
    *,
    result_count: int = 0,
    text: str = "",
    token_count: int | None = None,
    status: str,
    error_message: str | None = None,
) -> dict:
    cleaned_tokens = clean_text(text).split()
    return {
        "region": region.value,
        "date": run_date,
        "provider": source["type"],
        "source_name": source["name"],
        "source_query": source.get("query"),
        "source_url": source.get("url"),
        "result_count": result_count,
        "text_char_count": len(text),
        "token_count": len(cleaned_tokens) if token_count is None else token_count,
        "status": status,
        "error_message": error_message,
    }


def publish_frequencies(region: Region, run_date: str, top_frequencies: dict):
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
    payload = {
        "region": region.value,
        "date": run_date,
        "frequencies": top_frequencies,
    }
    future = publisher.publish(topic_path, data=json.dumps(payload).encode("utf-8"))
    print(f"Published message ID {future.result()} to {topic_path} for region {region.value}")


def publish_monitor_event(region: str, run_date: str, status: str):
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT_ID, FINALIZER_TOPIC_ID)
    payload = json.dumps(
        {"region": region, "date": run_date, "stage": STAGE_NAME, "status": status}
    ).encode("utf-8")
    future = publisher.publish(topic_path, data=payload)
    print(f"Published monitor event {future.result()} for {region} {run_date} ({status}).")


def region_and_date_from_payload(payload: dict) -> tuple[Region, str] | None:
    """Validate a ``{"region": ..., "date": ...}`` payload.

    Shared by the Pub/Sub entry point and the Cloud Tasks HTTP entry point, so
    both reject the same inputs the same way.
    """
    region_str = payload.get("region")
    run_date = normalize_run_date(payload.get("date"))
    if not region_str:
        print("Error: Please provide a 'region' parameter (e.g. 'US-CA')")
        return None
    try:
        region = Region(region_str)
    except ValueError:
        valid_regions = [r.value for r in Region]
        print(f"Error: Invalid region '{region_str}'. Valid regions: {valid_regions}")
        return None
    return region, run_date


def _parse_gather_news_event(cloud_event) -> tuple[Region, str] | None:
    if "message" in cloud_event.data and "data" in cloud_event.data["message"]:
        payload = base64.b64decode(cloud_event.data["message"]["data"]).decode("utf-8")
        try:
            event_json = json.loads(payload)
        except json.JSONDecodeError:
            print("Error: Invalid JSON payload in Pub/Sub message")
            return None
    else:
        print("Error: Message data missing from Cloud Event")
        return None

    return region_and_date_from_payload(event_json)


def _fetch_one_source(region: Region, run_date: str, source: dict) -> dict:
    provider = source["type"]
    quota_reason: str | None = None
    log_event(
        "source_fetch_start",
        region=region.value,
        provider=provider,
        source_name=source["name"],
        query=source.get("query"),
        url=source.get("url"),
        run_date=run_date,
    )
    try:
        if provider == "rss":
            rss_content = extract_rss_source_content(source, run_date=run_date)
            source_text = rss_content["text"]
            result_count = rss_content["result_count"]
            headlines = rss_content["headlines"]
            staleness_warning = build_rss_staleness_warning(
                region,
                source,
                rss_content["raw_headlines"],
                run_date=run_date,
            )
            if staleness_warning:
                log_event("rss_source_stale", **staleness_warning)
            log_event(
                "rss_recency_filter_summary",
                region=region.value,
                provider=provider,
                source_name=source["name"],
                run_date=run_date,
                **rss_content["recency"],
            )
        elif provider == "newsdata_io":
            source_text, result_count, headlines, quota_reason = fetch_newsdata_source_text(
                source, run_date
            )
        else:
            raise ValueError(f"Unsupported source type: {provider}")

        # A quota denial is not an empty source: it is a decision the retry path
        # depends on, so name it in the record (see shared/newsdata_quota.py).
        status = SOURCE_STATUS_QUOTA_DEFERRED if quota_reason == "window" else None
        if quota_reason == "daily":
            status = SOURCE_STATUS_QUOTA_EXHAUSTED
        if status is None:
            status = "success" if clean_text(source_text) else "empty"
        record = build_source_record(
            region,
            run_date,
            source,
            result_count=result_count,
            text=source_text,
            status=status,
        )
        log_event("source_fetch_summary", **record)
        return {
            "record": record,
            "source_text": source_text,
            "headlines": headlines,
            "quota_reason": quota_reason,
        }
    except Exception as exc:
        record = build_source_record(
            region,
            run_date,
            source,
            status="error",
            error_message=external_error_summary(exc),
        )
        log_event("source_fetch_error", **record)
        return {"record": record, "source_text": None, "headlines": None, "quota_reason": None}


def _fetch_all_sources(
    region: Region, run_date: str, sources: list[dict]
) -> tuple[list[dict], list[dict], list[str], list[str]]:
    """Fetch every source for a region.

    The fourth element is the quota denial reasons seen during the sweep
    (``window``/``daily``); the caller turns them into the region's stage status.
    """
    source_records = []
    headline_candidates = []
    all_text_parts = []
    quota_denials = []

    for source in sources:
        fetched = _fetch_one_source(region, run_date, source)
        source_records.append(fetched["record"])
        if fetched["source_text"]:
            all_text_parts.append(fetched["source_text"])
        if fetched["headlines"]:
            headline_candidates.extend(fetched["headlines"])
        if fetched["quota_reason"]:
            quota_denials.append(fetched["quota_reason"])

    return source_records, headline_candidates, all_text_parts, quota_denials


def _current_gather_attempt(run_date: str, region: Region) -> int:
    """Return the attempt number ``gather_news`` already incremented.

    The stage write that starts a run increments ``gatherer_attempts`` first, so
    reading it here yields 1 on the scheduled pass and 2 on the first retry. If
    the count cannot be read, treat the run as the first attempt: deferring is
    the safer default, and the next retry cannot defer again.
    """
    try:
        return _fetch_stage_attempts(get_supabase(), run_date, region.value, STAGE_NAME)
    except Exception:
        return 1


def _finish_gather_stage(
    region: Region, run_date: str, quota_denials: list[str], *, attempt: int
) -> None:
    """Record the region's terminal gather status.

    A window denial on the *first* attempt leaves the region retryable
    (``deferred``) so the finalizer's bounded retry can pick the call up once the
    window has room -- which is the common case late in the sweep, when the state
    gatherer has stopped competing for credits.

    The deferral is deliberately bounded to one retry. Both gatherers pace at 65
    seconds, so while their sweeps overlap they already consume ~27.7 of the 28
    credits per window: a second denial is far more likely than a grant, and a
    region that kept deferring would block publication entirely, because a run
    only reaches ``completed`` when every region is complete. So a denied retry
    accepts the corpus it has and records the shortfall instead of holding the
    board hostage.

    A daily denial cannot move until the next run date and is never retried.

    See the denial policy in ``shared/newsdata_quota.py``.
    """
    window_denied = "window" in quota_denials
    if window_denied and attempt <= 1:
        log_event(
            "newsdata_quota_deferred",
            region=region.value,
            run_date=run_date,
            attempt=attempt,
            denied_source_count=len(quota_denials),
        )
        update_stage_state(
            run_date,
            region.value,
            STAGE_NAME,
            "deferred",
            error_message="newsdata_quota_window_denied",
        )
        publish_monitor_event(region.value, run_date, "deferred")
        return

    if window_denied:
        log_event(
            "newsdata_quota_window_exhausted",
            region=region.value,
            run_date=run_date,
            attempt=attempt,
            denied_source_count=len(quota_denials),
        )
    elif "daily" in quota_denials:
        log_event(
            "newsdata_quota_exhausted",
            region=region.value,
            run_date=run_date,
            attempt=attempt,
            denied_source_count=len(quota_denials),
        )
    update_stage_state(run_date, region.value, STAGE_NAME, "completed")
    publish_monitor_event(region.value, run_date, "completed")


def _apply_gemini_fallback(
    region: Region,
    run_date: str,
    sources: list[dict],
    source_records: list[dict],
    headline_candidates: list[dict],
    all_text_parts: list[str],
    corpus: dict,
) -> dict:
    try:
        with tracer.start_as_current_span(
            "gemini.fallback",
            attributes={
                "region": region.value,
                "run_date": run_date,
                "model": GEMINI_GATHERER_MODEL,
                "mode": GEMINI_FALLBACK_MODE,
            },
        ) as gemini_span:
            gemini_headlines = fetch_gemini_fallback_headlines(
                region,
                run_date,
                existing_candidates=headline_candidates,
            )
            gemini_span.set_attribute("accepted_headline_count", len(gemini_headlines))
        gemini_text = " ".join(
            extract_headline_candidate_text(candidate)
            for candidate in gemini_headlines
        )
        source_records.append(
            build_source_record(
                region,
                run_date,
                GEMINI_SOURCE,
                result_count=len(gemini_headlines),
                text=gemini_text,
                status="success" if gemini_headlines else "empty",
            )
        )
        if gemini_headlines:
            headline_candidates.extend(gemini_headlines)
            all_text_parts.extend(
                extract_headline_candidate_text(candidate)
                for candidate in gemini_headlines
            )
            corpus = build_corpus_outputs(
                region=region,
                run_date=run_date,
                sources=sources,
                all_text_parts=all_text_parts,
                headline_candidates=headline_candidates,
            )
        log_event(
            "gemini_fallback_summary",
            region=region.value,
            run_date=run_date,
            accepted_headline_count=len(gemini_headlines),
        )
    except (json.JSONDecodeError, urllib.error.URLError, TimeoutError, ValueError) as exc:
        record = build_source_record(
            region,
            run_date,
            GEMINI_SOURCE,
            status="error",
            error_message=str(exc),
        )
        source_records.append(record)
        log_event("gemini_fallback_error", **record)
    return corpus


@functions_framework.http
def gather_region_http(request):
    """Cloud Tasks entry point: one region per task, paced by the queue.

    Cloud Tasks invokes this with an OIDC token, so the platform rejects
    unauthenticated calls before the container starts. The queue's dispatch rate
    is what paces NewsData on this path, which is why it does not sleep; a task
    retry is a duplicate delivery, and the claim below makes that cheap.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return json.dumps({"error": "expected a JSON object body"}), 400
    parsed = region_and_date_from_payload(payload)
    if parsed is None:
        return json.dumps({"error": "invalid region or date"}), 400
    region, run_date = parsed
    run_region_gather(region, run_date)
    return json.dumps({"region": region.value, "run_date": run_date}), 200


@functions_framework.cloud_event
def gather_news(cloud_event):
    """Cloud Event Function triggered by Pub/Sub to fetch news and calculate frequencies."""
    parsed_event = _parse_gather_news_event(cloud_event)
    if parsed_event is None:
        return
    region, run_date = parsed_event
    run_region_gather(region, run_date)


def run_region_gather(region: Region, run_date: str) -> None:
    """Fetch, build and persist one region's corpus.

    Shared by the Pub/Sub and Cloud Tasks entry points. The claim guards both:
    Pub/Sub delivers at least once, the finalizer republishes recovery attempts,
    and a Cloud Tasks retry is another delivery.
    """
    # Claim before doing anything: Pub/Sub delivers at least once and the
    # finalizer republishes recovery attempts, so this delivery may be a
    # duplicate. Losing the claim is cheap; gathering again is not.
    claim = claim_gather_stage(run_date, region.value)
    if claim != "claimed":
        log_event(
            "gather_claim_skipped",
            region=region.value,
            run_date=run_date,
            reason=claim,
        )
        return

    gather_span = tracer.start_span(
        "gather_news", attributes={"region": region.value, "run_date": run_date}
    )
    gather_span_token = otel_context.attach(otel_trace.set_span_in_context(gather_span))

    try:
        sources = get_sources_for_region(region)
        if not sources:
            raise ValueError(f"No sources found for region {region.value}")

        source_records, headline_candidates, all_text_parts, quota_denials = (
            _fetch_all_sources(region, run_date, sources)
        )

        corpus = build_corpus_outputs(
            region=region,
            run_date=run_date,
            sources=sources,
            all_text_parts=all_text_parts,
            headline_candidates=headline_candidates,
        )
        all_text = corpus["all_text"]
        words = corpus["words"]
        filtered_words = corpus["filtered_words"]
        word_counts = corpus["word_counts"]
        top_frequencies = corpus["top_frequencies"]
        supporting_headlines = corpus["supporting_headlines"]
        term_metrics = corpus["term_metrics"]
        topic_clusters = corpus["topic_clusters"]

        if should_use_gemini_fallback(
            region,
            filtered_token_count=len(filtered_words),
            supporting_headlines=supporting_headlines,
        ):
            log_event(
                "gemini_fallback_triggered",
                region=region.value,
                run_date=run_date,
                filtered_token_count=len(filtered_words),
                supporting_headline_count=len(supporting_headlines),
                distinct_source_count=len(
                    {
                        (headline.get("source_name") or "").strip().lower()
                        for headline in supporting_headlines
                        if (headline.get("source_name") or "").strip()
                    }
                ),
            )
            corpus = _apply_gemini_fallback(
                region,
                run_date,
                sources,
                source_records,
                headline_candidates,
                all_text_parts,
                corpus,
            )
            all_text = corpus["all_text"]
            words = corpus["words"]
            filtered_words = corpus["filtered_words"]
            word_counts = corpus["word_counts"]
            top_frequencies = corpus["top_frequencies"]
            supporting_headlines = corpus["supporting_headlines"]
            term_metrics = corpus["term_metrics"]
            topic_clusters = corpus["topic_clusters"]

        persist_source_contributions(source_records)

        log_event(
            "corpus_summary",
            region=region.value,
            run_date=run_date,
            source_count=len(sources),
            source_record_count=len(source_records),
            headline_candidate_count=len(headline_candidates),
            supporting_headline_count=len(supporting_headlines),
            raw_text_chars=len(all_text),
            raw_token_count=len(words),
            filtered_token_count=len(filtered_words),
            unique_terms=len(word_counts),
            stop_term_version=get_region_stop_term_version(region),
            term_metric_count=len((term_metrics.get("terms") or {})),
            article_count=topic_clusters.get("article_count") or term_metrics.get("article_count"),
            topic_model_status=topic_clusters.get("status"),
            topic_cluster_count=len(topic_clusters.get("topics") or []),
        )

        if not top_frequencies:
            log_event("empty_corpus", region=region.value, run_date=run_date)
            raise ValueError(f"No usable terms found for region {region.value} on {run_date}")

        persist_region_frequencies(
            region.value,
            run_date,
            top_frequencies,
            supporting_headlines=supporting_headlines,
            term_metrics=term_metrics,
            topic_clusters=topic_clusters,
        )
        publish_frequencies(region, run_date, top_frequencies)
        _finish_gather_stage(
            region,
            run_date,
            quota_denials,
            attempt=_current_gather_attempt(run_date, region),
        )
    except Exception as exc:
        update_stage_state(run_date, region.value, STAGE_NAME, "failed", error_message=str(exc))
        publish_monitor_event(region.value, run_date, "failed")
        print(f"Failed to gather news for {region.value} on {run_date}: {exc}")
        gather_span.record_exception(exc)
    finally:
        otel_context.detach(gather_span_token)
        gather_span.end()

# gen2 python313 - final
# deployment marker: workflow rebuild requested
