"""Shared helpers for Google Cloud REST calls from operator scripts.

Scripts authenticate with Application Default Credentials; nothing here runs
inside a deployed function.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
MONITORING_SCOPE = "https://www.googleapis.com/auth/monitoring.read"


def access_token(scope: str = CLOUD_SCOPE) -> str:
    """Return an access token for the requested scope using ADC."""
    import google.auth
    from google.auth.transport.requests import Request

    credentials, _ = google.auth.default(scopes=[scope])
    credentials.refresh(Request())
    return credentials.token


def get_json(url: str, token: str, *, method: str = "GET") -> Any:
    """Call a Google API and decode the JSON body, with the error text on failure."""
    request = urllib.request.Request(url, method=method, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"HTTP {exc.code} for {url}: {body}") from exc
    return json.loads(payload) if payload else None


def paginate(url: str, token: str, *, item_key: str = "items") -> list[dict[str, Any]]:
    """Return every item of a paginated Google API collection."""
    items: list[dict[str, Any]] = []
    page_token: str | None = None
    while True:
        if page_token:
            separator = "&" if "?" in url else "?"
            page_url = f"{url}{separator}pageToken={urllib.parse.quote(page_token)}"
        else:
            page_url = url
        payload = get_json(page_url, token) or {}
        items.extend(payload.get(item_key) or [])
        page_token = payload.get("nextPageToken")
        if not page_token:
            return items
