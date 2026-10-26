"""Supabase client helper shared by the Cloud Functions."""

from __future__ import annotations

import os

from supabase import Client, create_client


def get_supabase() -> Client:
    """Create a Supabase client from the standard environment variables."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url or not key:
        raise ValueError(
            "SUPABASE_URL and SUPABASE_SECRET_KEY must be set in environment variables"
        )
    return create_client(url, key)
