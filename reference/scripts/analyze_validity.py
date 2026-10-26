#!/usr/bin/env python3
"""Analyze whether regional_sentiment.leaning_score predicts 2026 election
outcomes, using the ground-truth cache built by scripts/fetch_ground_truth.py.

Usage:
  python3 scripts/analyze_validity.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

# Support the existing `python scripts/analyze_validity.py` entry point.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.supabase_rest import SupabaseRest


REPO_ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH_CACHE = REPO_ROOT / "docs" / "data" / "ground_truth" / "2026-validity-backtest.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "2026-07-predictive-validity-backtest.md"
CHART_PATH = REPO_ROOT / "docs" / "reports" / "2026-07-predictive-validity-backtest.png"

SUPABASE_URL_ENV = "SUPABASE_URL"
SUPABASE_KEY_ENV = "SUPABASE_SECRET_KEY"
PAGE_SIZE = 1000

# Mirrors the scorer's _LEANING_MULT (16.0) and the 55/45 decisive band
# edges, translated into 0-5 leaning_score space: (55 - 50) / 16.0 = 0.3125.
_LEANING_MULT = 16.0
_NEUTRAL_LEANING = 2.5
_DECISIVE_BAND_OFFSET = 5.0 / _LEANING_MULT

MIN_COVERAGE_STATES = 8
DEFAULT_REVERSION_WINDOW_DAYS = 5


def favored_party(leaning_score: float, band_offset: float = _DECISIVE_BAND_OFFSET) -> str | None:
    if leaning_score <= _NEUTRAL_LEANING - band_offset:
        return "democrat"
    if leaning_score >= _NEUTRAL_LEANING + band_offset:
        return "republican"
    return None


def _opposite_party(party: str) -> str:
    return "republican" if party == "democrat" else "democrat"


def find_signal_move_date(
    series: list[tuple[str, float]],
    target_party: str,
    reversion_window_days: int = DEFAULT_REVERSION_WINDOW_DAYS,
    band_offset: float = _DECISIVE_BAND_OFFSET,
) -> str | None:
    opposite = _opposite_party(target_party)
    for i, (candidate_date, score) in enumerate(series):
        if favored_party(score, band_offset) != target_party:
            continue
        window = series[i : i + reversion_window_days + 1]
        if all(favored_party(s, band_offset) != opposite for _, s in window):
            return candidate_date
    return None


def smooth_series(series: list[tuple[str, float]], window_days: int) -> list[tuple[str, float]]:
    if window_days <= 1:
        return series
    smoothed: list[tuple[str, float]] = []
    for i in range(len(series)):
        start = max(0, i - window_days + 1)
        window_scores = [score for _, score in series[start : i + 1]]
        smoothed.append((series[i][0], sum(window_scores) / len(window_scores)))
    return smoothed


def compute_lead_days(event_date: str, signal_move_date: str | None) -> int | None:
    if signal_move_date is None:
        return None
    return (date.fromisoformat(event_date) - date.fromisoformat(signal_move_date)).days


def classify_event_case(lead_days: int | None) -> str:
    if lead_days is None:
        return "miss"
    if lead_days > 0:
        return "true_positive_lead"
    if lead_days == 0:
        return "true_positive_same_day"
    return "true_positive_lag"


def check_quiet_state_false_positive(
    series: list[tuple[str, float]],
    polling_stable: bool,
    band_offset: float = _DECISIVE_BAND_OFFSET,
) -> bool:
    if not polling_stable:
        return False
    return any(favored_party(score, band_offset) is not None for _, score in series)


def get_supabase_config() -> tuple[str, str]:
    url = os.environ.get(SUPABASE_URL_ENV)
    key = os.environ.get(SUPABASE_KEY_ENV)
    if not url or not key:
        raise SystemExit(f"{SUPABASE_URL_ENV} and {SUPABASE_KEY_ENV} must be set.")
    return url.rstrip("/"), key


def fetch_rest_rows(
    base_url: str,
    service_key: str,
    table: str,
    select: str,
    *,
    order: str,
    filters: dict[str, str] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    client = SupabaseRest(base_url, service_key)
    while True:
        params = {"select": select, "order": order, "limit": str(PAGE_SIZE), "offset": str(offset)}
        if filters:
            params.update(filters)
        query = urllib.parse.urlencode(params)
        page = client.get(f"{table}?{query}")
        if not page:
            break
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def load_leaning_series_by_state(rows: list[dict]) -> dict[str, list[tuple[str, float]]]:
    grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for row in rows:
        grouped[row["region"]].append((row["date"], float(row["leaning_score"])))
    for state in grouped:
        grouped[state].sort(key=lambda pair: pair[0])
    return dict(grouped)


def build_case_results(cache: dict, series_by_state: dict, band_offset: float = _DECISIVE_BAND_OFFSET) -> dict:
    event_cases = []
    for race in cache["races"]:
        state = race["state"]
        series = series_by_state.get(state, [])
        move_date = find_signal_move_date(series, race["outcome_party"], band_offset=band_offset)
        lead_days = compute_lead_days(race["date"], move_date)
        event_cases.append({
            "state": state,
            "office": race["office"],
            "event_date": race["date"],
            "outcome_party": race["outcome_party"],
            "signal_move_date": move_date,
            "lead_days": lead_days,
            "classification": classify_event_case(lead_days),
        })

    quiet_cases = []
    for quiet in cache["quiet_states"]:
        state = quiet["state"]
        series = series_by_state.get(state, [])
        is_false_positive = check_quiet_state_false_positive(series, quiet["polling_stable"], band_offset=band_offset)
        quiet_cases.append({
            "state": state,
            "polling_stable": quiet["polling_stable"],
            "false_positive": is_false_positive,
        })

    return {"event_cases": event_cases, "quiet_cases": quiet_cases}


def count_states_with_coverage(results: dict) -> int:
    return len(results["event_cases"]) + len(results["quiet_cases"])


_CLASSIFICATION_COLORS = {
    "true_positive_lead": "#2b8a3e",
    "true_positive_same_day": "#5c940d",
    "true_positive_lag": "#e8590c",
    "miss": "#868e96",
}


def render_chart(results: dict, output_path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cases = results["event_cases"]
    labels = [f"{c['state']} ({c['office']})" for c in cases]
    values = [c["lead_days"] if c["lead_days"] is not None else 0 for c in cases]
    colors = [_CLASSIFICATION_COLORS[c["classification"]] for c in cases]

    fig, ax = plt.subplots(figsize=(10, max(4, len(cases) * 0.4)))
    ax.barh(labels, values, color=colors)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("Lead days (positive = signal led the outcome)")
    ax.set_title("Predictive-validity backtest: leaning_score vs. 2026 election outcomes")
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    plt.close(fig)


def render_findings_doc(results: dict, output_path: Path) -> str:
    events = results["event_cases"]
    quiet = results["quiet_cases"]
    leads = [c for c in events if c["classification"] in ("true_positive_lead", "true_positive_same_day")]
    misses = [c for c in events if c["classification"] == "miss"]
    lags = [c for c in events if c["classification"] == "true_positive_lag"]
    false_positives = [c for c in quiet if c["false_positive"]]

    verdict = "NULL RESULT" if not leads else "SIGNAL SHOWS SOME LEAD"

    lines = [
        "# Predictive-Validity Backtest Findings",
        "",
        f"**Verdict: {verdict}**",
        "",
        f"- {len(events)} election events tested, {len(leads)} led by the signal, "
        f"{len(lags)} lagged, {len(misses)} missed entirely.",
        f"- {len(quiet)} quiet states checked as negative controls, "
        f"{len(false_positives)} false positives (signal moved decisively with no confirming outcome).",
        "",
        "## Per-event results",
        "",
        "| State | Office | Event date | Outcome | Signal move date | Lead days | Classification |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in events:
        lines.append(
            f"| {c['state']} | {c['office']} | {c['event_date']} | {c['outcome_party']} | "
            f"{c['signal_move_date'] or '—'} | {c['lead_days'] if c['lead_days'] is not None else '—'} | "
            f"{c['classification']} |"
        )

    lines += ["", "## Quiet-state false positives", "", "| State | Polling stable | False positive |", "|---|---|---|"]
    for c in quiet:
        lines.append(f"| {c['state']} | {c['polling_stable']} | {c['false_positive']} |")

    doc = "\n".join(lines) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc, encoding="utf-8")
    return doc


def main() -> int:
    if not GROUND_TRUTH_CACHE.exists():
        raise SystemExit(
            f"{GROUND_TRUTH_CACHE} not found. Run scripts/fetch_ground_truth.py first."
        )
    cache = json.loads(GROUND_TRUTH_CACHE.read_text(encoding="utf-8"))

    base_url, service_key = get_supabase_config()
    rows = fetch_rest_rows(
        base_url, service_key, "regional_sentiment", "region,date,leaning_score",
        order="date.asc",
    )
    series_by_state = load_leaning_series_by_state(rows)

    results = build_case_results(cache, series_by_state)

    coverage = count_states_with_coverage(results)
    if coverage < MIN_COVERAGE_STATES:
        raise SystemExit(
            f"Only {coverage} states have usable ground-truth coverage "
            f"(minimum {MIN_COVERAGE_STATES}). Refusing to render a chart from insufficient data."
        )

    render_chart(results, CHART_PATH)
    render_findings_doc(results, REPORT_PATH)
    print(f"Wrote {CHART_PATH} and {REPORT_PATH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
