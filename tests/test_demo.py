"""Integration edges of the sample adapter, not duplicate rating unit tests."""
from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from demo.build import PACKAGE, assemble, build, load_fixtures


class PageLinks(HTMLParser):
    def __init__(self, text: str):
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in {"href", "src", "action", "poster"} and value is not None:
                self.links.append(value)
            if key == "id":
                self.ids.add(value)


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def test_build_uses_stdlib_without_credentials_or_network(tmp_path):
    # -S removes site-packages. Deny networking before importing the demo, so
    # import-time regressions are covered as well as calls made during build.
    script = '''
import socket
import sys
import urllib.request

def forbidden(*args, **kwargs):
    raise AssertionError("The offline demonstration attempted network I/O")

socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.create_connection = forbidden
socket.getaddrinfo = forbidden
urllib.request.urlopen = forbidden
urllib.request.OpenerDirector.open = forbidden
from demo.build import build
from shared.supabase_rest import SupabaseRest
SupabaseRest.__init__ = forbidden
build(sys.argv[1])
'''
    result = subprocess.run(
        [sys.executable, "-S", "-c", script, str(tmp_path / "offline")],
        cwd=PACKAGE.parent,
        # A stray dashboard environment variable must not resurrect map links.
        env={"NEWSCLOUD_DASHBOARD_URL": "https://offline.invalid", "PYTHONHASHSEED": "71"},
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "offline" / "email.html").is_file()
    assert (tmp_path / "offline" / "email.txt").is_file()


def test_outputs_resolve_locally_and_repeat_without_fixture_mutation(tmp_path, monkeypatch):
    import socket
    import urllib.request

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network I/O")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setenv("NEWSCLOUD_DASHBOARD_URL", "https://offline.invalid")
    original = tree_bytes(PACKAGE)
    first = build(tmp_path / "first")
    snapshot = tree_bytes(first)
    second = build(tmp_path / "second")
    assert snapshot == tree_bytes(second)
    build(first)
    assert snapshot == tree_bytes(first)
    assert original == tree_bytes(PACKAGE)

    pages = {
        path.resolve(): PageLinks(path.read_text(encoding="utf-8"))
        for path in first.rglob("*.html")
    }
    for path, page in pages.items():
        text = path.read_text(encoding="utf-8")
        assert "SYNTHETIC SAMPLE" in text
        for link in page.links:
            parsed = urlsplit(link)
            assert not parsed.scheme and not parsed.netloc, (path, link)
            assert not parsed.query, (path, link)
            target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            assert target.is_relative_to(first.resolve()), (path, link)
            assert target.is_file(), (path, link)
            if parsed.fragment:
                assert unquote(parsed.fragment) in pages[target].ids, (path, link)
    for json_path in first.rglob("*.json"):
        data = json.loads(json_path.read_text(encoding="utf-8"))

        def check_urls(value):
            if isinstance(value, dict):
                for key, nested in value.items():
                    if key == "url":
                        assert not urlsplit(nested).scheme
                        assert (first / nested).is_file()
                    else:
                        check_urls(nested)
            elif isinstance(value, list):
                for item in value:
                    check_urls(item)

        check_urls(data)
    email_text = (first / "email.txt").read_text(encoding="utf-8")
    assert "http://" not in email_text and "https://" not in email_text
    for line in email_text.splitlines():
        if line.startswith(("Race page: ", "See the full board: ")):
            assert (first / line.split(": ", 1)[1]).is_file()
    style = (first / "style.css").read_text(encoding="utf-8")
    assert "url(" not in style and "@import" not in style


def test_missing_and_thin_inputs_remain_distinct_and_transition_is_calculated():
    fixtures = load_fixtures()
    untouched = deepcopy(fixtures)
    board, prior, details = assemble(fixtures)
    assert fixtures == untouched
    rows = {
        row["race_id"]: row
        for section in board["chambers"].values() for row in section["races"]
    }
    assert sum(section["tally"]["monitored"] for section in board["chambers"].values()) == 3
    for race_id in ("sample-qz-senate", "sample-qz-governor"):
        assert not rows[race_id]["has_signal"]
        # Keep production fallback in the exported data; exclude it from tally.
        assert rows[race_id]["rating_band"] == "Tossup"
        chamber = rows[race_id]["chamber"]
        assert board["chambers"][chamber]["tally"]["bands"]["Tossup"] == 0
    thin = rows["sample-ex-house-01"]
    assert thin["has_signal"] and thin["thin_signal"]
    below = rows["sample-qz-house-02"]
    assert below["source_count"] == 1 and not below["has_signal"]
    finance = rows["sample-ex-governor"]
    assert finance["source_count"] == 0 and finance["has_signal"]
    previous = {row["race_id"]: row for row in prior["chambers"]["senate"]["races"]}
    moves = board["chambers"]["senate"]["changelog"]
    assert len(moves) == 1
    move = moves[0]
    assert move["from_band"] == previous[move["race_id"]]["rating_band"]
    assert move["to_band"] == rows[move["race_id"]]["rating_band"]
    assert move["from_band"] != move["to_band"]
    calculation = details[move["slug"]]["demo"]["calculations"]
    assert calculation["prior"]["rating_band"] == move["from_band"]
    assert calculation["current"]["rating_band"] == move["to_band"]


def test_foreign_output_directory_is_not_modified(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    existing = output / "index.html"
    existing.write_text("keep this unrelated page", encoding="utf-8")
    before = tree_bytes(output)
    with pytest.raises(ValueError):
        build(output)
    assert tree_bytes(output) == before


def test_output_symlink_cannot_overwrite_an_external_file(tmp_path):
    output = build(tmp_path / "owned")
    external = tmp_path / "private.txt"
    external.write_text("untouched private content", encoding="utf-8")
    email = output / "email.html"
    email.unlink()
    email.symlink_to(external)
    with pytest.raises(ValueError):
        build(output)
    assert external.read_text(encoding="utf-8") == "untouched private content"


def test_unrelated_files_are_not_silently_published_on_rebuild(tmp_path):
    output = build(tmp_path / "owned")
    private = output / "notes.txt"
    private.write_text("not a demo artifact", encoding="utf-8")
    before = tree_bytes(output)
    with pytest.raises(ValueError):
        build(output)
    assert tree_bytes(output) == before
