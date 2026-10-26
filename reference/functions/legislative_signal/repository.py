"""Idempotent upsert for legislative_signals rows."""

from __future__ import annotations

import hashlib
import json

from supabase import Client


def compute_source_hash(row: dict) -> str:
    """Hash the external-signal values while ignoring database metadata."""
    payload = json.dumps(
        {key: value for key, value in row.items() if key not in {"id", "created_at", "updated_at", "source_hash"}},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def upsert_legislative_signal(supabase: Client, row: dict) -> None:
    """Write or update a legislative_signals row keyed on (run_date, region).

    Calling this twice for the same (run_date, region) is safe — the second
    call overwrites the first with the latest values.
    """
    supabase.table("legislative_signals").upsert(
        row,
        on_conflict="run_date,region",
    ).execute()
