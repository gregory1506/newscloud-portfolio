"""GCP environment helpers shared by the Cloud Functions."""

from __future__ import annotations

import os


def get_project_id() -> str:
    """Resolve the GCP project id from the standard environment variables."""
    project_id = (
        os.environ.get("GCP_PROJECT")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GCLOUD_PROJECT")
    )
    if not project_id:
        raise ValueError("GCP project ID must be set via GCP_PROJECT or GOOGLE_CLOUD_PROJECT")
    return project_id
