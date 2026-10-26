"""Deterministic story-level topic clustering for TT and UK coverage.

The model intentionally uses only sanitized headline/excerpt metadata already
held by the gatherer. It does not persist article bodies, call an external
model, or add a heavyweight runtime dependency.
"""

from __future__ import annotations

from collections import Counter
import math
import re
from urllib.parse import urlparse


TOPIC_MODEL_VERSION = "regional-topic-v1"
SUPPORTED_REGIONS = {"TT", "UK"}
MAX_TOPICS = 6
MAX_EVIDENCE = 3

CLUSTER_STOP_TERMS = {
    "arrested",
    "britain",
    "british",
    "government",
    "govt",
    "minister",
    "official",
    "officials",
    "report",
    "reports",
    "trinidad",
    "urges",
}

REJECT_TITLE_PATTERNS = (
    re.compile(r"\bmarket to reach\b.*\bbillion\b", re.IGNORECASE),
    re.compile(r"\bcagr\b", re.IGNORECASE),
)

DISPLAY_TERMS = {
    "cpl": "CPL",
    "pca": "PCA",
    "pnm": "PNM",
    "ttps": "TTPS",
    "uk": "UK",
    "us": "US",
}


def _clean_display(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _tokens(value: object, stop_words: set[str]) -> list[str]:
    normalized = re.sub(r"[^a-z0-9']+", " ", str(value or "").lower())
    return [
        token
        for token in normalized.split()
        if len(token) > 2 and token not in stop_words and not token.isdigit()
    ]


def _entity_tokens(value: object, allowed_tokens: set[str]) -> set[str]:
    """Return headline terms carrying proper-name casing in the source text."""
    entities = set()
    for match in re.finditer(r"[A-Za-z][A-Za-z0-9']+", str(value or "")):
        token = match.group(0)
        normalized = token.lower()
        if normalized in allowed_tokens and (token[0].isupper() or token.isupper()):
            entities.add(normalized)
    return entities


def _safe_url(value: object) -> str | None:
    url = _clean_display(value)
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _source_family(value: object) -> str:
    source = _clean_display(value).lower()
    if source.startswith("google news"):
        return "google news"
    if source.startswith("local news"):
        return "local news"
    return source


def _article_records(candidates: list[dict], stop_words: set[str]) -> list[dict]:
    records = []
    seen: set[str] = set()
    for candidate in candidates:
        title = _clean_display(candidate.get("title"))
        if not title:
            continue
        if any(pattern.search(title) for pattern in REJECT_TITLE_PATTERNS):
            continue
        url = _safe_url(candidate.get("url"))
        key = (url or re.sub(r"\W+", " ", title.lower()).strip()).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        model_stop_words = stop_words | CLUSTER_STOP_TERMS
        title_tokens = _tokens(title, model_stop_words)
        excerpt_tokens = _tokens(candidate.get("excerpt"), model_stop_words)
        token_set = set(title_tokens) | set(excerpt_tokens)
        if not title_tokens or not token_set:
            continue
        records.append(
            {
                "key": key,
                "title": title,
                "url": url,
                "source_name": _clean_display(candidate.get("source_name")),
                "source_family": _source_family(candidate.get("source_name")),
                "title_tokens": set(title_tokens),
                "entity_tokens": _entity_tokens(title, set(title_tokens)),
                "token_set": token_set,
            }
        )
    return sorted(records, key=lambda item: (item["key"], item["title"].lower()))


def _connection_strength(
    left: dict, right: dict, title_document_frequency: Counter
) -> float | None:
    shared_title = left["title_tokens"] & right["title_tokens"]
    title_union = left["title_tokens"] | right["title_tokens"]
    title_jaccard = len(shared_title) / len(title_union) if title_union else 0.0
    if len(shared_title) >= 2 and title_jaccard >= 0.14:
        shared_evidence = left["token_set"] & right["token_set"]
        return len(shared_title) * 10 + title_jaccard + min(len(shared_evidence), 5) * 0.01
    if len(shared_title) != 1:
        return None
    # One shared headline term may join stories only when it behaves like a
    # rare named entity in this corpus. This preserves Burnham/Kangaloo-style
    # story continuity without letting a lone generic word chain unrelated
    # articles. Require a second corroborating term anywhere in the available
    # headline/excerpt metadata.
    term = next(iter(shared_title))
    shared_evidence = left["token_set"] & right["token_set"]
    connected = (
        len(term) >= 6
        and title_document_frequency[term] <= 3
        and term in left["entity_tokens"]
        and term in right["entity_tokens"]
        and len(shared_evidence) >= 2
    )
    if not connected:
        return None
    return 1 + min(len(shared_evidence), 5) * 0.01


def _should_connect(left: dict, right: dict, title_document_frequency: Counter) -> bool:
    return _connection_strength(left, right, title_document_frequency) is not None


def _components(articles: list[dict]) -> list[list[dict]]:
    title_document_frequency: Counter = Counter()
    for article in articles:
        title_document_frequency.update(article["title_tokens"])

    # Complete-link agglomeration prevents transitive bridge chains. A merged
    # topic is allowed only when every article in one group connects directly
    # to every article in the other group. Prefer the strongest weakest edge,
    # then the larger merge, with article keys as the deterministic tie-break.
    groups = [[article] for article in articles]
    while True:
        candidates = []
        for left_index in range(len(groups)):
            for right_index in range(left_index + 1, len(groups)):
                strengths = [
                    _connection_strength(left, right, title_document_frequency)
                    for left in groups[left_index]
                    for right in groups[right_index]
                ]
                if not strengths or any(strength is None for strength in strengths):
                    continue
                merged_keys = tuple(
                    sorted(
                        article["key"]
                        for article in groups[left_index] + groups[right_index]
                    )
                )
                candidates.append(
                    (
                        min(strengths),
                        len(groups[left_index]) + len(groups[right_index]),
                        merged_keys,
                        left_index,
                        right_index,
                    )
                )
        if not candidates:
            break
        _, _, _, left_index, right_index = max(
            candidates,
            key=lambda item: (item[0], item[1], tuple(reversed(item[2]))),
        )
        groups[left_index] = sorted(
            groups[left_index] + groups[right_index],
            key=lambda article: (article["key"], article["title"].lower()),
        )
        del groups[right_index]
    return groups


def _signature_terms(group: list[dict], document_frequency: Counter, article_count: int) -> list[str]:
    cluster_frequency: Counter = Counter()
    title_frequency: Counter = Counter()
    for article in group:
        cluster_frequency.update(article["token_set"])
        title_frequency.update(article["title_tokens"])

    scored = []
    for term, cluster_docs in cluster_frequency.items():
        idf = math.log((article_count + 1) / (document_frequency[term] + 1)) + 1
        title_boost = 1 + min(title_frequency[term], 3) * 0.35
        cohesion = cluster_docs / len(group)
        scored.append((cohesion * idf * title_boost, title_frequency[term], term))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [term for _, _, term in scored[:4]]


def _display_label(terms: list[str]) -> str:
    displayed = [DISPLAY_TERMS.get(term, term.title()) for term in terms[:3]]
    return " · ".join(displayed) if displayed else "Developing story"


def build_topic_clusters(
    candidates: list[dict],
    *,
    region: str,
    stop_words: set[str],
    limit: int = MAX_TOPICS,
) -> dict:
    """Return a stable topic contract from sanitized article metadata."""
    if region not in SUPPORTED_REGIONS:
        return {}

    articles = _article_records(candidates, stop_words)
    article_count = len(articles)
    distinct_sources = {article["source_family"] for article in articles if article["source_family"]}
    if not articles:
        return {
            "methodology_version": TOPIC_MODEL_VERSION,
            "status": "insufficient",
            "article_count": 0,
            "distinct_source_count": 0,
            "represented_article_count": 0,
            "other_article_count": 0,
            "topics": [],
        }

    document_frequency: Counter = Counter()
    for article in articles:
        document_frequency.update(article["token_set"])

    topic_rows = []
    for group in _components(articles):
        # One article is a story, not a cluster. Keep it in the corpus and the
        # outside-cluster count, but never promote it to a topic card.
        if len(group) < 2:
            continue
        terms = _signature_terms(group, document_frequency, article_count)
        sources = {article["source_family"] for article in group if article["source_family"]}
        label = _display_label(terms)
        evidence = [
            {
                "title": article["title"],
                "url": article["url"],
                "source_name": article["source_name"],
            }
            for article in sorted(
                group,
                key=lambda item: (
                    item["source_family"],
                    item["title"].lower(),
                    item["key"],
                ),
            )[:MAX_EVIDENCE]
        ]
        confidence = "strong" if len(sources) >= 2 else "developing"
        topic_rows.append(
            {
                "id": "-".join(terms[:3]) or f"story-{len(topic_rows) + 1}",
                "label": label,
                "article_count": len(group),
                "coverage_share": round(len(group) / article_count, 6),
                "source_breadth": len(sources),
                "confidence": confidence,
                "keywords": terms,
                "summary": (
                    f"{len(group)} article{'s' if len(group) != 1 else ''} across "
                    f"{len(sources)} source {'families' if len(sources) != 1 else 'family'} "
                    f"connect around {label.lower()}."
                ),
                "evidence": evidence,
            }
        )

    topic_rows.sort(
        key=lambda item: (
            -item["article_count"],
            -item["source_breadth"],
            item["label"].lower(),
        )
    )
    selected = topic_rows[: max(1, min(limit, MAX_TOPICS))]
    represented = sum(topic["article_count"] for topic in selected)
    multi_article_topics = sum(topic["article_count"] >= 2 for topic in selected)
    status = (
        "ready"
        if article_count >= 12 and len(distinct_sources) >= 3 and multi_article_topics >= 3
        else "provisional" if selected else "insufficient"
    )
    return {
        "methodology_version": TOPIC_MODEL_VERSION,
        "status": status,
        "article_count": article_count,
        "distinct_source_count": len(distinct_sources),
        "represented_article_count": represented,
        "other_article_count": max(0, article_count - represented),
        "topics": selected,
    }
