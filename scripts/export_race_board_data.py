#!/usr/bin/env python3
"""Export sanitized Race Board data for the single-page board.

Reads ``races`` and ``race_snapshots`` and writes, per date:
``docs/data/board/<date>.json`` plus ``index.json``. Each payload contains one
section per chamber (senate / house / governor) with the race rows, an exposure
tally, a deterministic board read, the day's band changelog, and a trend series.

The board describes monitored coverage and public campaign finance. Ratings are
Coverage Rating bands, not win probabilities.

Usage:
  python3 scripts/export_race_board_data.py
  python3 scripts/export_race_board_data.py --limit 14
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.districts import coverage_region_for_race, district_label, race_slug_for
from shared.supabase_rest import SupabaseRest
from shared.regions import STATE_DISPLAY_NAMES

ROOT = Path(__file__).resolve().parents[1]
BOARD_DATA_DIR = ROOT / "docs" / "data" / "board"
RACE_DATA_DIR = ROOT / "docs" / "data" / "races"

CHAMBERS = ("senate", "house", "governor")
CHAMBER_LABELS = {"senate": "Senate", "house": "House", "governor": "Governor"}
BAND_ORDER = ("Safe D", "Likely D", "Lean D", "Tossup", "Lean R", "Likely R", "Safe R")
CONTENDED_BANDS = ("Lean D", "Tossup", "Lean R")
# A band "move" is measured over this many editions, not one, so a transient
# one-day flip in thin coverage does not register as news.
HYSTERESIS_EDITIONS = 3
PUBLIC_RACE_FIELDS = (
    "race_id", "chamber", "state", "state_name", "district", "label", "slug",
    "incumbent_party", "rating_band", "rating_score", "thin_signal", "has_signal",
    "coverage_leaning", "source_count", "top_issue", "dem_money", "rep_money", "fec_coverage",
)
RACE_DETAIL_FIELDS = PUBLIC_RACE_FIELDS + (
    "seat_status", "coverage_tone", "ie_support", "ie_oppose",
    "digital_spend_wk", "digital_refreshed",
    "methodology_version", "candidates", "evidence",
)

_SNAPSHOT_SELECT = (
    "run_date,race_id,rating_band,rating_score,rating_confidence,coverage_leaning,coverage_tone,"
    "source_count,dem_money,rep_money,ie_support,ie_oppose,fec_coverage,methodology_version,"
    "issue_mix,evidence"
)


def require_env() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY must be set.")
    return url.rstrip("/"), key


def state_name(state: str) -> str:
    return STATE_DISPLAY_NAMES.get(state, str(state).removeprefix("US-"))


def race_label(race: dict) -> str:
    postal = str(race.get("state", "")).removeprefix("US-")
    if race.get("chamber") == "house" and race.get("district") is not None:
        return district_label(postal, int(race["district"]))
    return state_name(race.get("state", ""))


def band_counts(rows: list[dict], *, monitored_only: bool = False) -> dict[str, int]:
    counts = {band: 0 for band in BAND_ORDER}
    for row in rows:
        if monitored_only and not _has_signal(row):
            continue
        band = row.get("rating_band")
        if band in counts:
            counts[band] += 1
    return counts


def exposure_tally(rows: list[dict]) -> dict:
    """Seat exposure by rating band, counted over races with monitored input.

    A race with no monitored coverage has its missing components renormalized to
    neutral, which lands on Tossup. Counting those as tossups would read as a horse
    race that does not exist, so they are reported as their own number instead.
    """
    counts = band_counts(rows, monitored_only=True)
    monitored = sum(counts.values())
    contested = sum(counts[band] for band in CONTENDED_BANDS)
    return {
        "seats": len(rows),
        "monitored": monitored,
        "not_monitored": len(rows) - monitored,
        "contested": contested,
        "bands": counts,
    }


def _direction(counts: dict[str, int]) -> str:
    dem = counts["Safe D"] + counts["Likely D"] + counts["Lean D"]
    rep = counts["Safe R"] + counts["Likely R"] + counts["Lean R"]
    if dem > rep:
        return "Democratic"
    if rep > dem:
        return "Republican"
    return "even"


def board_read(chamber: str, tally: dict) -> str:
    """One deterministic sentence describing the board. Never a prediction."""
    label = CHAMBER_LABELS.get(chamber, chamber.title())
    counts = tally["bands"]
    direction = _direction(counts)
    monitored = tally.get("monitored", sum(counts.values()))
    if direction == "even":
        lead = (
            f"Monitored coverage is split across the {monitored} {label} seats with "
            "monitored coverage"
        )
    else:
        lead = (
            f"Monitored coverage runs {direction}-ward across the {monitored} "
            f"{label} seats with monitored coverage"
        )
    return (
        f"{lead}, with {tally['contested']} in the contested range and "
        f"{counts['Tossup']} in the tossup band. "
        f"{tally.get('not_monitored', 0)} of the {tally['seats']} seats on the board "
        "have no monitored coverage yet."
    )


def changelog(current_rows: list[dict], prior_bands: dict[str, str]) -> list[dict]:
    """Races whose rating band differs from the prior available date, ranked.

    Ranked by band-step distance (bigger moves first) so the daily brief can
    lead with the most significant change instead of an alphabetical list.
    """
    movers: list[dict] = []
    for row in current_rows:
        race_id = row["race_id"]
        prior = prior_bands.get(race_id)
        current = row.get("rating_band")
        if not prior or not current or prior == current:
            continue
        # A band move only counts as news when the race has real coverage behind
        # it; a no-coverage race moving is measurement noise, not a story.
        if not row.get("source_count") or row["source_count"] < 2:
            continue
        movers.append({
            "race_id": race_id,
            "label": row["label"],
            "state": row["state"],
            "slug": row.get("slug"),
            "from_band": prior,
            "to_band": current,
            "significance": mover_significance(prior, current),
            "toward": _band_side(current) if _band_side(current) != "TOSS" else "tossup",
            "top_issue": row.get("top_issue"),
            "source_count": row.get("source_count"),
            "dem_money": row.get("dem_money"),
            "rep_money": row.get("rep_money"),
        })
    movers.sort(key=lambda item: (-item["significance"], item["label"]))
    return movers


def _band_index(band: str | None) -> int:
    return BAND_ORDER.index(band) if band in BAND_ORDER else len(BAND_ORDER) // 2


def mover_significance(from_band: str | None, to_band: str | None) -> int:
    """Band-step distance, with a bonus for crossing the tossup midpoint."""
    if from_band is None or to_band is None:
        return 0
    step = abs(_band_index(to_band) - _band_index(from_band))
    crossed_midpoint = (
        _band_index(from_band) - 3
    ) * (_band_index(to_band) - 3) <= 0 and from_band != to_band
    return step + (1 if crossed_midpoint else 0)


def _band_side(band: str | None) -> str:
    if band in ("Safe D", "Likely D", "Lean D"):
        return "D"
    if band in ("Safe R", "Likely R", "Lean R"):
        return "R"
    return "TOSS"


def _top_issue(issue_mix: dict | None) -> str | None:
    if not isinstance(issue_mix, dict) or not issue_mix:
        return None
    try:
        topic, score = max(issue_mix.items(), key=lambda kv: float(kv[1] or 0))
    except (TypeError, ValueError):
        return None
    return str(topic) if float(score or 0) > 0 else None


def chamber_read(chamber: str, tally: dict, movers: list[dict]) -> str:
    """A change-first sentence. Names the day's most significant mover."""
    label = CHAMBER_LABELS.get(chamber, chamber.title())
    if movers:
        top = movers[0]
        verb = "flipped" if top["toward"] == "tossup" else f"moved {top['toward']}-ward"
        issue = f" on {top['top_issue'].replace('_', ' ')} coverage" if top.get("top_issue") else ""
        return (
            f"{len(movers)} {label} seats changed bands, led by "
            f"{top['label']}, which {verb} from {top['from_band']} to "
            f"{top['to_band']}{issue}."
        )
    return board_read(chamber, tally)


def trend_point(rows: list[dict]) -> dict:
    scores = [float(row["rating_score"]) for row in rows if row.get("rating_score") is not None]
    counts = band_counts(rows)
    monitored_counts = band_counts(rows, monitored_only=True)
    avg = round(sum(scores) / len(scores), 2) if scores else None
    return {
        "avg_score": avg,
        "tossup": counts["Tossup"],
        "contested": sum(counts[band] for band in CONTENDED_BANDS),
        # The all-rows counts above are kept so the series stays continuous; these
        # are the honest ones, since an unmonitored race renormalizes to Tossup.
        "monitored": sum(monitored_counts.values()),
        "tossup_monitored": monitored_counts["Tossup"],
        "contested_monitored": sum(monitored_counts[band] for band in CONTENDED_BANDS),
    }


def _has_signal(snapshot: dict) -> bool:
    """True when a race has enough measured input to rate meaningfully.

    Coverage breadth (>=2 sources) or FEC money. A race with neither is "no
    data", not "close" — the map must not paint it as a tossup. Supabase returns
    numerics as strings through its REST and management APIs, so both inputs are
    coerced rather than compared as they arrive.
    """
    try:
        sources = int(snapshot.get("source_count") or 0)
        fec_coverage = float(snapshot.get("fec_coverage") or 0)
    except (TypeError, ValueError):
        return False
    return sources >= 2 or fec_coverage > 0


def public_race_row(race: dict, snapshot: dict) -> dict:
    score = snapshot.get("rating_score")
    confidence = snapshot.get("rating_confidence")
    return {
        "race_id": race["race_id"],
        "chamber": race["chamber"],
        "state": race["state"],
        "state_name": state_name(race["state"]),
        "district": race.get("district"),
        "label": race_label(race),
        "slug": race_slug_for(race),
        "incumbent_party": race.get("incumbent_party"),
        "rating_band": snapshot.get("rating_band"),
        "rating_score": round(float(score), 2) if score is not None else None,
        "thin_signal": confidence is not None and float(confidence) < 0.5,
        "has_signal": _has_signal(snapshot),
        "coverage_leaning": snapshot.get("coverage_leaning"),
        "source_count": snapshot.get("source_count"),
        "top_issue": _top_issue(snapshot.get("issue_mix")),
        "dem_money": snapshot.get("dem_money"),
        "rep_money": snapshot.get("rep_money"),
        "fec_coverage": snapshot.get("fec_coverage"),
    }


def sanitize_candidates(rows: list[dict]) -> list[dict]:
    clean: list[dict] = []
    for row in rows:
        name = str(row.get("candidate_name") or "").strip()
        if not name:
            continue
        clean.append({
            "name": name,
            "party": str(row.get("party") or "").strip(),
            "ie_support_7d": row.get("ie_support_7d"),
            "ie_oppose_7d": row.get("ie_oppose_7d"),
        })
    clean.sort(key=lambda item: (item["party"], item["name"]))
    return clean


def sanitize_evidence(rows: list[dict]) -> list[dict]:
    from urllib.parse import urlparse

    clean: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        url = str(row.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or url in seen:
            continue
        seen.add(url)
        clean.append({
            "title": str(row.get("title") or "").strip(),
            "url": url,
            "source_name": str(row.get("source_name") or "").strip(),
        })
    return clean[:6]


def public_race_detail(
    race: dict,
    snapshot: dict,
    candidates: list[dict],
    evidence: list[dict],
    *,
    digital_spend_wk: float | None = None,
    digital_refreshed: str | None = None,
) -> dict:
    row = public_race_row(race, snapshot)
    row.update({
        "seat_status": race.get("seat_status"),
        "coverage_tone": snapshot.get("coverage_tone"),
        "ie_support": snapshot.get("ie_support"),
        "ie_oppose": snapshot.get("ie_oppose"),
        # Digital placement spend is shown, never rated: it is a weekly,
        # state-apportioned estimate, so it cannot carry a band. It also covers
        # only advertisers matched to FEC filings; state-level issue advertising
        # is not attributed to any race.
        "digital_spend_wk": digital_spend_wk,
        "digital_refreshed": digital_refreshed,
        "methodology_version": snapshot.get("methodology_version", "coverage-rating-v1"),
        "candidates": sanitize_candidates(candidates),
        "evidence": sanitize_evidence(evidence),
    })
    return {key: row.get(key) for key in RACE_DETAIL_FIELDS}


def build_board_payload(
    *,
    run_date: str,
    races: list[dict],
    snapshots_by_race: dict[str, dict],
    prior_bands: dict[str, str],
    trend_by_chamber: dict[str, list[dict]] | None = None,
) -> dict:
    """Assemble one date's board payload. Pure and deterministic (no clock)."""
    chambers: dict[str, dict] = {}
    for chamber in CHAMBERS:
        chamber_races = [race for race in races if race.get("chamber") == chamber]
        rows = [
            public_race_row(race, snapshots_by_race.get(race["race_id"], {}))
            for race in chamber_races
        ]
        rows.sort(key=lambda row: (row["label"], row["race_id"]))
        tally = exposure_tally(rows)
        movers = changelog(rows, prior_bands)
        chambers[chamber] = {
            "races": rows,
            "tally": tally,
            "read": chamber_read(chamber, tally, movers),
            "changelog": movers,
            "trend": (trend_by_chamber or {}).get(chamber, []),
        }
    board = {"date": run_date, "chambers": chambers}
    board["lead"] = board_lead(board)
    board["subject"] = board_subject(board)
    return board


def _all_movers(board: dict) -> list[dict]:
    movers: list[dict] = []
    for chamber in CHAMBERS:
        for mover in board["chambers"][chamber]["changelog"]:
            movers.append({**mover, "chamber": chamber})
    movers.sort(key=lambda item: (-item["significance"], item["label"]))
    return movers


def board_lead(board: dict) -> str:
    """One specific, change-first sentence: a place, a move, and a reason."""
    movers = _all_movers(board)
    if movers:
        top = movers[0]
        issue = (
            f" on {top['top_issue'].replace('_', ' ')} coverage" if top.get("top_issue") else ""
        )
        direction = {
            "D": "toward Democrats",
            "R": "toward Republicans",
            "tossup": "back into tossup",
        }.get(top["toward"], "across the board")
        monitored = sum(
            board["chambers"][c]["tally"].get("monitored", 0) for c in CHAMBERS
        )
        return (
            f"{top['label']} moved {direction}, from {top['from_band']} to "
            f"{top['to_band']}{issue} — one of {len(movers)} of {monitored} monitored "
            "seats to change bands."
        )
    totals = ", ".join(
        f"{board['chambers'][c]['tally']['seats']} {CHAMBER_LABELS[c]}" for c in CHAMBERS
    )
    return f"No rating bands changed since the prior edition ({totals} seats on the board)."


def board_subject(board: dict) -> str:
    movers = _all_movers(board)
    if movers:
        top = movers[0]
        return f"{top['label']}: {top['from_band']} → {top['to_band']} — {len(movers)} seats moved"
    return f"Race Board: no seat moves on {board['date']}"


def top_movers(board: dict, limit: int = 3) -> list[dict]:
    """The most significant band moves across all chambers."""
    return _all_movers(board)[:limit]


def sanitize_board_payload(payload: dict) -> dict:
    """Re-derive the public payload from raw rows, dropping any private fields."""
    clean: dict = {
        "date": payload["date"],
        "lead": payload.get("lead"),
        "subject": payload.get("subject"),
        "chambers": {},
    }
    for chamber, section in payload["chambers"].items():
        clean["chambers"][chamber] = {
            "races": [
                {k: row[k] for k in PUBLIC_RACE_FIELDS if k in row}
                for row in section["races"]
            ],
            "tally": section["tally"],
            "read": section["read"],
            "changelog": section["changelog"],
            "trend": section["trend"],
        }
    return clean


# ---------------------------------------------------------------------------
# Network I/O
# ---------------------------------------------------------------------------



def _client(base_url: str, service_key: str) -> SupabaseRest:
    return SupabaseRest(base_url, service_key)


def fetch_races(base_url: str, service_key: str, cycle: int) -> list[dict]:
    return _client(base_url, service_key).get(
        f"races?cycle=eq.{cycle}"
        "&select=race_id,chamber,state,district,incumbent_party,seat_status&order=race_id",
    )


def fetch_snapshots(
    base_url: str, service_key: str, dates: list[str] | None = None
) -> list[dict]:
    filter_clause = ""
    if dates:
        date_filter = urllib.parse.quote(",".join(sorted(set(dates))), safe=",")
        filter_clause = f"run_date=in.({date_filter})&"
    return _client(base_url, service_key).get(
        f"race_snapshots?{filter_clause}select={_SNAPSHOT_SELECT}&order=run_date.desc",
    )


def _group_by(rows: list[dict], key: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row[key], []).append(row)
    return grouped


def fetch_candidates(base_url: str, service_key: str, run_date: str) -> list[dict]:
    return _client(base_url, service_key).get(
        "ad_spend_signals?run_date=eq."
        + urllib.parse.quote(run_date)
        + "&candidate_id=neq.&select=candidate_name,party,district,ie_support_7d,ie_oppose_7d",
    )


def fetch_digital_spend(base_url: str, service_key: str) -> tuple[dict[str, float], str | None]:
    """Return the newest weekly digital-placement estimate, keyed by race label.

    The Google political-ads refresh is weekly, so most run dates carry no digital
    value at all. Take the newest date that has one rather than reading today's
    null as zero, and report that date so a week-old estimate is not presented as
    today's spend. Rows with no candidate id are state-level issue advertising and
    are deliberately excluded: they cannot be attributed to a race.
    """
    client = _client(base_url, service_key)
    newest = client.get(
        "ad_spend_signals?digital_spend_wk=not.is.null&candidate_id=neq."
        "&select=run_date&order=run_date.desc&limit=1",
    )
    if not newest:
        return {}, None
    refreshed = str(newest[0]["run_date"])
    rows = client.get(
        "ad_spend_signals?run_date=eq."
        + urllib.parse.quote(refreshed)
        + "&candidate_id=neq.&digital_spend_wk=not.is.null&select=district,digital_spend_wk",
    )
    totals: dict[str, float] = {}
    for row in rows:
        key = str(row.get("district") or "").strip()
        if not key:
            continue
        try:
            amount = float(row.get("digital_spend_wk") or 0)
        except (TypeError, ValueError):
            continue
        totals[key] = totals.get(key, 0.0) + amount
    return totals, refreshed


def fetch_headlines(base_url: str, service_key: str, run_date: str) -> list[dict]:
    return _client(base_url, service_key).get(
        f"word_frequencies?date=eq.{urllib.parse.quote(run_date)}&select=region,supporting_headlines",
    )


def candidate_key_for(race: dict) -> str | None:
    """Return the ad-spend key that holds a race's candidate rows.

    Candidate rows carry the district label for House races and the state postal
    code for Senate races; governors file nothing with the FEC.
    """
    chamber = race.get("chamber")
    if chamber == "house":
        return race_label(race)
    if chamber == "senate":
        return str(race.get("state", "")).removeprefix("US-")
    return None


def export_race_details(
    base_url: str,
    service_key: str,
    run_date: str,
    races: list[dict],
    snapshot_rows: list[dict],
) -> int:
    snapshots_by_race = {row["race_id"]: row for row in snapshot_rows}
    candidates_by_district = _group_by(fetch_candidates(base_url, service_key, run_date), "district")
    headlines_by_region = {
        row["region"]: row.get("supporting_headlines") or []
        for row in fetch_headlines(base_url, service_key, run_date)
    }

    RACE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    index: dict[str, str] = {}
    digital_by_key, digital_refreshed = fetch_digital_spend(base_url, service_key)
    for race in races:
        snapshot = snapshots_by_race.get(race["race_id"], {})
        region = coverage_region_for_race(race)
        candidate_key = candidate_key_for(race)
        detail = public_race_detail(
            race,
            snapshot,
            candidates_by_district.get(candidate_key, []) if candidate_key else [],
            headlines_by_region.get(region, []),
            digital_spend_wk=digital_by_key.get(candidate_key or "", None),
            digital_refreshed=digital_refreshed,
        )
        (RACE_DATA_DIR / f"{detail['slug']}.json").write_text(
            json.dumps(detail, indent=2), encoding="utf-8"
        )
        index[detail["slug"]] = detail["race_id"]
    (RACE_DATA_DIR / "index.json").write_text(
        json.dumps({"date": run_date, "races": index}, indent=2), encoding="utf-8"
    )
    return len(index)


def export(limit: int) -> None:
    base_url, service_key = require_env()
    races = fetch_races(base_url, service_key, 2026)
    race_by_id = {race["race_id"]: race for race in races}
    snapshots = fetch_snapshots(base_url, service_key)
    by_date = _group_by(snapshots, "run_date")
    dates = sorted(by_date, reverse=True)[:limit]

    trend_by_chamber: dict[str, dict[str, dict]] = {chamber: {} for chamber in CHAMBERS}
    for date in sorted(dates):
        rows_by_race = _group_by(by_date[date], "race_id")
        for chamber in CHAMBERS:
            chamber_rows = [
                row
                for race_id, rows in rows_by_race.items()
                if race_by_id.get(race_id, {}).get("chamber") == chamber
                for row in rows
            ]
            trend_by_chamber[chamber][date] = trend_point(chamber_rows)

    trend = {
        chamber: [{"date": d, **trend_by_chamber[chamber][d]} for d in sorted(dates)]
        for chamber in CHAMBERS
    }

    BOARD_DATA_DIR.mkdir(parents=True, exist_ok=True)
    published_dates: list[str] = []
    for index, date in enumerate(dates):
        snapshots_by_race = {row["race_id"]: row for row in by_date[date]}
        prior_index = index + HYSTERESIS_EDITIONS
        if prior_index >= len(dates):
            prior_index = index + 1 if index + 1 < len(dates) else None
        prior = dates[prior_index] if prior_index is not None else None
        prior_bands = (
            {row["race_id"]: row["rating_band"] for row in by_date[prior]} if prior else {}
        )
        payload = build_board_payload(
            run_date=date,
            races=races,
            snapshots_by_race=snapshots_by_race,
            prior_bands=prior_bands,
            trend_by_chamber=trend,
        )
        (BOARD_DATA_DIR / f"{date}.json").write_text(
            json.dumps(sanitize_board_payload(payload), indent=2), encoding="utf-8"
        )
        published_dates.append(date)

    (BOARD_DATA_DIR / "index.json").write_text(
        json.dumps({
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "available_dates": published_dates,
        }, indent=2),
        encoding="utf-8",
    )
    print(f"Exported board data for {len(published_dates)} date(s) to {BOARD_DATA_DIR}")
    if published_dates:
        latest = published_dates[0]
        count = export_race_details(base_url, service_key, latest, races, by_date[latest])
        print(f"Exported {count} race detail file(s) for {latest} to {RACE_DATA_DIR}")
        maps = export_chamber_maps(latest, races, by_date[latest])
        print(f"Exported {maps} chamber map(s) for {latest} to {BOARD_DATA_DIR}")


def export_chamber_maps(run_date: str, races: list[dict], snapshots: list[dict]) -> int:
    """Render the PNG maps the email embeds, beside the board data the site serves.

    Email clients strip SVG, so the email needs a raster; hosting it under the board
    data means the site deploy carries it and no separate bucket is involved.
    """
    from scripts.render_chamber_map import map_path, render_chamber_map, render_house_grid
    from shared.coverage_rating import BAND_COLORS

    snapshots_by_race = {row["race_id"]: row for row in snapshots}
    rows = [
        public_race_row(race, snapshots_by_race.get(race["race_id"], {}))
        for race in races
    ]
    written = 0
    for chamber in ("senate", "governor", "house"):
        target = BOARD_DATA_DIR / map_path(chamber, run_date)
        target.parent.mkdir(parents=True, exist_ok=True)
        chamber_rows = [row for row in rows if row["chamber"] == chamber]
        # The House has no district geometry, so it gets a grid of one square per seat
        # rather than a map; the other two draw state shapes.
        image = (
            render_house_grid(chamber_rows, colors=BAND_COLORS)
            if chamber == "house"
            else render_chamber_map(chamber_rows, colors=BAND_COLORS)
        )
        target.write_bytes(image)
        written += 1
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=14, help="Most recent dates to export.")
    args = parser.parse_args()
    export(args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
