"""Minimal Supabase REST client shared by the board scripts and jobs.

Each script that talked to Supabase repeated the same plumbing: build the URL,
set the apikey/Authorization headers, encode the body, decode the response. This
is that plumbing once, so call sites read as data operations.

Query strings stay with the caller: the domain knowledge of which filters a
table needs belongs next to the code that reads it, and keeping the queries
readable is worth more than a query builder.
"""

from __future__ import annotations

import json
from typing import Any
import urllib.error
import urllib.parse
import urllib.request


class SupabaseRestError(RuntimeError):
    """Raised when Supabase answers with an error status."""


class SupabaseRest:
    def __init__(self, base_url: str, service_key: str, *, timeout: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_key = service_key
        self.timeout = timeout

    def _headers(self, *, prefer: str | None = None, with_body: bool = False) -> dict[str, str]:
        headers = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Accept": "application/json",
        }
        if with_body:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def call(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        prefer: str | None = None,
        timeout: int | None = None,
    ) -> Any:
        """Issue one PostgREST request and return the decoded payload."""
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/rest/v1/{path}",
            data=data,
            headers=self._headers(prefer=prefer, with_body=body is not None),
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise SupabaseRestError(f"{method} {path} failed: {exc.code} {detail}") from exc
        return json.loads(payload) if payload.strip() else None

    def get(self, path: str, *, timeout: int | None = None) -> list[dict]:
        """Read rows. ``path`` is PostgREST-relative, e.g. ``races?cycle=eq.2026``."""
        return self.call("GET", path, timeout=timeout) or []

    def upsert(
        self,
        table: str,
        rows: Any,
        *,
        on_conflict: str | None = None,
        timeout: int | None = None,
    ) -> list[dict]:
        """Insert rows, merging duplicates on ``on_conflict`` and returning them."""
        path = table if not on_conflict else f"{table}?on_conflict={on_conflict}"
        return self.call(
            "POST",
            path,
            body=rows,
            prefer="resolution=merge-duplicates,return=representation",
            timeout=timeout,
        ) or []

    def rpc(self, name: str, params: dict, *, timeout: int | None = None) -> Any:
        """Call a Postgres function exposed over PostgREST."""
        return self.call("POST", f"rpc/{name}", body=params, timeout=timeout)

    def upload_object(
        self,
        bucket: str,
        path: str,
        data: bytes,
        *,
        content_type: str,
        upsert: bool = True,
        timeout: int | None = None,
    ) -> None:
        """Upload one object through the Storage API (not PostgREST)."""
        url = f"{self.base_url}/storage/v1/object/{bucket}/{urllib.parse.quote(path, safe='/')}"
        headers = self._headers(with_body=True)
        headers["Content-Type"] = content_type
        if upsert:
            headers["x-upsert"] = "true"
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise SupabaseRestError(f"upload {bucket}/{path} failed: {exc.code} {detail}") from exc
