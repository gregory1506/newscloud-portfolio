"""District-level source construction for the Race Board.

Phase 1 (``GR3-516``). There is no curated RSS feed per congressional district,
so district coverage is query-based: NewsData.io queries built from the district
label, the state name, and the FEC candidate roster. Callers gather the returned
source dicts with the existing gatherer fetch path and persist under the
district region code (``US-TX-07``).

Kept pure and dependency-light so it can be unit-tested without the gatherer.
"""

from __future__ import annotations

from shared.districts import district_label

DEFAULT_MAX_QUERIES = 1
PROVIDER = "newsdata_io"


def _ordinal(value: int) -> str:
    if 10 <= value % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
    return f"{value}{suffix}"


def build_district_queries(
    *,
    postal: str,
    district: int,
    state_name: str,
    candidate_names: tuple[str, ...] | list[str] = (),
    max_queries: int = DEFAULT_MAX_QUERIES,
) -> list[dict]:
    """Return NewsData.io source specs for one district.

    Queries use natural-language forms ("Texas 7th congressional district") that
    match real coverage; label/quoted forms return nothing on NewsData.io. Each
    spec has a unique ``name`` so provenance rows do not collide.
    """
    label = district_label(postal, district)
    raw_queries = [
        f"{state_name} {_ordinal(district)} congressional district",
        f"{state_name} congress election",
    ]
    for name in candidate_names:
        cleaned = (name or "").strip()
        if cleaned:
            raw_queries.append(f'"{cleaned}" congress')

    queries: list[str] = []
    for query in raw_queries:
        if query not in queries:
            queries.append(query)
        if len(queries) >= max_queries:
            break

    return [
        {
            "name": f"NewsData.io {label} #{index + 1}",
            "type": PROVIDER,
            "query": query,
            "country": "US",
            "language": "en",
        }
        for index, query in enumerate(queries)
    ]


def get_district_sources(
    *,
    postal: str,
    district: int,
    state_name: str,
    candidate_names: tuple[str, ...] | list[str] = (),
    curated_rss: list[dict] | None = None,
    max_queries: int = DEFAULT_MAX_QUERIES,
) -> list[dict]:
    """Return the full source list for a district: curated RSS plus queries."""
    sources = list(curated_rss or [])
    sources.extend(
        build_district_queries(
            postal=postal,
            district=district,
            state_name=state_name,
            candidate_names=candidate_names,
            max_queries=max_queries,
        )
    )
    return sources
