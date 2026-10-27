# Rights and third-party provenance

The owner authorized public release and selected the [MIT License](LICENSE)
for the included NewsCloud software and associated documentation. The original
private snapshot had no root license; this grant is a deliberate release decision,
not an inference from an earlier public deployment or a dependency's license.
Third-party dependencies retain their own terms, and excluded assets are not licensed here.

## Included material

| Material | Provenance and treatment |
|---|---|
| Production-derived Python and SQL | Selected from the private NewsCloud snapshot recorded in `SOURCE_MANIFEST.json`; exact source/export hashes and transformations are recorded. Public distribution under MIT was authorized by the owner. |
| Synthetic demonstration | Written for this candidate. Financial amounts, coverage observations, candidates and headlines are invented, not copied from a news service, actual filing or subscriber record. State/chamber labels are illustrative and do not turn the fixture into election evidence. |
| Case studies and evidence summaries | Written from dated engineering records. Aggregate measurements are explicitly scoped; private raw logs, research and contact records are not reproduced. |
| Demo presentation and screenshots | Candidate-authored presentation and screenshots of the synthetic local demo. They are not screenshots of a real election result or evidence of product adoption. |
| Dependency declarations | Retained for source transparency. Dependency packages are not vendored; their own license terms apply when installed. The offline demo uses the Python standard library. |

## Deliberately excluded

- Original and transformed geographic map assets: redistribution provenance was
  not established by this preparation. The offline demo uses no map dataset.
- News/RSS/API headlines, article excerpts, social-platform posts, actual campaign
  data exports and historical generated emails.
- Production screenshots and private customer-development material.
- Borrowed UI assets: the production site contains a separate WatermelonUI MIT
  notice, but that notice does not license all NewsCloud code. Neither that CSS
  nor its other assets are needed or copied into this candidate.
- Third-party repositories and engines. Their existence in the engineering story
  is not a claim that their source or gathered data is included here.

## Release decision

Keep necessary third-party notices with the associated files. The MIT grant does
not establish rights to material that is not owned or included. If a real
screenshot, map or dataset is added later, record its source, version/date,
license or permission, attribution requirements and public-use decision before
including it. A public URL, a successful download, or previous public deployment
is not a redistribution license.

This file records a review boundary; it is not legal advice or an assertion of
rights over third-party work.
