"""Environment-variable helpers shared by functions and jobs."""

from __future__ import annotations

import os


def require_env(name: str) -> str:
    """Return env var ``name`` (stripped), raising if it is missing or blank."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
