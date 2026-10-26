"""Check exported-source integrity, local documentation links and release hygiene.

This is not a secret scanner, legal review or security certification. Run a
separate redacted secret scan and manual privacy review before publication.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
IGNORED_ROOTS = {".git", ".venv", ".pytest_cache", "demo-output"}
SOURCE_ROOTS = {"shared", "scripts", "reference", "tests"}
CANDIDATE_SOURCE_FILES = {"tests/test_demo.py", "tests/test_verifier.py"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
LINK = re.compile(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)")
EXAMPLE_DOMAINS = {"example.com", "example.org", "example.net", "example.invalid"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    failures: list[str] = []
    manifest = json.loads((ROOT / "SOURCE_MANIFEST.json").read_text())
    entries = manifest["files"] + manifest.get("generated_files", [])
    exported_paths = [item["exported_path"] for item in entries]
    if len(set(exported_paths)) != len(exported_paths):
        failures.append("Duplicate exported paths in source manifest.")
    if manifest["exported_source_files"] != len(manifest["files"]):
        failures.append("Exported source file count disagrees with manifest entries.")
    if manifest["source_files"] != len({item["source_path"] for item in manifest["files"]}):
        failures.append("Unique source file count disagrees with manifest entries.")
    allowed_source_paths = set(exported_paths) | CANDIDATE_SOURCE_FILES
    for item in entries:
        path = ROOT / item["exported_path"]
        if not path.resolve().is_relative_to(ROOT) or path.is_symlink():
            failures.append(f"Unsafe manifest path: {item['exported_path']}")
        elif not path.is_file() or digest(path) != item["exported_sha256"]:
            failures.append(f"Export hash mismatch: {item['exported_path']}")
    checked = 0
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if relative.parts[0] in IGNORED_ROOTS or "__pycache__" in relative.parts:
            continue
        if path.is_symlink():
            failures.append(f"Symlink requires review: {relative}")
            continue
        if not path.is_file():
            continue
        checked += 1
        if relative.parts[0] in SOURCE_ROOTS and relative.as_posix() not in allowed_source_paths:
            failures.append(f"Unmanifested source file: {relative}")
        if path.name == ".env" or path.name.startswith(".env.") or path.suffix in {".pem", ".p12", ".pfx"}:
            failures.append(f"Private configuration/key filename: {relative}")
        if relative.as_posix().startswith(".github/workflows/") and path.name != "verify.yml":
            failures.append(f"Unexpected workflow: {relative}")
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            continue  # Images require the documented separate visual review.
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"Unreviewed binary file: {relative}")
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            for match in EMAIL.finditer(line):
                domain = match.group(1).lower()
                if domain not in EXAMPLE_DOMAINS and not domain.endswith(".invalid"):
                    failures.append(f"Non-example contact address: {relative}:{line_number}")
        if path.suffix == ".md":
            for match in LINK.finditer(text):
                target = unquote(match.group(1).strip("<>"))
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                destination = (path.parent / parsed.path).resolve()
                if not destination.is_relative_to(ROOT) or not destination.exists():
                    failures.append(f"Broken/nonlocal documentation link: {relative} -> {target}")
    print(json.dumps({"files_checked": checked, "export_hashes_checked": len(entries), "failures": failures}, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
