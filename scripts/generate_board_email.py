#!/usr/bin/env python3
"""Generate the daily Race Board email — one email, no party lanes.

The email leads with a specific, change-first sentence (a place, a move, and a
reason), ranked movers, and a real race spotlight: candidates, money, and the
coverage behind it. Deliberately caveated — it describes monitored coverage and
public campaign finance, never a forecast.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.coverage_rating import BAND_COLORS
from shared.districts import coverage_region_for_race, district_label
from shared.supabase_rest import SupabaseRest
from scripts.export_race_board_data import (
    BAND_ORDER,
    build_board_payload,
    fetch_candidates,
    fetch_headlines,
    fetch_races,
    fetch_snapshots,
    sanitize_candidates,
    sanitize_evidence,
    top_movers,
)
from scripts.r2_object_store import put_bytes as put_r2_bytes, storage_provider

BOARD_EMAIL_TEMPLATE_VERSION = "v2"
BOARD_EMAIL_ARTIFACT_TYPE = "race_board_email"
BOARD_EMAIL_REGION = "national"
ARTIFACT_BUCKET = "artifacts"
DEFAULT_BOARD_URL = "https://dashboard.example.invalid/board"

CAVEAT = (
    "Based on monitored news coverage and public campaign finance only — "
    "not public opinion research or vote intention."
)

PROHIBITED_PATTERNS = (
    (r"\bforecast", "forecast"),
    (r"\bprobabilit", "probability"),
    (r"\bpredict", "predict"),
    (r"\bwill win\b", "will win"),
    (r"\bwinning\b", "winning"),
    (r"\bvoters? (are|will|have) mov", "voters moving"),
    (r"\blikely to win\b", "likely to win"),
)


def check_prohibited_language(text: str) -> list[str]:
    lowered = text.lower()
    return [label for pattern, label in PROHIBITED_PATTERNS if re.search(pattern, lowered)]


def require_env() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY must be set.")
    return url.rstrip("/"), key


def fetch_prior_date(base_url: str, service_key: str, run_date: str) -> str | None:
    rows = SupabaseRest(base_url, service_key).get(
        f"race_snapshots?run_date=lt.{run_date}&select=run_date&order=run_date.desc&limit=1"
    )
    return rows[0]["run_date"] if rows else None


def load_board(run_date: str, base_url: str, service_key: str) -> dict:
    races = fetch_races(base_url, service_key, 2026)
    prior_date = fetch_prior_date(base_url, service_key, run_date)
    dates = [run_date] + ([prior_date] if prior_date else [])
    rows = fetch_snapshots(base_url, service_key, dates)
    current = {row["race_id"]: row for row in rows if row["run_date"] == run_date}
    prior = {row["race_id"]: row["rating_band"] for row in rows if row["run_date"] == prior_date}
    return build_board_payload(
        run_date=run_date,
        races=races,
        snapshots_by_race=current,
        prior_bands=prior,
    )


def select_spotlight(board: dict) -> dict | None:
    """The day's most notable race: the biggest mover, else the closest tossup."""
    movers = top_movers(board, 1)
    if movers:
        return movers[0]
    for chamber in ("senate", "house", "governor"):
        for race in board["chambers"][chamber]["races"]:
            # Only a race with monitored coverage: an unmonitored race renormalizes
            # to a neutral score, so its "Tossup" is the absence of data rather than
            # a close race.
            if (
                race.get("has_signal")
                and race.get("rating_band") == "Tossup"
                and race.get("slug")
            ):
                return {
                    "label": race["label"], "state": race["state"], "slug": race["slug"],
                    "from_band": "—", "to_band": "Tossup", "toward": "tossup",
                    "top_issue": race.get("top_issue"), "chamber": chamber,
                    "dem_money": race.get("dem_money"), "rep_money": race.get("rep_money"),
                }
    return None


def load_spotlight_enrichment(
    base_url: str, service_key: str, run_date: str, race_row: dict
) -> dict:
    """Candidates, money, and coverage headlines for the spotlight race."""
    postal = str(race_row.get("state", "")).removeprefix("US-")
    district = (
        district_label(postal, int(race_row["district"]))
        if race_row.get("chamber") == "house" and race_row.get("district") is not None
        else None
    )
    candidates: list[dict] = []
    if district:
        candidates = [
            row for row in fetch_candidates(base_url, service_key, run_date)
            if row.get("district") == district
        ]
    region = coverage_region_for_race({
        "chamber": race_row.get("chamber"), "state": race_row.get("state"),
        "district": race_row.get("district"),
    })
    headlines = [
        row for row in fetch_headlines(base_url, service_key, run_date)
        if row.get("region") == region
    ]
    evidence = (headlines[0].get("supporting_headlines") if headlines else []) or []
    return {
        "candidates": sanitize_candidates(candidates),
        "evidence": sanitize_evidence(evidence),
    }


def board_url(cta_base_url: str, slug: str | None = None) -> str:
    base = (cta_base_url or DEFAULT_BOARD_URL).rstrip("/")
    return f"{base}/race/{slug}/" if slug else f"{base}/"


def _money(value) -> str:
    if value is None:
        return "—"
    try:
        return f"${float(value):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _direction_phrase(toward: str) -> str:
    return {
        "D": "toward Democrats",
        "R": "toward Republicans",
        "tossup": "back into tossup",
    }.get(toward, "across the board")


CHAMBER_TITLES = {"senate": "Senate", "house": "House", "governor": "Governors"}


def chamber_distribution_read(tally: dict) -> str:
    """The lead and the implication, before the counts.

    Mirrors the board's own framing — monitored coverage "runs Democratic-ward" — so
    the email does not describe bands as an electoral standing.
    """
    bands = tally["bands"]
    dem = sum(bands.get(band, 0) for band in ("Safe D", "Likely D", "Lean D"))
    rep = sum(bands.get(band, 0) for band in ("Safe R", "Likely R", "Lean R"))
    tossup = bands.get("Tossup", 0)
    monitored = int(tally.get("monitored") or sum(bands.values()))
    if not monitored:
        return "No seat in this chamber has monitored coverage yet."
    if dem > rep:
        lead = f"Monitored coverage runs Democratic-ward, {dem} to {rep}"
    elif rep > dem:
        lead = f"Monitored coverage runs Republican-ward, {rep} to {dem}"
    else:
        lead = f"Monitored coverage is split evenly, {dem} each"
    return f"{lead}, with {tossup} in the tossup band."


def chamber_map_urls(run_date: str) -> dict[str, str]:
    """Absolute URLs for the chamber maps, served with the board data.

    The House grid is a later slice, so only the two rendered maps are listed; an
    image URL that 404s would be worse than no image.
    """
    base = os.environ.get("NEWSCLOUD_DASHBOARD_URL", "").rstrip("/")
    if not base or not run_date:
        return {}
    from scripts.render_chamber_map import map_path

    return {
        chamber: f"{base}/data/{map_path(chamber, run_date)}"
        for chamber in ("senate", "governor", "house")
    }


def render_chamber_bars(board: dict, map_urls: dict[str, str] | None = None) -> str:
    """One stacked bar per chamber, over races with monitored coverage.

    Table cells with percentage widths, because email clients lay out neither flex
    nor SVG. Seats without monitored coverage are named in the note rather than
    painted: an unmonitored race renormalizes to a neutral score, so painting it
    would read as a competitive seat.
    """
    rows = []
    for chamber in ("senate", "house", "governor"):
        section = board["chambers"].get(chamber)
        if not section:
            continue
        tally = section["tally"]
        bands = tally["bands"]
        seats = int(tally.get("seats") or 0)
        monitored = int(tally.get("monitored") or sum(bands.values()))
        label = CHAMBER_TITLES.get(chamber, chamber.title())
        cells = ""
        legend = []
        for band in BAND_ORDER:
            count = int(bands.get(band) or 0)
            if not count or not monitored:
                continue
            share = count / monitored
            # A count inside a narrow segment is unreadable, so it is shown only where
            # the segment is wide enough to hold it — the rule the board site uses.
            label_text = f"{count}" if share >= 0.10 else ""
            cells += (
                f'<td style="background:{BAND_COLORS[band]};width:{share * 100:.2f}%;'
                'height:18px;font-size:11px;line-height:18px;text-align:center;color:#ffffff">'
                f"{label_text}</td>"
            )
            legend.append(f"{html.escape(band)} {count}")
        if not cells:
            cells = '<td style="background:#dad4cb;width:100%;height:18px"></td>'
        not_monitored = int(tally.get("not_monitored") or 0)
        note = f"{monitored} of {seats} seats with monitored coverage"
        if not_monitored:
            note += f" · {not_monitored} without"
        # The coloured bar is sized to the monitored share of the chamber, on a grey
        # track: the House is 86 of 435 seats, and a full-width bar would claim
        # coverage the board does not have.
        ratio = monitored / seats * 100 if seats else 0.0
        read = chamber_distribution_read(tally)
        url = (map_urls or {}).get(chamber)
        map_html = (
            f'<img src="{html.escape(url)}" alt="{html.escape(label)} map" '
            'style="display:block;width:100%;max-width:552px;height:auto;margin:0 0 6px">'
            if url else ""
        )
        rows.append(
            f'<p style="margin:0 0 2px;font-weight:700;color:#16130f">{html.escape(label)}</p>'
            f'{map_html}'
            f'<p style="margin:0 0 4px;color:#16130f;font-size:13px">{html.escape(read)}</p>'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="border-collapse:collapse"><tr><td style="background:#e6e0d6;padding:0">'
            f'<table role="presentation" width="{ratio:.2f}%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;table-layout:fixed"><tr>{cells}</tr></table>'
            '</td></tr></table>'
            f'<p style="margin:4px 0 12px;color:#6b6157;font-size:12px">'
            f'{" · ".join(legend)} — {note}</p>'
        )
    if not rows:
        return ""
    key = "".join(
        f'<span style="display:inline-block;margin:0 8px 2px 0;white-space:nowrap">'
        f'<span style="display:inline-block;width:9px;height:9px;background:{BAND_COLORS[band]}"></span>'
        f' {html.escape(band)}</span>'
        for band in BAND_ORDER
    )
    return (
        '<h2 style="font-size:15px;text-transform:uppercase;letter-spacing:1px;'
        'color:#6b6157;margin:0 0 8px">Chamber distribution</h2>'
        '<p style="margin:0 0 10px;color:#6b6157;font-size:12px">Monitored coverage only. '
        'The board follows a selected set of states and districts, so a seat outside it is '
        'shown as not monitored rather than as a close race. The House view is one square per '
        'district, grouped by state in census-region order, because a district map needs '
        'boundaries the board does not license.</p>'
        f'<p style="margin:0 0 12px;color:#6b6157;font-size:11px">{key}</p>' + "".join(rows)
    )


def render_chamber_bars_text(board: dict, map_urls: dict[str, str] | None = None) -> list[str]:
    """The same distribution as plain lines, for the text edition."""
    lines: list[str] = []
    for chamber in ("senate", "house", "governor"):
        section = board["chambers"].get(chamber)
        if not section:
            continue
        tally = section["tally"]
        bands = {band: count for band, count in tally["bands"].items() if count}
        seats = int(tally.get("seats") or 0)
        monitored = int(tally.get("monitored") or sum(tally["bands"].values()))
        label = CHAMBER_TITLES.get(chamber, chamber.title())
        counts = ", ".join(f"{band} {count}" for band, count in bands.items()) or "no bands"
        lines.append(
            f"- {label}: {chamber_distribution_read(tally)} "
            f"({counts}; {monitored} of {seats} seats with monitored coverage)"
        )
        if (map_urls or {}).get(chamber):
            lines.append(f"  Map: {map_urls[chamber]}")
    return lines


def render_board_text_email(
    board: dict, cta_base_url: str = "", map_urls: dict[str, str] | None = None
) -> str:
    if map_urls is None:
        map_urls = chamber_map_urls(str(board.get("date") or ""))
    movers = top_movers(board, 3)
    spotlight = board.get("spotlight") or select_spotlight(board)
    # A mover carries a race_id; the "closest tossup" fallback does not. That is what
    # tells the two cases apart, so the top mover is never told twice.
    lead_is_mover = bool(spotlight and spotlight.get("race_id"))
    rest = [mover for mover in movers if mover.get("race_id") != (spotlight or {}).get("race_id")]
    lines = [f"NEWSCLOUD RACE BOARD — {board['date']}", "", board["lead"], ""]

    if spotlight:
        heading = "Moved on the board" if lead_is_mover else "Spotlight"
        lines.append(f"{heading} — {spotlight['label']} ({spotlight['to_band']})")
        reason = (
            f" on {spotlight['top_issue'].replace('_', ' ')} coverage"
            if spotlight.get("top_issue") else ""
        )
        moved = (
            f"{spotlight['from_band']} → {spotlight['to_band']}, "
            f"{_direction_phrase(spotlight.get('toward', ''))}"
            if lead_is_mover
            else spotlight["to_band"]
        )
        lines.append(f"{moved}{reason}.")
        if spotlight.get("dem_money") is not None or spotlight.get("rep_money") is not None:
            dem_money = _money(spotlight.get("dem_money")) if spotlight.get("dem_money") else "none reported"
            rep_money = _money(spotlight.get("rep_money")) if spotlight.get("rep_money") else "none reported"
            lines.append(
                f"Money (outside spending reported to the FEC): "
                f"{dem_money} favoring Democrats · "
                f"{rep_money} favoring Republicans."
            )
        for candidate in spotlight.get("candidates", [])[:4]:
            lines.append(
                f"- {candidate['name']} ({candidate['party'] or '—'}): "
                f"{_money(candidate.get('ie_support_7d'))} outside support, "
                f"{_money(candidate.get('ie_oppose_7d'))} opposed"
            )
        for item in spotlight.get("evidence", [])[:3]:
            lines.append(f'Coverage: "{item["title"]}" — {item["source_name"]} {item["url"]}')
        lines.append(f"Race page: {board_url(cta_base_url, spotlight.get('slug'))}")
        lines.append("")

    if rest:
        lines.append("Also moved:")
        for mover in rest:
            issue = f" ({mover['top_issue'].replace('_', ' ')})" if mover.get("top_issue") else ""
            lines.append(f"- {mover['label']}: {mover['from_band']} → {mover['to_band']}{issue}")
        lines.append("")
    elif not movers:
        lines.append("No rating bands moved since the prior edition.")
        lines.append("")

    lines.append("Chamber distribution (races with monitored coverage):")
    lines.extend(render_chamber_bars_text(board, map_urls))
    lines.append("")
    lines.append(f"See the full board: {board_url(cta_base_url)}")
    lines.append("")
    lines.append(CAVEAT)
    return "\n".join(lines)


def render_board_html_email(
    board: dict, cta_base_url: str = "", map_urls: dict[str, str] | None = None
) -> str:
    if map_urls is None:
        map_urls = chamber_map_urls(str(board.get("date") or ""))
    def esc(value: object) -> str:
        return html.escape(str(value))

    movers = top_movers(board, 3)
    spotlight = board.get("spotlight") or select_spotlight(board)
    # A mover carries a race_id; the "closest tossup" fallback does not.
    lead_is_mover = bool(spotlight and spotlight.get("race_id"))
    rest = [mover for mover in movers if mover.get("race_id") != (spotlight or {}).get("race_id")]
    if rest:
        rest_items = "".join(
            f'<li style="margin:0 0 6px"><strong>{esc(m["label"])}</strong> '
            f'{esc(m["from_band"])} &rarr; {esc(m["to_band"])}</li>'
            for m in rest
        )
        rest_html = (
            '<p style="margin:12px 0 4px;color:#6b6157;font-size:13px">Also moved</p>'
            f'<ul style="padding-left:18px;margin:0">{rest_items}</ul>'
        )
    elif movers:
        rest_html = ""
    else:
        rest_html = '<p style="margin:0;color:#6b6157">No rating bands moved since the prior edition.</p>'
    heading_html = "Moved on the board" if lead_is_mover else "Spotlight"

    chamber_bars_html = render_chamber_bars(board, map_urls)

    spotlight = board.get("spotlight") or select_spotlight(board)
    if spotlight:
        candidate_html = "".join(
            f'<li>{esc(c["name"])} ({esc(c["party"] or "—")}): '
            f'{_money(c.get("ie_support_7d"))} outside support, '
            f'{_money(c.get("ie_oppose_7d"))} opposed</li>'
            for c in spotlight.get("candidates", [])[:4]
        )
        evidence_html = "".join(
            f'<li><a href="{esc(e["url"])}" style="color:#123c74">{esc(e["title"])}</a> '
            f'<span style="color:#6b6157">{esc(e["source_name"])}</span></li>'
            for e in spotlight.get("evidence", [])[:3]
        )
        reason = (
            f" on {esc(spotlight['top_issue'].replace('_', ' '))} coverage"
            if spotlight.get("top_issue") else ""
        )
        money_html = ""
        if spotlight.get("dem_money") is not None or spotlight.get("rep_money") is not None:
            dem_money = _money(spotlight.get("dem_money")) if spotlight.get("dem_money") else "none reported"
            rep_money = _money(spotlight.get("rep_money")) if spotlight.get("rep_money") else "none reported"
            money_html = (
                '<p style="margin:0 0 8px;color:#6b6157">Money (outside spending reported to the FEC): '
                f'{dem_money} favoring Democrats · '
                f'{rep_money} favoring Republicans.</p>'
            )
        spotlight_html = (
            f'<p style="margin:0 0 4px;font-weight:700;font-size:16px">{esc(spotlight["label"])} ({esc(spotlight["to_band"])})</p>'
            f'<p style="margin:0 0 8px;color:#16130f">{esc(spotlight["from_band"])} &rarr; {esc(spotlight["to_band"])}, '
            f'{esc(_direction_phrase(spotlight.get("toward", "")))}{reason}.</p>'
            f'{money_html}'
            f'<ul style="padding-left:18px;margin:0 0 8px">{candidate_html}</ul>'
            f'<ul style="padding-left:18px;margin:0 0 8px">{evidence_html}</ul>'
            f'<p style="margin:0"><a href="{esc(board_url(cta_base_url, spotlight.get("slug")))}" '
            'style="color:#123c74">Open the race page</a></p>'
        )
    else:
        spotlight_html = ""

    return f"""<!DOCTYPE html>
<html lang="en"><body style="margin:0;background:#faf7f1;font-family:Helvetica,Arial,sans-serif">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#faf7f1">
    <tr><td align="center">
      <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%">
        <tr><td style="padding:20px 24px 4px;border-bottom:3px solid #16130f">
          <span style="font-size:13px;letter-spacing:2px;color:#6b6157">NEWSCLOUD RACE BOARD</span>
          <div style="font-size:22px;font-weight:700;color:#16130f">{esc(board["date"])}</div>
        </td></tr>
        <tr><td style="padding:18px 24px 0;font-size:18px;line-height:1.4;color:#16130f">{esc(board["lead"])}</td></tr>
        <tr><td style="padding:14px 24px 0">{chamber_bars_html}</td></tr>
        <tr><td style="padding:14px 24px 0"><h2 style="font-size:15px;text-transform:uppercase;letter-spacing:1px;color:#6b6157;margin:0 0 8px">{heading_html}</h2>{spotlight_html}{rest_html}</td></tr>
        <tr><td style="padding:18px 24px 0">
          <a href="{esc(board_url(cta_base_url))}" style="display:inline-block;background:#16130f;color:#faf7f1;padding:12px 20px;text-decoration:none;font-weight:700">Open the full board</a>
        </td></tr>
        <tr><td style="padding:20px 24px;border-top:1px solid #d9d2c6;color:#6b6157;font-size:12px">{esc(CAVEAT)}</td></tr>
      </table>
    </td></tr>
  </table>
</body></html>
"""


def store_artifact(
    *, base_url: str, service_key: str, run_date: str, fmt: str, content: str
) -> dict:
    content_bytes = (content.rstrip() + "\n").encode("utf-8")
    storage_path = f"{BOARD_EMAIL_ARTIFACT_TYPE}/{BOARD_EMAIL_REGION}/{run_date}.{fmt}"
    content_hash = hashlib.sha256(content_bytes).hexdigest()
    content_type = "text/html; charset=utf-8" if fmt == "html" else "text/plain; charset=utf-8"

    if storage_provider() == "r2":
        put_r2_bytes(
            bucket_role=ARTIFACT_BUCKET, key=storage_path,
            body=content_bytes, content_type=content_type,
        )
    else:
        SupabaseRest(base_url, service_key).upload_object(
            ARTIFACT_BUCKET, storage_path, content_bytes,
            content_type=content_type, timeout=60,
        )

    payload = {
        "run_date": run_date,
        "region": BOARD_EMAIL_REGION,
        "artifact_type": BOARD_EMAIL_ARTIFACT_TYPE,
        "format": fmt,
        "storage_bucket": ARTIFACT_BUCKET,
        "storage_path": storage_path,
        "content_hash": content_hash,
        "template_version": BOARD_EMAIL_TEMPLATE_VERSION,
        "audience": None,
        "metadata": {"channel": "email", "shadow": True},
    }
    SupabaseRest(base_url, service_key).upsert(
        "artifacts",
        payload,
        on_conflict="run_date,region,artifact_type,format",
        timeout=60,
    )
    return payload


def generate_board_email_artifacts(
    *,
    run_date: str,
    cta_base_url: str = "",
    output_dir: Path | None = None,
    store_supabase: bool = False,
    supabase_base_url: str | None = None,
    supabase_service_key: str | None = None,
) -> dict:
    base_url, service_key = supabase_base_url or "", supabase_service_key or ""
    if not base_url or not service_key:
        base_url, service_key = require_env()

    board = load_board(run_date, base_url, service_key)
    spotlight = select_spotlight(board)
    if spotlight and spotlight.get("state"):
        spotlight.update(load_spotlight_enrichment(base_url, service_key, run_date, spotlight))
    board["spotlight"] = spotlight

    html_content = render_board_html_email(board, cta_base_url)
    text_content = render_board_text_email(board, cta_base_url)

    violations = check_prohibited_language(html_content + "\n" + text_content)
    if violations:
        raise SystemExit(f"Prohibited language found in board email: {violations}")

    stored = []
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{run_date}-board.html").write_text(
            html_content.rstrip() + "\n", encoding="utf-8"
        )
        (output_dir / f"{run_date}-board.txt").write_text(
            text_content.rstrip() + "\n", encoding="utf-8"
        )

    if store_supabase:
        for fmt, content in (("html", html_content), ("txt", text_content)):
            stored.append(store_artifact(
                base_url=base_url, service_key=service_key,
                run_date=run_date, fmt=fmt, content=content,
            ))

    return {
        "run_date": run_date,
        "subject": board.get("subject") or f"Race Board — {run_date}",
        "stored_artifacts": stored,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--brief-url-base", default="")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--store-supabase", action="store_true")
    args = parser.parse_args()

    result = generate_board_email_artifacts(
        run_date=args.date,
        cta_base_url=args.brief_url_base,
        output_dir=args.output_dir,
        store_supabase=args.store_supabase,
    )
    print(json.dumps({
        "run_date": result["run_date"],
        "subject": result["subject"],
        "stored_artifacts": len(result["stored_artifacts"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
