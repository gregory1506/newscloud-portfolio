# Provenance and scope

## A new history, not a rewritten past

This candidate is derived from private NewsCloud source revision `71070bb`,
recorded on 2026-10-23. It is prepared as a standalone local repository with a
new history, no production remote and no imported production Git objects.
Original commit dates are described as evidence, never recreated with backdated
commits. This snapshot is not an assertion about current production health.

The owner dates the project's beginnings to February 2026. The earliest verified
commit in the available, non-shallow production repository is May 1, 2026. Earlier
notes, screenshots or repositories were not located in the inspected sources.
The February–April period is therefore an owner-reported origin, not a verified
commit timeline. The archived August public write-up was considered historical
material, not an approved or accurate current release.

## What is copied and what is new

`SOURCE_MANIFEST.json` lists every exported production-derived file, its source
path and revision, original SHA-256, exported SHA-256 and transformation categories.
Identifiers and example contacts are sanitized where recorded. A match to a source
hash establishes file identity, not correctness or permission to distribute it.

The `shared/` and selected `scripts/` modules support the offline replay. Source
under `reference/` exposes the actual Cloud Function, job and schema designs for
inspection. It has no production deployment workflow and is not presented as a
self-contained cloud installation. External services, permissions and data are
not simulated by empty handlers or fake successful API responses.

The candidate's `demo/`, documentation, release checks and synthetic screenshots
are new presentation/verification work, not artifacts that existed during the
production timeline. Their purpose is to exercise and explain the retained
implementation without distributing source data or credentials.

## Deliberate portability changes

The text email renderer accepts an optional `map_urls` argument, like the HTML
renderer. Passing an empty mapping explicitly omits optional map images. The
map-URL helper defers its optional renderer import until map configuration is
actually present. These candidate-only adaptations remove an unnecessary imaging
import from the offline path without changing rating or band calculations. The
production repository is not changed by those adaptations.

The offline demo supplies its own inputs and local links; it never invokes the
production fetch, persistence, sending or deployment functions. It is an honest
local replay of rating/export/rendering, not an end-to-end emulation of Pub/Sub,
Cloud Tasks, Supabase or an email provider.

## Evidence handling

[Public evidence notes](docs/evidence.md) describe dated outcomes and limitations.
A separate private preparation ledger retains precise source locations and
supporting revisions. Raw work logs, original operational reports and subscriber
records are intentionally not published. Historical measurements are not current
uptime, throughput, audience or financial claims.

[Rights](RIGHTS.md) and [security](SECURITY.md) remain separate release gates.
An allowlist, a manifest and a clean secret scan do not establish a license,
scientific validity, privacy compliance, or absence of every security defect.
