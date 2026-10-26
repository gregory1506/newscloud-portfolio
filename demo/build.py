"""Build local sample artifacts using production-derived rating/export/render code.

No fetch, storage, credential, map or send entry point is called. Only the preview
presentation and its URLs are adapted; the production numeric results are kept.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from scripts.export_race_board_data import (
    BAND_ORDER,
    CHAMBER_LABELS,
    CHAMBERS,
    build_board_payload,
    public_race_detail,
)
from scripts.generate_board_email import (
    render_board_html_email,
    render_board_text_email,
    select_spotlight,
)
from shared.coverage_rating import BAND_COLORS, rate_race

PACKAGE = Path(__file__).resolve().parent
PREVIEW_ORIGIN = "https://demo.invalid"
NOTICE = "SYNTHETIC SAMPLE · NOT AN ELECTION FORECAST"
SCOPE = (
    "This local demonstration calls the production-derived deterministic rating, "
    "board export, race-detail sanitizer and HTML/plain-text email renderers. "
    "It does not run news collection, article classification, ingestion, databases, "
    "cloud orchestration, quota controls, authentication or email delivery. "
    "The prior and current editions are calculated from authored numeric inputs, "
    "not observed news or election results. No predictive validity is implied."
)


OUTPUT_MARKER = ".newscloud-demo-output"
OUTPUT_SIGNATURE = "NewsCloud synthetic offline demo output v1\n"


def write_artifacts(output: Path, artifacts: dict[str, str]) -> None:
    """Reuse only our own output tree; never overwrite unrelated or linked files."""
    resolved = output.resolve()
    source_root = PACKAGE.parent
    protected = ("demo", "shared", "scripts", "tests", "docs", "reference", "tools", ".git", ".github")
    if resolved == source_root or resolved in source_root.parents or any(
        resolved == source_root / name or source_root / name in resolved.parents
        for name in protected
    ):
        raise ValueError("Choose a dedicated output directory, not source or documentation paths.")
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("Output paths must not traverse symlinks.")
    for relative in artifacts:
        target = output / relative
        if Path(relative).is_absolute() or not target.resolve().is_relative_to(resolved):
            raise ValueError("Artifact paths must remain inside the output directory.")
    marker = output / OUTPUT_MARKER
    if output.exists():
        if not output.is_dir():
            raise ValueError("Output must be a directory.")
        existing = list(output.rglob("*"))
        if any(path.is_symlink() for path in existing):
            raise ValueError("Output tree contains a symlink; choose a new directory.")
        if any(output.iterdir()) and (
            not marker.is_file() or marker.read_text(encoding="utf-8") != OUTPUT_SIGNATURE
        ):
            raise ValueError("Refusing a nonempty directory not owned by this demo.")
        allowed = set(artifacts) | {OUTPUT_MARKER}
        if any(path.is_file() and path.relative_to(output).as_posix() not in allowed for path in existing):
            raise ValueError("Output contains unrelated or stale files; choose a new directory.")
    output.mkdir(parents=True, exist_ok=True)
    marker.write_text(OUTPUT_SIGNATURE, encoding="utf-8")
    for relative, content in artifacts.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def load_fixtures() -> dict:
    return json.loads((PACKAGE / "fixtures.json").read_text(encoding="utf-8"))


def _snapshot(race: dict, inputs: dict) -> tuple[dict, dict]:
    result = rate_race(**inputs, incumbent_party=race["incumbent_party"]).as_dict()
    return {
        "race_id": race["race_id"],
        "rating_score": result["rating_score"],
        "rating_band": result["rating_band"],
        "rating_confidence": result["confidence"],
        "coverage_leaning": inputs["leaning_score"],
        "coverage_tone": None,
        "source_count": inputs["source_count"],
        "dem_money": inputs["dem_money"],
        "rep_money": inputs["rep_money"],
        "fec_coverage": inputs["fec_coverage"],
        "issue_mix": race["issue_mix"],
        "methodology_version": result["methodology_version"],
    }, result


def assemble(fixtures: dict) -> tuple[dict, dict, dict[str, dict]]:
    """Rate both editions and pass their actual results to the public exporter."""
    races = fixtures["races"]
    current, previous, calculations = {}, {}, {}
    for race in races:
        race_id = race["race_id"]
        current[race_id], now = _snapshot(race, race["inputs"])
        previous[race_id], before = _snapshot(race, race.get("prior_inputs", race["inputs"]))
        calculations[race_id] = {"current": now, "prior": before}

    prior = build_board_payload(
        run_date=fixtures["prior_date"], races=races,
        snapshots_by_race=previous, prior_bands={},
    )
    board = build_board_payload(
        run_date=fixtures["date"], races=races, snapshots_by_race=current,
        prior_bands={race_id: row["rating_band"] for race_id, row in previous.items()},
    )
    for payload in (board, prior):
        payload["demo"] = {
            "synthetic": True, "notice": fixtures["notice"], "scope": SCOPE,
            "prior_date": fixtures["prior_date"],
            "comparison": "Two authored editions; not the live three-edition selection/orchestration path.",
        }

    details = {}
    for race in races:
        evidence = [
            {"title": item["title"], "source_name": item["source_name"],
             "url": f'{PREVIEW_ORIGIN}/evidence/{item["id"]}.html'}
            for item in race["evidence"]
        ]
        detail = public_race_detail(
            race, current[race["race_id"]], race["candidates"], evidence,
        )
        # The production sanitizer accepts absolute HTTP(S) evidence URLs. Supply
        # reserved .invalid identifiers, then localize only the sanitized URLs.
        for item in detail["evidence"]:
            item["url"] = item["url"].removeprefix(PREVIEW_ORIGIN + "/")
        detail["demo"] = {
            "synthetic": True, "scenario": race["scenario"],
            "inputs": race["inputs"],
            "prior_inputs": race.get("prior_inputs", race["inputs"]),
            "calculations": calculations[race["race_id"]],
            "prior_date": fixtures["prior_date"], "date": fixtures["date"],
        }
        details[detail["slug"]] = detail

    spotlight = select_spotlight(board)
    if spotlight:
        detail = details[spotlight["slug"]]
        board["spotlight"] = {
            **spotlight, "candidates": detail["candidates"], "evidence": detail["evidence"],
        }
    return board, prior, details


def signal_label(row: dict) -> str:
    if row["has_signal"]:
        return "Thin · monitored" if row["thin_signal"] else "Monitored"
    if not row.get("source_count") and not row.get("fec_coverage"):
        return "No inputs"
    return "Below monitoring threshold"


def band(row: dict) -> str:
    if not row["has_signal"]:
        return '<span class="unrated">Not rated on board</span>'
    color = BAND_COLORS[row["rating_band"]]
    return f'<span class="band" style="--band:{color}">{esc(row["rating_band"])}</span>'


def shell(title: str, body: str, *, root: str = "") -> str:
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="A wholly synthetic, offline NewsCloud source demonstration. Not an election forecast.">
<title>{esc(title)} · NewsCloud sample</title><link rel="stylesheet" href="{root}style.css">
<link rel="icon" type="image/svg+xml" href="{root}favicon.svg">
</head><body><a class="skip" href="#main">Skip to content</a>
<div class="sample-banner">{NOTICE}</div>
<header class="site-header"><a class="wordmark" href="{root}index.html">NewsCloud<span> / source demonstration</span></a>
<nav aria-label="Preview formats"><a href="{root}index.html">Board</a><a href="{root}email.html">Email preview</a><a href="{root}board.json">JSON</a></nav></header>
<main id="main">{body}</main>
<footer><strong>Authored fiction. Real rendering code.</strong><p>{esc(SCOPE)}</p>
<p>EX and QZ are example identifiers, not states. D/R labels are inherited coverage-band vocabulary, not vote shares or win probabilities. No external assets, maps, fonts or scripts are loaded.</p></footer>
</body></html>\n'''


def render_index(board: dict, prior: dict, details: dict[str, dict]) -> str:
    monitored = sum(section["tally"]["monitored"] for section in board["chambers"].values())
    seats = sum(section["tally"]["seats"] for section in board["chambers"].values())
    movers = [move for section in board["chambers"].values() for move in section["changelog"]]
    links = "".join(f'<a href="#{chamber}">{CHAMBER_LABELS[chamber]}</a>' for chamber in CHAMBERS)
    sections = []
    for chamber in CHAMBERS:
        section = board["chambers"][chamber]
        tally = section["tally"]
        counts = "".join(
            f'<li><span class="dot" style="--band:{BAND_COLORS[name]}"></span>{esc(name)} <strong>{count}</strong></li>'
            for name in BAND_ORDER if (count := tally["bands"][name])
        ) or '<li>No monitored bands</li>'
        rows = []
        for row in section["races"]:
            detail = details[row["slug"]]
            scenario = detail["demo"]["scenario"]
            money = "Present (synthetic)" if row["fec_coverage"] else "Missing"
            rows.append(f'''<tr><th scope="row"><a href="race/{row['slug']}/index.html">{esc(row['label'])}</a><small>{esc(scenario)}</small></th>
<td>{band(row)}</td><td>{esc(signal_label(row))}</td><td>{row['source_count']}</td><td>{money}</td></tr>''')
        sections.append(f'''<section class="chamber" id="{chamber}" aria-labelledby="{chamber}-title">
<div class="section-heading"><h2 id="{chamber}-title">{CHAMBER_LABELS[chamber]}</h2><span>{tally['monitored']} of {tally['seats']} sample seats monitored</span></div>
<p>{esc(section['read'])}</p><ul class="counts" aria-label="Monitored band counts">{counts}</ul>
<div class="table-scroll"><table><caption>{CHAMBER_LABELS[chamber]} sample inputs and coverage bands</caption>
<thead><tr><th scope="col">Example seat / scenario</th><th scope="col">Coverage band</th><th scope="col">Input status</th><th scope="col">Sources</th><th scope="col">Finance input</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div></section>''')
    transitions = "".join(
        f'<li><a href="race/{m["slug"]}/index.html">{esc(m["label"])}</a>: '
        f'<strong>{esc(m["from_band"])} → {esc(m["to_band"])}</strong></li>' for m in movers
    )
    body = f'''<section class="hero"><div><p class="eyebrow">Offline edition / {board['date']}</p>
<h1>Coverage, with the<br>gaps left in.</h1>
<p class="intro">A small, fictional race board that makes the difference between a signal and a missing input visible.</p>
<p>Every name, headline and measurement below is authored sample data. This is a demonstration of software behavior, not reporting about an election.</p></div>
<aside class="edition"><p class="eyebrow">This sample edition</p><div class="metrics"><div><strong>{seats}</strong><span>example seats</span></div><div><strong>{monitored}</strong><span>monitored inputs</span></div><div><strong>{len(movers)}</strong><span>band transition</span></div></div>
<p class="edition-note">Coverage bands describe these inputs. They do not predict winners.</p></aside></section>
<section class="change-note" aria-labelledby="change-title"><p class="eyebrow">Prior-edition comparison</p><h2 id="change-title">A calculated change, not a scripted label</h2>
<p>{esc(board['lead'])}</p><ul>{transitions}</ul>
<p>Both {prior['date']} and {board['date']} pass through the same production rating function. This compares two authored editions; it does not simulate live history selection or three-edition orchestration.</p>
<a href="prior-board.json">Prior board JSON</a> · <a href="fixtures.json">Authored inputs</a></section>
<nav class="chamber-nav" aria-label="Jump to chamber">{links}</nav>
{''.join(sections)}
<section class="reading-guide" aria-labelledby="guide-title"><h2 id="guide-title">Read the inputs before the band</h2><div class="guide-grid">
<div><h3>Monitored</h3><p>The exporter includes a seat when it has at least two coverage sources or a positive finance-coverage input. Finance-only monitoring is possible.</p></div>
<div><h3>Thin, not empty</h3><p>Production confidence below 0.5 is marked thin. Our two-source House example is monitored but thin: it lacks finance and incumbency inputs. Confidence is input completeness, not electoral certainty.</p></div>
<div><h3>No inputs ≠ Tossup</h3><p>Missing coverage and finance are excluded from monitored band counts. The raw calculator's neutral fallback remains in JSON for transparency; the board does not portray it as a close race. One source is also excluded, but is labelled separately.</p></div></div></section>
<section class="formats"><div><h2>Same edition. Another surface.</h2><p>The production email renderer receives this board, with local links and no maps. Nothing is sent.</p></div><div><a class="button" href="email.html">Open email preview</a><a href="email.txt">Plain-text email</a></div></section>'''
    return shell("Offline coverage board", body)


def render_detail(detail: dict) -> str:
    sample = detail["demo"]
    calculations = sample["calculations"]
    comparisons = "".join(
        f'<tr><th scope="row">{label}</th><td>{esc(calculations["prior"][key])}</td><td>{esc(calculations["current"][key])}</td></tr>'
        for label, key in (("Raw rating score (0–100)", "rating_score"), ("Raw rating band", "rating_band"), ("Input confidence (0–1)", "confidence"))
    )
    candidates = "".join(
        f'<li><strong>{esc(candidate["name"])}</strong> · {esc(candidate["party"])}</li>'
        for candidate in detail["candidates"]
    ) or '<li>No candidate fixture supplied.</li>'
    evidence = "".join(
        f'<li><a href="../../{esc(item["url"])}">{esc(item["title"])}</a><small>{esc(item["source_name"])}</small></li>'
        for item in detail["evidence"]
    ) or '<li>No coverage evidence supplied. Missing is not neutral reporting.</li>'
    body = f'''<p class="breadcrumb"><a href="../../index.html#{detail['chamber']}">← Back to {CHAMBER_LABELS[detail['chamber']]}</a></p>
<section class="detail-heading"><p class="eyebrow">Fictional example / {CHAMBER_LABELS[detail['chamber']]}</p><h1>{esc(detail['label'])}</h1>
<p class="intro">{esc(sample['scenario'])}</p><p>{band(detail)} <span class="status">{esc(signal_label(detail))}</span></p></section>
<section class="reading-guide"><h2>What this detail shows</h2><p>Production <code>public_race_detail</code> sanitizes the candidates and evidence below. The calculator's unmodified numeric outputs are exposed for inspection, including neutral fallbacks for missing inputs. An unmonitored raw band is not displayed as a rated seat on the board.</p>
<p>All money is invented. The email renderer's inherited “reported to the FEC” wording describes a production field; no FEC filing is represented by this sample.</p></section>
<section class="chamber"><h2>Two editions, one calculation</h2><div class="table-scroll"><table><caption>Actual outputs of rate_race on the authored inputs</caption><thead><tr><th scope="col">Output</th><th scope="col">{sample['prior_date']}</th><th scope="col">{sample['date']}</th></tr></thead><tbody>{comparisons}</tbody></table></div>
<p>The 0–100 score is a coverage/finance/incumbency index, not a vote share. Confidence is not a probability of winning.</p>
<details><summary>Inspect inputs, components and weights</summary><pre>{esc(dump(sample))}</pre></details><p><a href="detail.json">Download detail JSON</a></p></section>
<div class="detail-grid"><section><h2>Fictional candidates</h2><ul class="evidence">{candidates}</ul></section><section><h2>Authored evidence</h2><ul class="evidence">{evidence}</ul></section></div>'''
    return shell(f'{detail["label"]} detail', body, root="../../")


def render_evidence(item: dict, slug: str) -> str:
    body = f'''<p class="breadcrumb"><a href="../race/{slug}/index.html">← Back to example race</a></p>
<article class="evidence-page"><p class="eyebrow">Authored fixture / not a news article</p><h1>{esc(item['title'])}</h1><p class="intro">{esc(item['source_name'])} · fictional source</p><p>{esc(item['text'])}</p>
<p>This text is included only as local evidence-page content. Numeric inputs in <a href="../fixtures.json">fixtures.json</a> are supplied directly; the demo does not infer scores from these words.</p></article>'''
    return shell("Synthetic evidence", body, root="../")


def render_emails(board: dict) -> tuple[str, str]:
    """Use production renderers; adapt links and prepend an explicit sample label."""
    rendered_html = render_board_html_email(board, cta_base_url=PREVIEW_ORIGIN, map_urls={})
    rendered_text = render_board_text_email(board, cta_base_url=PREVIEW_ORIGIN, map_urls={})
    # Explicit index files work both on file:// and a plain static HTTP server.
    for section in board["chambers"].values():
        for race in section["races"]:
            remote = f'{PREVIEW_ORIGIN}/race/{race["slug"]}/'
            local = f'race/{race["slug"]}/index.html'
            rendered_html = rendered_html.replace(remote, local)
            rendered_text = rendered_text.replace(remote, local)
    rendered_html = rendered_html.replace(PREVIEW_ORIGIN + "/", "index.html")
    rendered_text = rendered_text.replace(PREVIEW_ORIGIN + "/", "index.html")
    note = (
        "All names, sources, headlines, money and measurements are fictional. "
        "EX/QZ are example identifiers. No messages are sent. Maps are omitted; "
        "production distribution bars are retained. The renderer's FEC wording "
        "describes its production fields, not actual filings in this sample. "
        "This is not an election forecast."
    )
    banner = f'''<section aria-label="Synthetic preview notice" style="max-width:552px;margin:16px auto;padding:20px;background:#e7f1ed;color:#153b33;font-family:Arial,sans-serif;line-height:1.5">
<h1 style="font-size:18px;margin:0">{NOTICE}</h1><p>{esc(note)}</p><p>{esc(SCOPE)}</p>
<a href="index.html">Back to sample board</a> · <a href="email.txt">Plain-text preview</a></section>'''
    rendered_html = rendered_html.replace(
        '<html lang="en">', '<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="icon" type="image/svg+xml" href="favicon.svg"><title>Synthetic email preview · NewsCloud</title></head>', 1,
    ).replace('<table role="presentation"', banner + '\n<table role="presentation"', 1)
    return rendered_html.rstrip() + "\n", f"{NOTICE}\n{note}\n\n{SCOPE}\n\n{rendered_text.rstrip()}\n"


def build(output: str | Path = "demo-output") -> Path:
    """Write deterministic artifacts to a dedicated, build-owned directory."""
    output = Path(output)
    fixtures = load_fixtures()
    board, prior, details = assemble(fixtures)
    artifacts = {
        "style.css": (PACKAGE / "style.css").read_text(encoding="utf-8"),
        "favicon.svg": (PACKAGE / "favicon.svg").read_text(encoding="utf-8"),
        "fixtures.json": dump(fixtures),
        "board.json": dump(board),
        "prior-board.json": dump(prior),
        "index.html": render_index(board, prior, details),
    }
    for detail in details.values():
        artifacts[f'race/{detail["slug"]}/index.html'] = render_detail(detail)
        artifacts[f'race/{detail["slug"]}/detail.json'] = dump(detail)
    by_id = {detail["race_id"]: detail for detail in details.values()}
    for race in fixtures["races"]:
        for item in race["evidence"]:
            artifacts[f'evidence/{item["id"]}.html'] = render_evidence(item, by_id[race["race_id"]]["slug"])
    artifacts["email.html"], artifacts["email.txt"] = render_emails(board)
    write_artifacts(output, artifacts)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("demo-output"), help="Dedicated artifact directory (default: demo-output)")
    args = parser.parse_args()
    output = build(args.output)
    print(f"Built synthetic offline preview: {output / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
