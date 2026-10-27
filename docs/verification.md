# Candidate verification record — October 26, 2026

[Evaluation](evaluation.md#candidate-verification-status) · [Local commands](local-demo.md) · [Release gates](../SECURITY.md)

## Revision and environment

The executable candidate checked in a fresh, non-hardlinked local Git clone was `04f5aeacf6981e2eef9ba98d005e3f50bea3273b`. It was a new root commit containing 155 files, not an import of production history. The original candidate had no Git remote. Author and committer metadata used the reserved address `portfolio@example.invalid`; no author identity or date was fabricated to represent earlier work.

The production-derived source is separately pinned to `71070bb96a6f0dd5da378f06a11f9eb399d9a0c1` in [SOURCE_MANIFEST.json](../SOURCE_MANIFEST.json). This record and its evaluation link were added after the executable check; they do not change the checked code.

Environment: Linux, CPython **3.13.15**, pytest **9.1.1**. A dedicated virtual environment installed only the candidate's pinned test requirements. The clone was not installed as an editable package and did not import the private production worktree.

## Observed checks

| Check | Observed result | Boundary |
|---|---|---|
| Actual CLI in the fresh clone | Board, details, evidence, JSON and both email formats generated | Empty environment, empty HOME, Python `-S`; no site-packages or credentials |
| Full selected candidate test suite | **131 passed, 0 skipped** | Not the larger private production suite; no candidate coverage percentage measured |
| Source integrity and inventory | **128 hashes verified**, no failures | 126 exported source files plus two generated configurations; unlisted production-root files rejected |
| Offline and repeatability regressions | Passed | Cold import with socket/URL access and database construction denied; repeated output bytes and local link targets checked |
| Output safety regressions | Passed | Foreign directories, output symlinks and unrelated files rejected without modifying protected content |
| Release-verifier regressions | Passed | Unlisted files, duplicate manifest paths, inconsistent counts and modified export bytes rejected |
| New-code lint | Passed locally | Demo, verifier and their new tests; not a new lint result for all reference code |
| Chromium inspection | Board, race detail, evidence and email navigation exercised | Desktop and 390 px mobile inspection; no observed board/detail/email horizontal overflow or page errors |
| Final preview assets | Board HTML, CSS and icon returned HTTP 200 | Localhost only; initial optional favicon miss was corrected with an authored local asset |
| Screenshot review | Synthetic board only; no text/EXIF PNG metadata | Screenshot is not production news, customer data or a historical UI capture |
| Gitleaks 8.30.1 | No findings in the scanned candidate directory or separately scanned original history | Original scan covered 775 commits; no assertion of comprehensive secret/PII absence |
| Static privacy/security review | No remaining actionable finding in the selected export | No live provider access, penetration test, credential validation or legal clearance |

## Reproduce the executable boundary

With a clean clone and a virtual environment prepared from `requirements-dev.txt`, use that environment's absolute Python path as `PYTHON` below. Create an empty directory and use its absolute path as `EMPTY_HOME`:

```bash
env -i PATH=/usr/bin:/bin HOME="$EMPTY_HOME" "$PYTHON" -S -m demo.build --output demo-output
env -i PATH=/usr/bin:/bin HOME="$EMPTY_HOME" "$PYTHON" tools/verify_candidate.py
env -i PATH=/usr/bin:/bin HOME="$EMPTY_HOME" PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$PYTHON" -m pytest -q
```

These commands were exercised from the fresh clone, using a dedicated empty home and the separate test environment. Test networking denial is implemented in the cold-import regression; the CLI invocation was not enclosed in an OS-level network namespace. The demo does not call provider code, and this record does not claim to have exercised cloud orchestration offline.

## Boundaries of the original preparation checks

- The original local preparation did not execute a public GitHub workflow, create a remote repository, push or deploy.
- No live credential validity, database migration run, provider response, email send or production behavior change.
- No election prediction, scientific reproduction on the original private dataset, commercial adoption or completed attention-shadow pilot.
- At preparation time no license grant had been selected. The owner subsequently authorized public release and chose [MIT](../LICENSE); this does not clear excluded maps/news/assets or change the scope of the original checks.

Secret scanners and static reviews have false negatives. Re-scan the exact proposed public tree and its new history after any further edits; retain detailed reports privately rather than publishing source operational logs.
