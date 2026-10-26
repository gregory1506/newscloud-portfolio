"""Renders the daily pipeline-health brief (subject + HTML + text) from
metrics.py's pure computations. No I/O."""
from __future__ import annotations

STAGE_LABELS = {"gatherer": "Gatherer", "scorer": "Scorer", "generator": "Generator"}


def _format_duration(duration_minutes: float | None) -> str:
    if duration_minutes is None:
        return "unknown"
    return f"{duration_minutes:.1f} min"


def _stage_lines(stage_completion: dict) -> list[str]:
    lines = []
    for stage, label in STAGE_LABELS.items():
        data = stage_completion.get(stage, {})
        lines.append(
            f"{label}: {data.get('completed', 0)}/{data.get('expected', 0)} completed "
            f"({data.get('attempts', 0)} attempts, {data.get('recovery_attempts', 0)} recoveries)"
        )
    return lines


def _issue_lines(stage_issues: list[dict]) -> list[str]:
    if not stage_issues:
        return ["No stage errors recorded."]
    return [f"{issue['region']} / {issue['stage']}: {issue['last_error']}" for issue in stage_issues]


def _gemini_line(gemini_usage: dict) -> str:
    by_status = gemini_usage.get("by_status", {})
    return (
        f"Gemini fallback used {gemini_usage.get('total', 0)} times "
        f"({by_status.get('success', 0)} success, {by_status.get('empty', 0)} empty, "
        f"{by_status.get('error', 0)} error)"
    )


def _legislative_line(legislative_coverage: dict) -> str:
    coverage_pct = legislative_coverage.get("coverage_fraction", 0.0) * 100
    return (
        f"Legislative signal coverage: {legislative_coverage.get('region_count', 0)}/"
        f"{legislative_coverage.get('expected_region_count', 0)} regions ({coverage_pct:.0f}%), "
        f"avg FEC coverage {legislative_coverage.get('avg_fec_coverage', 0.0):.2f}, "
        f"avg member coverage {legislative_coverage.get('avg_member_coverage', 0.0):.2f}"
    )


def _party_lines(party_status: dict) -> list[str]:
    lines = []
    for audience in ("democrat", "republican"):
        data = party_status.get(audience, {"status": "missing", "attempts": 0})
        lines.append(f"{audience.capitalize()} synthesis: {data['status']} ({data['attempts']} attempts)")
    return lines


def render_brief(
    *,
    run_date: str,
    status: str,
    duration_minutes: float | None,
    stage_completion: dict,
    stage_issues: list[dict],
    gemini_usage: dict,
    legislative_coverage: dict,
    party_status: dict,
) -> dict:
    subject = f"NewsCloud Performance Brief | {run_date}"

    stage_lines = _stage_lines(stage_completion)
    issue_lines = _issue_lines(stage_issues)
    gemini_line = _gemini_line(gemini_usage)
    legislative_line = _legislative_line(legislative_coverage)
    party_lines = _party_lines(party_status)
    duration_str = _format_duration(duration_minutes)

    text = "\n".join(
        [
            f"NewsCloud Performance Brief | {run_date}",
            f"Run status: {status} (duration: {duration_str})",
            "",
            "Stage completion:",
            *[f"  - {line}" for line in stage_lines],
            "",
            "Stage errors:",
            *[f"  - {line}" for line in issue_lines],
            "",
            gemini_line,
            legislative_line,
            "",
            "Party synthesis:",
            *[f"  - {line}" for line in party_lines],
        ]
    )

    def _li(items: list[str]) -> str:
        return "".join(f"<li>{item}</li>" for item in items)

    html = f"""\
<html>
  <body style="font-family: -apple-system, Helvetica, Arial, sans-serif; color: #1a1a1a;">
    <h2>NewsCloud Performance Brief | {run_date}</h2>
    <p><strong>Run status:</strong> {status} (duration: {duration_str})</p>
    <h3>Stage completion</h3>
    <ul>{_li(stage_lines)}</ul>
    <h3>Stage errors</h3>
    <ul>{_li(issue_lines)}</ul>
    <h3>Gemini fallback</h3>
    <p>{gemini_line}</p>
    <h3>Legislative signal coverage</h3>
    <p>{legislative_line}</p>
    <h3>Party synthesis</h3>
    <ul>{_li(party_lines)}</ul>
  </body>
</html>
"""

    return {"subject": subject, "html": html, "text": text}
