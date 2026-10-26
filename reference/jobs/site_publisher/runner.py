#!/usr/bin/env python3
"""Build and, after an explicit cutover, publish the three NewsCloud sites."""

from __future__ import annotations

from datetime import date
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
from typing import Callable

# Support the existing `python jobs/site_publisher/runner.py` entry point.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from google.auth.transport.requests import Request
from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage
from google.oauth2 import id_token
from supabase import Client, create_client
from shared.publication_hashes import hash_tree
from jobs.site_publisher.race_board import score_race_board as _score_race_board
from shared.env import require_env

ROOT = Path(__file__).resolve().parents[2]


TASK_NAME = "site_publisher"
PUBLISHER_VERSION = "v3"
VALID_MODES = {"shadow", "active"}
PAGES_PROJECTS = {
    "us": ("public-dashboard", "test-project-dashboard"),
    "tt": ("public-regions/tt", "test-project-tt"),
    "uk": ("public-regions/uk", "test-project-uk"),
}


def run_date_from_env() -> str:
    value = require_env("RUN_DATE")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid RUN_DATE: {value!r}") from exc
    return value


def publisher_mode() -> str:
    value = os.environ.get("SITE_PUBLISHER_MODE", "shadow").strip().lower()
    if value not in VALID_MODES:
        raise RuntimeError(f"Unsupported SITE_PUBLISHER_MODE: {value}")
    return value


def get_supabase() -> Client:
    return create_client(require_env("SUPABASE_URL"), require_env("SUPABASE_SECRET_KEY"))


def claim_task(db: Client, *, run_date: str, mode: str) -> tuple[str, str] | None:
    logical_key = f"{run_date}:{mode}:{PUBLISHER_VERSION}"
    response = db.rpc(
        "claim_scheduled_task",
        {"p_task_name": TASK_NAME, "p_logical_key": logical_key, "p_lease_seconds": 3600},
    ).execute()
    token = response.data
    if isinstance(token, list):
        token = token[0] if token else None
    return (logical_key, str(token)) if token else None


def finish_task(
    db: Client,
    *,
    logical_key: str,
    claim_token: str,
    status: str,
    details: dict,
    error: str | None = None,
) -> bool:
    response = db.rpc(
        "finish_scheduled_task",
        {
            "p_task_name": TASK_NAME,
            "p_logical_key": logical_key,
            "p_claim_token": claim_token,
            "p_status": status,
            "p_details": details,
            "p_error": error,
        },
    ).execute()
    return bool(response.data)


def execute(command: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def read_latest_date() -> str:
    """Return the newest published Race Board date from the exported board data."""
    payload = json.loads((ROOT / "docs/data/board/index.json").read_text(encoding="utf-8"))
    return str(payload["available_dates"][0])


def score_race_board(run_date: str) -> None:
    """Write this run's race snapshots before the board export reads them.

    Best-effort by design: the board export asserts that the exported date
    matches the run, so a scoring failure fails publication loudly rather than
    publishing a board built from yesterday's snapshots.
    """
    try:
        _score_race_board(run_date)
    except Exception as exc:
        print(json.dumps({
            "event": "race_board_scoring_skipped",
            "run_date": run_date,
            "error": str(exc),
        }, sort_keys=True))


def build_sites(run_date: str) -> dict[str, str]:
    execute([sys.executable, "scripts/export_site_data.py"])
    score_race_board(run_date)
    # The board export must precede the freshness check: the check reads the
    # board index, which this step writes. It is also what the bundle is built
    # from, so asserting on it asserts the product's date, not a side channel.
    execute([sys.executable, "scripts/export_race_board_data.py"])
    exported_date = read_latest_date()
    if exported_date != run_date:
        raise RuntimeError(f"board export latest date {exported_date} does not match {run_date}")
    execute([sys.executable, "scripts/validate_tt_phase0.py", "--format", "text"])
    execute([sys.executable, "scripts/build_regions_dashboard.py"])
    execute([sys.executable, "scripts/build_public_dashboard.py"])
    return {
        name: hash_tree(ROOT / directory)
        for name, (directory, _project) in PAGES_PROJECTS.items()
    }


def board_url_base() -> str:
    return os.environ.get("NEWSCLOUD_BOARD_URL", "https://dashboard.example.invalid/board")


def generate_board_email(run_date: str, *, store: bool) -> None:
    command = [
        sys.executable,
        "scripts/generate_board_email.py",
        "--date",
        run_date,
        "--brief-url-base",
        board_url_base(),
        "--output-dir",
        str(ROOT / "docs" / "email"),
    ]
    if store:
        command.append("--store-supabase")
    execute(command)


def dispatch_board_email(run_date: str) -> None:
    emailer_url = require_env("EMAILER_URL")
    env = os.environ.copy()
    env["EMAILER_ID_TOKEN"] = id_token.fetch_id_token(Request(), emailer_url)
    execute(
        [sys.executable, "scripts/dispatch_board_email_jobs.py", "--date", run_date, "--live"],
        env=env,
    )


def deploy_sites() -> None:
    require_env("CLOUDFLARE_API_TOKEN")
    require_env("CLOUDFLARE_ACCOUNT_ID")
    for directory, project in PAGES_PROJECTS.values():
        execute([
            "wrangler", "pages", "deploy", directory,
            f"--project-name={project}", "--branch=main", "--commit-dirty=true",
        ])


def verify_sites(run_date: str) -> None:
    execute([
        sys.executable, "scripts/verify_dashboard_deployment.py",
        "--base-url", "https://dashboard.example.invalid/",
        "--expected-date", run_date,
    ])
    for region, host in (("TT", "test-project-tt"), ("UK", "test-project-uk")):
        execute([
            sys.executable, "scripts/verify_regions_deployment.py",
            "--base-url", f"https://{host}.pages.dev/",
            "--expected-date", run_date, "--region", region, "--json",
        ])


def mark_published(run_date: str) -> None:
    claim_id = require_env("EXPORT_CLAIM_ID")
    execute([sys.executable, "scripts/mark_export_published.py", run_date, claim_id])


def upload_immutable(object_name: str, payload: bytes, *, content_type: str) -> str:
    bucket_name = require_env("PUBLICATION_SNAPSHOT_BUCKET")
    blob = storage.Client().bucket(bucket_name).blob(object_name)
    try:
        blob.upload_from_string(
            payload,
            content_type=content_type,
            if_generation_match=0,
        )
    except PreconditionFailed:
        # A retry may arrive after the immutable manifest was written but
        # before the task claim was completed. Treat the exact same manifest
        # as success; never overwrite conflicting evidence for a run.
        if blob.download_as_bytes() != payload:
            raise RuntimeError(
                f"immutable publication object conflict: gs://{bucket_name}/{object_name}"
            ) from None
    return f"gs://{bucket_name}/{object_name}"


def snapshot_files(run_date: str) -> list[Path]:
    candidates = [
        ROOT / "docs/data/index.json",
        ROOT / f"docs/data/{run_date}.json",
        ROOT / f"docs/data/source-quality/{run_date}.json",
        ROOT / "docs/data/board/index.json",
        ROOT / f"docs/data/board/{run_date}.json",
    ]
    missing = [path.relative_to(ROOT).as_posix() for path in candidates if not path.is_file()]
    if missing:
        raise RuntimeError(f"publication snapshot files missing: {', '.join(missing)}")
    optional = [
        ROOT / f"docs/email/{run_date}-board.html",
        ROOT / f"docs/email/{run_date}-board.txt",
    ]
    return candidates + [path for path in optional if path.is_file()]


def create_snapshot(run_date: str) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in snapshot_files(run_date):
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return output.getvalue()


def upload_snapshot(run_date: str, mode: str) -> tuple[str, str]:
    payload = create_snapshot(run_date)
    object_name = f"publication-snapshots/{run_date}/{mode}-{PUBLISHER_VERSION}.zip"
    uri = upload_immutable(object_name, payload, content_type="application/zip")
    return uri, hashlib.sha256(payload).hexdigest()


def upload_manifest(manifest: dict) -> str:
    object_name = (
        f"publication-manifests/{manifest['run_date']}/"
        f"{manifest['mode']}-{manifest['publisher_version']}.json"
    )
    payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    return upload_immutable(object_name, payload, content_type="application/json")


US_ATTENTION_UNTIL_ENV = "NEWSCLOUD_US_ATTENTION_UNTIL"
US_ATTENTION_ENGINE_ENV = "NEWSCLOUD_US_ATTENTION_ENGINE"


def run_us_attention_shadow(run_date: str) -> None:
    """Run the private U.S. attention shadow last, never letting it affect publication.

    The pilot's hard boundary is that a failure cannot block gathering, publication,
    or email, so this runs after ``mark_published`` and swallows its own errors into
    a log event. It is gated on a window end date because the pilot is a bounded
    evaluation rather than a permanent feature.
    """
    until = os.environ.get(US_ATTENTION_UNTIL_ENV, "").strip()
    engine_root = os.environ.get(US_ATTENTION_ENGINE_ENV, "").strip()
    if not until or not engine_root:
        return
    if run_date > until:
        print(json.dumps({
            "event": "us_attention_shadow_window_closed",
            "run_date": run_date,
            "until": until,
        }, sort_keys=True))
        return
    try:
        execute([
            sys.executable,
            "scripts/run_us_attention_shadow.py",
            "--engine-root", engine_root,
            "--fetch",
            "--date", run_date,
        ])
        print(json.dumps({
            "event": "us_attention_shadow_completed",
            "run_date": run_date,
        }, sort_keys=True))
    except Exception as exc:
        print(json.dumps({
            "event": "us_attention_shadow_skipped",
            "run_date": run_date,
            "error": str(exc),
        }, sort_keys=True))


def publish(*, build: Callable[[str], dict[str, str]] = build_sites) -> dict:
    run_date = run_date_from_env()
    mode = publisher_mode()
    db = get_supabase()
    claim = claim_task(db, run_date=run_date, mode=mode)
    if claim is None:
        return {"status": "duplicate", "run_date": run_date, "mode": mode}
    logical_key, claim_token = claim
    details: dict = {
        "run_date": run_date,
        "mode": mode,
        "publisher_version": PUBLISHER_VERSION,
        "source_revision": os.environ.get("PUBLISHER_IMAGE_SHA", "unknown"),
    }
    try:
        details["site_hashes"] = build(run_date)
        try:
            generate_board_email(run_date, store=mode == "active")
        except Exception as exc:
            # The board email must never block site publication. Missing tables
            # or an empty board degrade to "no board email this run".
            print(json.dumps({
                "event": "board_email_generation_skipped",
                "run_date": run_date,
                "error": str(exc),
            }, sort_keys=True))
        details["snapshot_uri"], details["snapshot_sha256"] = upload_snapshot(run_date, mode)
        if mode == "active":
            dispatch_board_email(run_date)
            deploy_sites()
            verify_sites(run_date)
        details["manifest_uri"] = upload_manifest(details)
        if mode == "active":
            # Publication is the final irreversible state transition. All
            # sends, deployments, live verification, and manifest persistence
            # must succeed first.
            mark_published(run_date)
        run_us_attention_shadow(run_date)
        if not finish_task(
            db,
            logical_key=logical_key,
            claim_token=claim_token,
            status="succeeded",
            details=details,
        ):
            raise RuntimeError("site publisher completion claim was lost")
        return {"status": "completed", **details}
    except Exception as exc:
        finish_task(
            db,
            logical_key=logical_key,
            claim_token=claim_token,
            status="failed",
            details=details,
            error=str(exc),
        )
        raise


def main() -> int:
    print(json.dumps(publish(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
