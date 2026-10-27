# Security and publication boundary

This is a public portfolio source snapshot, not a production deployment.
It contains a runnable offline example and sanitized source for review.
Public release and the MIT license were explicitly authorized by the owner.

## Safe default

The documented `python3 -m demo.build --output demo-output` command uses authored
synthetic inputs and writes static local files. It does not gather news, fetch
financial data, connect to a database, authenticate to a cloud, deploy, or send
email. The local preview has no signup form or subscriber backend.

Production-derived modules also contain I/O functions. Their presence is code
for inspection, not permission to invoke them against production. Do not supply
production environment variables, application-default credentials, tokens or
service accounts to this candidate. Reference function/job files are not a
turnkey deployment: their production orchestration and configuration are
intentionally outside this release.

## What does not cross the boundary

- The original Git history, branches, tags, remote configuration or GitHub integrations.
- Production workflow files, cloud-trust bindings, deployment defaults or secret values.
- Subscriber rows, real-recipient seeds, delivery records, unsubscribe tokens or links.
- Raw operator logs, private strategy/customer research, database dumps or generated archives.
- Third-party news content, geographic map data or unreviewed screenshots.

The source export is an allowlist. `SOURCE_MANIFEST.json` records copied paths,
source revision, hashes and declared transformations. It does not prove every
possible confidentiality issue is absent. Read it alongside [provenance](PROVENANCE.md)
and the [rights review](RIGHTS.md).

## Required checks before publication

1. Inspect the exact file list, docs, screenshots, author metadata and generated demo.
2. Run a redacted secret scan over the candidate tree and every candidate commit.
3. Review personal information separately from credential detection. A secret
   scanner passing is not a privacy certification.
4. Verify the documented demo from a fresh checkout with no credentials and
   network access denied during replay. Confirm that output links remain local.
5. Keep public CI limited to tests and the offline build, with read-only contents
   permission, no OIDC token permission, no secrets and no deployment or email steps.
6. Resolve code licensing and third-party provenance; choose the public repository
   and a private vulnerability-reporting channel before publishing.

The preparation process does not probe credentials for validity. If an actual
credential exposure is discovered, stop release, privately notify the owner and
agree on revocation/rotation; deleting a committed value alone is not remediation.

## Reporting

Use [GitHub private vulnerability reporting](https://github.com/gregory1506/newscloud-portfolio/security/advisories/new)
to report findings privately. Provide a minimal reproduction without credential
values or subscriber information. Do not open a public issue containing sensitive
material. This repository does not authorize testing the production service.

The verification record describes checks actually performed and their limits.
It is not a claim that the production service or its full history is secure.
