"""Unit coverage for the shared Supabase REST client."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.supabase_rest import SupabaseRest, SupabaseRestError

pytestmark = pytest.mark.unit


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


def test_get_sends_credentials_and_decodes_rows(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        captured["method"] = request.get_method()
        return FakeResponse(json.dumps([{"race_id": "2026-SEN-TX"}]).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    rows = SupabaseRest("https://db.example/", "service-key").get("races?select=race_id")

    assert rows == [{"race_id": "2026-SEN-TX"}]
    assert captured["url"] == "https://db.example/rest/v1/races?select=race_id"
    assert captured["headers"]["apikey"] == "service-key"
    assert captured["headers"]["authorization"] == "Bearer service-key"
    assert captured["method"] == "GET"


def test_upsert_merges_duplicates_on_the_conflict_key(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        captured["body"] = json.loads(request.data.decode())
        return FakeResponse(b"[]")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    SupabaseRest("https://db.example", "key").upsert(
        "artifacts", [{"run_date": "2026-09-23"}], on_conflict="run_date,region",
    )

    assert captured["url"].endswith("/rest/v1/artifacts?on_conflict=run_date,region")
    assert captured["headers"]["prefer"] == "resolution=merge-duplicates,return=representation"
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["body"] == [{"run_date": "2026-09-23"}]


def test_upload_object_marks_upsert_and_path_encodes(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = {k.lower(): v for k, v in request.header_items()}
        captured["body"] = request.data
        return FakeResponse(b"")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    SupabaseRest("https://db.example", "key").upload_object(
        "test-project-artifacts", "race_board_email/national/2026-09-23.html",
        b"<html></html>", content_type="text/html; charset=utf-8",
    )

    assert captured["url"] == (
        "https://db.example/storage/v1/object/test-project-artifacts/"
        "race_board_email/national/2026-09-23.html"
    )
    assert captured["headers"]["x-upsert"] == "true"
    assert captured["body"] == b"<html></html>"


def test_error_responses_raise_with_the_status_and_body(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 409, "Conflict", {}, io.BytesIO(b'{"message":"duplicate key"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(SupabaseRestError, match="409"):
        SupabaseRest("https://db.example", "key").get("races")


def test_empty_body_decodes_to_no_rows(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda request, timeout=None: FakeResponse(b""))
    assert SupabaseRest("https://db.example", "key").get("races") == []
