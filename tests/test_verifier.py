"""Release-boundary regressions using isolated, synthetic candidate trees."""
from __future__ import annotations

import hashlib
import json

import pytest

from tools import verify_candidate


@pytest.fixture
def candidate_tree(tmp_path, monkeypatch):
    source = tmp_path / "shared" / "sample.py"
    source.parent.mkdir()
    source.write_text("# Authored test input.\n", encoding="utf-8")
    manifest = {
        "source_files": 1,
        "exported_source_files": 1,
        "files": [{
            "source_path": "shared/sample.py",
            "exported_path": "shared/sample.py",
            "exported_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }],
        "generated_files": [],
    }
    manifest_path = tmp_path / "SOURCE_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(verify_candidate, "ROOT", tmp_path)
    return tmp_path, manifest, manifest_path


def test_unlisted_reference_material_is_rejected(candidate_tree):
    root, _, _ = candidate_tree
    assert verify_candidate.main() == 0
    extra = root / "reference" / "private_notes.txt"
    extra.parent.mkdir()
    extra.write_text("Synthetic material outside the export allowlist.\n", encoding="utf-8")
    assert verify_candidate.main() == 1
    extra.unlink()
    assert verify_candidate.main() == 0


@pytest.mark.parametrize("count", ["source_files", "exported_source_files"])
def test_manifest_counts_must_match_inventory(candidate_tree, count):
    _, manifest, path = candidate_tree
    manifest[count] = 2
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_candidate.main() == 1


def test_duplicate_export_paths_are_rejected(candidate_tree):
    _, manifest, path = candidate_tree
    manifest["files"].append(dict(manifest["files"][0]))
    manifest["exported_source_files"] = 2
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert verify_candidate.main() == 1


def test_changed_export_bytes_are_rejected(candidate_tree):
    root, _, _ = candidate_tree
    (root / "shared" / "sample.py").write_text("# Different source.\n", encoding="utf-8")
    assert verify_candidate.main() == 1
