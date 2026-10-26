"""Deterministic hashes for the three deployable publication trees."""

from __future__ import annotations

import hashlib
from pathlib import Path


PUBLICATION_TREES = {
    "us": "public-dashboard",
    "tt": "public-regions/tt",
    "uk": "public-regions/uk",
}


def hash_tree(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def publication_hashes(root: Path) -> dict[str, str]:
    return {name: hash_tree(root / directory) for name, directory in PUBLICATION_TREES.items()}
