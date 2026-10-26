#!/usr/bin/env python3
"""Sweep decisive-band width and leaning_score smoothing to determine
whether the predictive-validity backtest's false-positive rate is fixable
mis-tuning or a genuinely null signal. Diagnostic only.

Usage:
  python3 scripts/sensitivity_sweep.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Support the existing `python scripts/sensitivity_sweep.py` entry point.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.analyze_validity import (
    MIN_COVERAGE_STATES,
    _DECISIVE_BAND_OFFSET,
    build_case_results,
    count_states_with_coverage,
    smooth_series,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

GROUND_TRUTH_CACHE = REPO_ROOT / "docs" / "data" / "ground_truth" / "2026-validity-backtest.json"
SERIES_CACHE = REPO_ROOT / "docs" / "data" / "ground_truth" / "leaning_score_series_cache.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "2026-07-sensitivity-sweep.md"

BAND_MULTIPLIERS = [1, 1.5, 2, 3]
SMOOTHING_WINDOWS = [1, 3, 5, 7]


def run_combo(cache: dict, series_by_state: dict, band_multiplier: float, smoothing_window: int) -> dict:
    smoothed_series_by_state = {
        state: smooth_series(series, smoothing_window) for state, series in series_by_state.items()
    }
    band_offset = _DECISIVE_BAND_OFFSET * band_multiplier
    results = build_case_results(cache, smoothed_series_by_state, band_offset=band_offset)

    events = results["event_cases"]
    quiet = results["quiet_cases"]
    leads = [c for c in events if c["classification"] in ("true_positive_lead", "true_positive_same_day")]
    lags = [c for c in events if c["classification"] == "true_positive_lag"]
    misses = [c for c in events if c["classification"] == "miss"]
    false_positives = [c for c in quiet if c["false_positive"]]

    return {
        "band_multiplier": band_multiplier,
        "smoothing_window": smoothing_window,
        "false_positive_rate": (len(false_positives) / len(quiet)) if quiet else 0.0,
        "lead_capture_rate": (len(leads) / len(events)) if events else 0.0,
        "lag_count": len(lags),
        "miss_count": len(misses),
    }


def run_sweep(cache: dict, series_by_state: dict) -> list[dict]:
    return [
        run_combo(cache, series_by_state, band_multiplier=m, smoothing_window=w)
        for m in BAND_MULTIPLIERS
        for w in SMOOTHING_WINDOWS
    ]


def rank_combos(combos: list[dict]) -> list[dict]:
    return sorted(combos, key=lambda c: (c["false_positive_rate"], -c["lead_capture_rate"]))


def render_report(ranked: list[dict], output_path: Path) -> str:
    lines = [
        "# Sensitivity Sweep: leaning_score Decisive Band & Smoothing",
        "",
        "Diagnostic only — no automatic winner. Read the false-positive/lead-capture",
        "tradeoff against the mid-August decision gate.",
        "",
        "| Band multiplier | Smoothing window (days) | False positive rate | Lead capture rate | Lag count | Miss count |",
        "|---|---|---|---|---|---|",
    ]
    for c in ranked:
        lines.append(
            f"| {c['band_multiplier']}x | {c['smoothing_window']} | "
            f"{c['false_positive_rate']:.2f} | {c['lead_capture_rate']:.2f} | "
            f"{c['lag_count']} | {c['miss_count']} |"
        )
    doc = "\n".join(lines) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(doc, encoding="utf-8")
    return doc


def main() -> int:
    if not GROUND_TRUTH_CACHE.exists():
        raise SystemExit(f"{GROUND_TRUTH_CACHE} not found. Run scripts/fetch_ground_truth.py first.")
    if not SERIES_CACHE.exists():
        raise SystemExit(f"{SERIES_CACHE} not found. Run scripts/fetch_leaning_series_cache.py first.")

    cache = json.loads(GROUND_TRUTH_CACHE.read_text(encoding="utf-8"))
    series_payload = json.loads(SERIES_CACHE.read_text(encoding="utf-8"))
    series_by_state = {
        state: [(d, float(s)) for d, s in series] for state, series in series_payload["series_by_state"].items()
    }

    coverage = count_states_with_coverage(build_case_results(cache, series_by_state))
    if coverage < MIN_COVERAGE_STATES:
        raise SystemExit(
            f"Only {coverage} states have usable ground-truth coverage "
            f"(minimum {MIN_COVERAGE_STATES}). Refusing to sweep insufficient data."
        )

    ranked = rank_combos(run_sweep(cache, series_by_state))
    render_report(ranked, REPORT_PATH)
    print(f"Wrote {REPORT_PATH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
