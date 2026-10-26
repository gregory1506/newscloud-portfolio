"""Congressional member press release RSS parsing and issue-term extraction.

Uses only stdlib — xml.etree.ElementTree for RSS, no feedparser dependency.
Mirrors the term-counting approach in gatherer/main.py, applied to each party's
delegation separately so the output is party-attributable.
"""

from __future__ import annotations

import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

_TIMEOUT = 15

_ISSUE_BUCKETS: dict[str, list[str]] = {
    "economy": ["economy", "jobs", "inflation", "unemployment", "trade", "tariff", "gdp", "wages"],
    "immigration": ["immigration", "border", "asylum", "migrant", "deportation", "visa"],
    "healthcare": ["healthcare", "medicare", "medicaid", "prescription", "insurance", "drug prices"],
    "education": ["education", "student", "school", "university", "college", "loan"],
    "crime": ["crime", "fentanyl", "public safety", "law enforcement", "criminal", "police"],
    "abortion": ["abortion", "reproductive", "roe", "pro-life", "pro-choice", "contraception"],
    "elections": ["election", "voting", "democracy", "ballot", "voter", "redistricting"],
}


def fetch_press_release_headlines(rss_url: str, max_items: int = 25) -> list[str]:
    """Fetch and return headline+description text from a member's RSS feed.

    Returns an empty list when the feed is unavailable or malformed.
    """
    try:
        req = urllib.request.Request(rss_url, headers={"User-Agent": "NewsCloud/1.0"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            root = ET.parse(resp).getroot()
        texts = []
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title") or ""
            desc = item.findtext("description") or ""
            texts.append(f"{title} {desc}")
        return texts
    except (urllib.error.URLError, ET.ParseError, Exception) as exc:
        print(f"RSS fetch {rss_url}: {exc}")
        return []


def extract_top_issue_terms(texts: list[str], top_n: int = 3) -> list[str]:
    """Return the top-N issue bucket names by keyword mention count across texts.

    Returns an empty list when texts is empty.
    """
    if not texts:
        return []
    combined = " ".join(texts).lower()
    counts: Counter[str] = Counter()
    for bucket, keywords in _ISSUE_BUCKETS.items():
        for kw in keywords:
            count = combined.count(kw)
            if count:
                counts[bucket] += count
    return [bucket for bucket, _ in counts.most_common(top_n)]
