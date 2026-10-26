# NewsCloud

**A news-coverage pipeline that became a lesson in distributed systems—and in knowing what the data cannot say.**

NewsCloud gathered regional reporting, produced coverage summaries and word clouds, and published a U.S. Race Board with an email edition. Its strongest engineering story is not an election prediction: it is recovering unreliable work, making missing evidence visible, and narrowing the product when validation did not support the original ambition.

This is a **production-derived source snapshot dated October 23, 2026**, with a runnable, entirely synthetic offline demonstration. It is not the production database, an imported private Git history, or a turnkey cloud deployment.

![Synthetic offline NewsCloud board: authored examples, not live election reporting](docs/assets/synthetic-board.png)

## See it locally

From this repository's root, with Python 3.13 or newer:

```bash
python3 -m demo.build --output demo-output
python3 -m http.server 8000 --directory demo-output --bind 127.0.0.1
```

Open [localhost:8000](http://localhost:8000). The server is optional: open `demo-output/index.html` directly instead. Generation requires no credentials, database, downloads or third-party services. Stop the server with Ctrl-C.

The demo calls the retained production rating, board export and email-rendering functions. It shows synthetic monitored, thin, missing and finance-only inputs, plus a prior-edition band change. All rendered links and assets stay local; no email is sent. [Commands, outputs and boundaries →](docs/local-demo.md)

## Three things worth inspecting

- **Work ownership before retries.** Atomic database claims, quota reservations and paced dispatch address the interaction between slow consumers and duplicate delivery. The October 4–7 production record showed **53–54 HTTP gather requests for 53 regions** per fan-out; this is a bounded observation, not a reliability guarantee. [Incident →](docs/incidents/retry-amplification.md)
- **Missing is not neutral.** In the October 9 snapshot, separating unmonitored races changed the displayed tossup tally from **377 to 27**. That corrected a coverage-band denominator, not electoral accuracy. Only **156 of 509 races** had qualifying inputs in that snapshot. [Incident →](docs/incidents/missing-coverage.md)
- **A claim can be retired.** The July study did not establish predictive validity. The September product became descriptive coverage and public-finance reporting, with the scientific limitations retained rather than marketed away. [Evaluation →](docs/evaluation.md)

All historical numbers above are dated source-record summaries. [Evidence notes →](docs/evidence.md)

## Read at your own depth

| Question | Start here |
|---|---|
| What was built, and what changed? | [Case study](docs/case-study.md) |
| How did the system work? | [Architecture and code map](docs/architecture.md) |
| What happened over the months? | [Evolution](docs/evolution.md) |
| What tradeoffs were deliberate? | [Decisions](docs/decisions.md) |
| What failed, and how was recovery handled? | [Retry amplification](docs/incidents/retry-amplification.md), [storage quota](docs/incidents/storage-quota.md), [missing coverage](docs/incidents/missing-coverage.md) |
| What can the evidence actually support? | [Evidence](docs/evidence.md) and [evaluation](docs/evaluation.md) |
| What has been verified in this candidate? | [Candidate checks](docs/evaluation.md#candidate-verification-status) |
| What was exported, excluded or adapted? | [Provenance](PROVENANCE.md), [security boundary](SECURITY.md) and [rights](RIGHTS.md) |

## Scope and ownership

An **owner-directed, AI-assisted project**: the owner set product direction and authorized operational decisions; AI tools assisted implementation, debugging, research and editorial critique. This is not a claim of unaided authorship, a staffed engineering team, investor endorsement or an external advisory relationship.

The owner dates the idea to **February 2026**. The earliest verified main-repository commit is **May 1, 2026**; no February–April artifact was located in the inspected sources. These are different provenance claims.

The October 23 source records an every-other-day publication wind-down, not a scaled commercial success. **Product-market fit remained unestablished.** Coverage bands are not win probabilities, polling, voter sentiment or recommendations to a campaign.

## Release boundary

The runnable surface is `demo/`, backed by retained modules in `shared/` and `scripts/`. `reference/` contains cloud implementation for inspection, not instructions to deploy it. Production credentials, recipient records, private research, original news excerpts and external map assets are excluded.

The candidate's recorded checks are separate from historical production verification; see [evaluation](docs/evaluation.md). Public release remains subject to the owner's licensing/publication decision and the [security](SECURITY.md)/[rights](RIGHTS.md) review. No license grant should be inferred from access to this preparation copy.
