#!/usr/bin/env python3
"""Measure current-month GCP usage against the internal free-tier thresholds.

Phase 3 of ``docs/research/2026-09-26-free-tier-hardening-plan.md``: track real
usage monthly and warn at 80 % of the relevant free allowance instead of
discovering an overage on the invoice.

Machine-readable surfaces (Cloud Monitoring, the Artifact Registry / Secret
Manager APIs, and the Supabase Management API) are measured. Surfaces that need
a vendor console are printed as manual checks so one command covers the whole
monthly review. Supabase rows fall back to a manual check with the reason when
the access token is unavailable.

Usage:
  python3 scripts/free_tier_report.py
  python3 scripts/free_tier_report.py --days 30 --json /tmp/free-tier.json

Exit status is 1 when any measured surface is above its threshold share.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.gcp_api import CLOUD_SCOPE, MONITORING_SCOPE, access_token
from shared.gcp_api import get_json as _get
from shared.gcp_api import paginate as _paginate_items
from shared.gcp_env import get_project_id

ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS_PATH = ROOT / "config" / "free_tier_thresholds.json"

# DELTA metrics are summed across the window; never sum a GAUGE metric.
MONITORED_SURFACES = (
    ("cloud_run_requests", "run.googleapis.com/request_count"),
    ("cloud_run_cpu_seconds", "run.googleapis.com/container/cpu/allocation_time"),
    ("cloud_run_memory_gib_seconds", "run.googleapis.com/container/memory/allocation_time"),
    ("pubsub_bytes", "pubsub.googleapis.com/topic/byte_cost"),
    ("logging_bytes", "logging.googleapis.com/billing/bytes_ingested"),
)
# Surfaces no API can measure, with the reason recorded so the monthly review says
# what would have to change rather than just "manual check".
MANUAL_REASONS = {
    "resend_monthly_emails": (
        "the Resend API key is send-only, so usage is not readable; "
        "a read-scoped key would allow measuring it"
    ),
}


class VendorUnavailable(RuntimeError):
    """A vendor surface cannot be measured here; the report prints the reason."""


R2_SURFACE = "r2_storage_bytes"
PAGES_SURFACE = "cloudflare_pages_builds"
R2_BUCKET_ROLES = ("newspics", "artifacts")
R2_DEFAULT_BUCKETS = {"newspics": "test-project-newspics", "artifacts": "test-project-artifacts"}
R2_ACCOUNT_ID = "test-project"
CLOUDFLARE_ACCOUNT_ID = "test-project"
# The 500/month allowance is account-level, and this account also hosts other
# tenants' projects, so the account total is what the allowance actually bounds.
CLOUDFLARE_NEWSCLOUD_PROJECTS = ("test-project-dashboard", "test-project-uk", "test-project-tt")
# The Pages deployments endpoint rejects per_page above 25 (error 8000024).
PAGES_DEPLOYMENTS_PER_PAGE = 25

# Supabase is a separate vendor on the same Google Cloud project. Its usage is
# read through the Management API with a personal access token.
SUPABASE_PROJECT_REF = "test-project"
SUPABASE_QUERY_URL = f"https://api.supabase.com/v1/projects/{SUPABASE_PROJECT_REF}/database/query"
SUPABASE_TOKEN_SECRET = "test-project-cli-token"
SUPABASE_TOKEN_PROJECT = "test-project"
SUPABASE_STORAGE_SURFACE = "supabase_storage_bytes"
SUPABASE_DATABASE_SURFACE = "supabase_database_bytes"
SUPABASE_STORAGE_SQL = (
    "select count(*) as objects, "
    "coalesce(sum((metadata->>'size')::bigint), 0) as bytes from storage.objects"
)
SUPABASE_DATABASE_SQL = "select pg_database_size(current_database()) as bytes"
# Supabase reported 1.11 GB for 1,134,657,022 bytes: decimal GB, not GiB.
BYTES_PER_GB = 1_000_000_000


class SupabaseUnavailable(RuntimeError):
    """The Supabase Management API or its access token could not be used."""


def human_bytes(value: float) -> str:
    """Format a byte count with decimal units, as Supabase reports them."""
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{int(size)} B" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1000
    return f"{size:.2f} TB"


@dataclass
class Surface:
    name: str
    usage: float
    allowance: float
    measured: bool
    reason: str | None = None
    note: str | None = None
    human: bool = False

    @property
    def share(self) -> float:
        return self.usage / self.allowance if self.allowance else 0.0

    def usage_text(self) -> str:
        if not self.measured:
            return f"manual check ({self.reason})" if self.reason else "manual check"
        return human_bytes(self.usage) if self.human else f"{self.usage:,.0f}"

    def status(self, warn_share: float) -> str:
        if not self.measured:
            return "manual"
        if self.share > 1.0:
            return "OVER"
        return "warn" if self.share >= warn_share else "ok"


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def monitoring_total(
    metric: str,
    *,
    project: str,
    start: datetime,
    end: datetime,
    token: str,
) -> float:
    """Sum a DELTA metric over the window.

    The alignment period is capped at one day: a single period spanning the
    whole window makes Cloud Monitoring return extra points whose interval
    starts *before* ``start``, which inflates the total.
    """
    window_seconds = int((end - start).total_seconds())
    alignment_seconds = min(window_seconds, 86400)
    query = urllib.parse.urlencode(
        {
            "filter": f'metric.type="{metric}"',
            "interval.startTime": start.isoformat().replace("+00:00", "Z"),
            "interval.endTime": end.isoformat().replace("+00:00", "Z"),
            "aggregation.alignmentPeriod": f"{alignment_seconds}s",
            "aggregation.perSeriesAligner": "ALIGN_SUM",
            "aggregation.crossSeriesReducer": "REDUCE_SUM",
        }
    )
    payload = (
        _get(f"https://monitoring.googleapis.com/v3/projects/{project}/timeSeries?{query}", token) or {}
    )
    total = 0.0
    for series in payload.get("timeSeries", []):
        for point in series.get("points", []):
            value = point["value"]
            total += float(value.get("doubleValue") or value.get("int64Value") or 0)
    return total


def artifact_registry_bytes(project: str, token: str) -> float:
    """Sum repository sizes across every Artifact Registry location."""
    locations = _paginate_items(
        f"https://artifactregistry.googleapis.com/v1/projects/{project}/locations",
        token,
        item_key="locations",
    )
    total = 0
    for location in locations:
        url = f"https://artifactregistry.googleapis.com/v1/{location['name']}/repositories"
        for repository in _paginate_items(url, token, item_key="repositories"):
            total += int(repository.get("sizeBytes") or 0)
    return float(total)


def secret_manager_active_versions(project: str, token: str) -> float:
    secrets = _paginate_items(
        f"https://secretmanager.googleapis.com/v1/projects/{project}/secrets",
        token,
        item_key="secrets",
    )
    enabled = 0
    for secret in secrets:
        version_url = (
            f"https://secretmanager.googleapis.com/v1/{secret['name']}/versions"
            "?filter=state:ENABLED&fields=versions%2CnextPageToken"
        )
        enabled += len(_paginate_items(version_url, token, item_key="versions"))
    return float(enabled)


def supabase_access_token() -> str:
    """Resolve a Supabase Management API token, or raise ``SupabaseUnavailable``.

    Prefers ``SUPABASE_ACCESS_TOKEN`` so the report works without gcloud, then
    falls back to the ``test-project-cli-token`` Secret Manager entry.
    """
    token = os.environ.get("SUPABASE_ACCESS_TOKEN")
    if token:
        return token
    if shutil.which("gcloud") is None:
        raise SupabaseUnavailable("SUPABASE_ACCESS_TOKEN is unset and gcloud is not on PATH")
    try:
        result = subprocess.run(
            [
                "gcloud",
                "secrets",
                "versions",
                "access",
                "latest",
                f"--secret={SUPABASE_TOKEN_SECRET}",
                f"--project={SUPABASE_TOKEN_PROJECT}",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SupabaseUnavailable(
            f"SUPABASE_ACCESS_TOKEN is unset and gcloud secret read failed: {exc}"
        ) from exc
    resolved = result.stdout.strip()
    if not resolved:
        raise SupabaseUnavailable("SUPABASE_ACCESS_TOKEN is unset and the secret resolved empty")
    return resolved


def supabase_query(sql: str, *, token: str | None = None) -> Any:
    """Run one SQL statement through the Supabase Management API."""
    resolved = token or supabase_access_token()
    request = urllib.request.Request(
        SUPABASE_QUERY_URL,
        data=json.dumps({"query": sql}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {resolved}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise SupabaseUnavailable(f"Supabase Management API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SupabaseUnavailable(f"Supabase Management API unreachable: {exc.reason}") from exc
    return json.loads(payload) if payload else None


def _first_row(result: Any) -> dict[str, Any]:
    rows = result.get("result") if isinstance(result, dict) else result
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    raise SupabaseUnavailable(f"unexpected Supabase query payload: {result!r}")


def read_supabase_usage(*, query_fn: Callable[[str], Any] | None = None) -> dict[str, float]:
    """Read Storage object count/bytes and database size from the Management API.

    Raises ``SupabaseUnavailable`` when the token, network, or API is unusable so
    the caller can fall back to a manual check instead of crashing.
    """
    query = query_fn or supabase_query
    storage = _first_row(query(SUPABASE_STORAGE_SQL))
    database = _first_row(query(SUPABASE_DATABASE_SQL))
    return {
        "storage_bytes": float(storage.get("bytes") or 0),
        "storage_objects": float(storage.get("objects") or 0),
        "database_bytes": float(database.get("bytes") or 0),
    }


def secret_value(env_name: str, secret_name: str) -> str:
    """A vendor credential from the environment, else Secret Manager via gcloud."""
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    if shutil.which("gcloud") is None:
        raise VendorUnavailable(f"{env_name} is unset and gcloud is not on PATH")
    completed = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            "--secret",
            secret_name,
            "--project",
            get_project_id(),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.returncode != 0:
        raise VendorUnavailable(f"{env_name} is unset and reading {secret_name} failed")
    return completed.stdout.strip()


def read_r2_usage() -> dict[str, float]:
    """R2 object counts and bytes, measured rather than assumed.

    The credentials are the publisher's; they come from the environment or Secret
    Manager, so the monthly review needs no console visit.
    """
    os.environ["R2_ACCESS_KEY_ID"] = secret_value(
        "R2_ACCESS_KEY_ID", "test-project-r2-access-key-id"
    )
    os.environ["R2_SECRET_ACCESS_KEY"] = secret_value(
        "R2_SECRET_ACCESS_KEY", "test-project-r2-secret-access-key"
    )
    if not os.environ.get("R2_ENDPOINT"):
        os.environ["R2_ENDPOINT"] = f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
    for role, bucket in R2_DEFAULT_BUCKETS.items():
        if not os.environ.get(f"R2_{role.upper()}_BUCKET"):
            os.environ[f"R2_{role.upper()}_BUCKET"] = bucket
    try:
        from scripts.r2_object_store import bucket_usage
    except Exception as exc:  # boto3 absent, etc.
        raise VendorUnavailable(f"R2 client unavailable: {exc}") from exc
    objects = 0
    total = 0
    for role in R2_BUCKET_ROLES:
        count, size = bucket_usage(role)
        objects += count
        total += size
    return {"storage_bytes": float(total), "storage_objects": float(objects)}


def read_pages_builds(*, now: datetime | None = None) -> dict[str, float]:
    """This calendar month's Cloudflare Pages deployments for the whole account.

    Reported as the account total plus the NewsCloud share, because the allowance is
    shared with projects that are not NewsCloud's.
    """
    token = secret_value("CLOUDFLARE_API_TOKEN", "test-project-cloudflare-api-token")
    moment = now or datetime.now(timezone.utc)
    month_start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    base = (
        f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}"
        "/pages/projects"
    )
    total = 0
    own = 0
    for project in _get(base, token).get("result", []):
        name = project["name"]
        page = 1
        while True:
            payload = _get(
                f"{base}/{name}/deployments"
                f"?per_page={PAGES_DEPLOYMENTS_PER_PAGE}&page={page}",
                token,
            )
            deployments = payload.get("result", [])
            in_month = 0
            for deployment in deployments:
                created = deployment.get("created_on") or ""
                try:
                    when = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if when >= month_start:
                    in_month += 1
            total += in_month
            if name in CLOUDFLARE_NEWSCLOUD_PROJECTS:
                own += in_month
            # Newest first: a page that reaches out of the month ends the walk.
            if len(deployments) < PAGES_DEPLOYMENTS_PER_PAGE or in_month < len(deployments):
                break
            page += 1
    return {"builds": float(total), "newscloud_builds": float(own)}


def vendor_surfaces(
    allowances: dict[str, Any],
    r2_usage_fn: Callable[[], dict[str, float]],
    pages_usage_fn: Callable[[], dict[str, float]],
) -> list[Surface]:
    """R2 and Pages rows: measured when the vendor answers, manual when it cannot."""
    rows: list[Surface] = []
    definitions = (
        (R2_SURFACE, r2_usage_fn, "storage_bytes", "storage_objects", "objects", True),
        (
            PAGES_SURFACE,
            pages_usage_fn,
            "builds",
            "newscloud_builds",
            "NewsCloud deployments",
            False,
        ),
    )
    for name, usage_fn, usage_key, note_key, note_label, human in definitions:
        if name not in allowances:
            continue
        try:
            usage = usage_fn()
        except Exception as exc:
            # A vendor API error must degrade the row, not kill the whole monthly
            # review: the report's contract is that one command covers every surface.
            rows.append(
                Surface(
                    name=name,
                    usage=0.0,
                    allowance=float(allowances[name]),
                    measured=False,
                    reason=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        note = f"{usage[note_key]:,.0f} {note_label}" if note_key in usage else None
        rows.append(
            Surface(
                name=name,
                usage=usage.get(usage_key, 0.0),
                allowance=float(allowances[name]),
                measured=True,
                note=note,
                human=human,
            )
        )
    return rows


def build_report(
    *,
    project: str,
    thresholds: dict[str, Any],
    start: datetime,
    end: datetime,
    monitoring_token: str,
    cloud_token: str,
    monitoring_total_fn: Callable[..., float] = monitoring_total,
    artifact_registry_fn: Callable[[str, str], float] = artifact_registry_bytes,
    secret_manager_fn: Callable[[str, str], float] = secret_manager_active_versions,
    supabase_usage_fn: Callable[[], dict[str, float]] = read_supabase_usage,
    r2_usage_fn: Callable[[], dict[str, float]] = read_r2_usage,
    pages_usage_fn: Callable[[], dict[str, float]] = read_pages_builds,
) -> dict[str, Any]:
    allowances = thresholds["allowances"]
    surfaces: list[Surface] = []
    for name, metric in MONITORED_SURFACES:
        surfaces.append(
            Surface(
                name=name,
                usage=monitoring_total_fn(
                    metric, project=project, start=start, end=end, token=monitoring_token
                ),
                allowance=float(allowances[name]),
                measured=True,
            )
        )
    surfaces.append(
        Surface(
            name="artifact_registry_bytes",
            usage=artifact_registry_fn(project, cloud_token),
            allowance=float(allowances["artifact_registry_bytes"]),
            measured=True,
        )
    )
    surfaces.append(
        Surface(
            name="secret_manager_active_versions",
            usage=secret_manager_fn(project, cloud_token),
            allowance=float(allowances["secret_manager_active_versions"]),
            measured=True,
        )
    )
    try:
        supabase_usage = supabase_usage_fn()
        supabase_reason = None
    except SupabaseUnavailable as exc:
        supabase_usage = None
        supabase_reason = str(exc)
    supabase_surfaces = (
        (SUPABASE_STORAGE_SURFACE, "storage_bytes", "storage_objects"),
        (SUPABASE_DATABASE_SURFACE, "database_bytes", None),
    )
    for name, usage_key, object_key in supabase_surfaces:
        if name not in allowances:
            continue
        note = None
        if supabase_usage is not None:
            if object_key and object_key in supabase_usage:
                note = f"{supabase_usage[object_key]:,.0f} objects"
            surfaces.append(
                Surface(
                    name=name,
                    usage=supabase_usage.get(usage_key, 0.0),
                    allowance=float(allowances[name]),
                    measured=True,
                    note=note,
                    human=True,
                )
            )
        else:
            surfaces.append(
                Surface(
                    name=name,
                    usage=0.0,
                    allowance=float(allowances[name]),
                    measured=False,
                    reason=supabase_reason,
                    human=True,
                )
            )
    surfaces.extend(vendor_surfaces(allowances, r2_usage_fn, pages_usage_fn))
    for name, reason in MANUAL_REASONS.items():
        if name in allowances and not any(surface.name == name for surface in surfaces):
            surfaces.append(
                Surface(
                    name=name,
                    usage=0.0,
                    allowance=float(allowances[name]),
                    measured=False,
                    reason=reason,
                )
            )
    return {
        "project": project,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "warn_share": thresholds["warn_share"],
        "surfaces": surfaces,
    }


def render(report: dict[str, Any]) -> str:
    warn_share = report["warn_share"]
    lines = [
        f"free-tier report {report['project']} "
        f"{report['window_start'][:10]} → {report['window_end'][:10]}",
        f"{'surface':34} {'usage':>16} {'allowance':>16} {'used':>7}  status",
    ]
    for surface in report["surfaces"]:
        usage = surface.usage_text()
        share = "—" if not surface.measured else f"{surface.share * 100:.1f}%"
        note = f"  {surface.note}" if surface.note else ""
        lines.append(
            f"{surface.name:34} {usage:>16} {surface.allowance:>16,.0f} {share:>7}  "
            f"{surface.status(warn_share)}{note}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--project", default=None)
    parser.add_argument("--days", type=int, default=0, help="window length; 0 = calendar month to date")
    parser.add_argument("--thresholds", type=Path, default=THRESHOLDS_PATH)
    parser.add_argument("--json", type=Path, help="write the report as JSON")
    args = parser.parse_args()

    project = args.project or get_project_id()
    thresholds = load_thresholds(args.thresholds)
    end = datetime.now(timezone.utc)
    if args.days:
        start = end - timedelta(days=args.days)
    else:
        start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    report = build_report(
        project=project,
        thresholds=thresholds,
        start=start,
        end=end,
        monitoring_token=access_token(MONITORING_SCOPE),
        cloud_token=access_token(CLOUD_SCOPE),
    )
    print(render(report), flush=True)
    warn_share = report["warn_share"]
    payload = dict(
        report,
        surfaces=[
            {
                "name": surface.name,
                "usage": surface.usage,
                "allowance": surface.allowance,
                "measured": surface.measured,
                "share": surface.share,
                "status": surface.status(warn_share),
                "reason": surface.reason,
                "note": surface.note,
            }
            for surface in report["surfaces"]
        ],
    )
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"report={args.json}", flush=True)
    return 1 if any(
        surface["status"] in {"OVER", "warn"} for surface in payload["surfaces"]
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
