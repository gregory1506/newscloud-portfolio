# Decisions and tradeoffs

[Architecture](architecture.md) · [Evolution](evolution.md) · [Evaluation](evaluation.md)

These are retrospective decision summaries, not copied private design memos. Dates identify the evidence window; the status column prevents proposed or retired work from being mistaken for the final product.

| Decision | Why it was chosen | Cost or limitation | Status at October 23, 2026 |
|---|---|---|---|
| **Deterministic core; AI assistance around it** | Make ratings, claims and exports inspectable. AI-assisted investigation and editorial critique can improve implementation without owning the measurement contract. | Determinism does not make the input signal valid. A proposed autonomous advisory layer is not evidence of a shipped agent system. | Core retained; advisory expansion proposed, not established as deployed. |
| **Database claims before provider work** | At-least-once delivery is normal; prevent duplicates from spending credits or consuming retry budgets unnecessarily. | Leases, stale windows and queued-work detection become correctness concerns. The database is a critical dependency. | Region and district claims implemented; late-September district state closed an earlier visibility gap. |
| **Cloud Tasks for initial regional fan-out** | Scheduled times address burst delivery more directly than increasing retries around a slow subscriber. | Queue dispatch does not replace per-query pacing or quota reservations. District dispatch and recovery still use Pub/Sub. | October 4–7 production observations recorded; no indefinite SLA inferred. |
| **One GCP operational publisher** | CI scheduling and minute availability should not decide whether an already-computed edition has artifacts or emails. | Requires IAM, immutable publication evidence, shadow parity and explicit external-side-effect handling. | Active cutover recorded in September; GitHub runtime publication paths retired. |
| **R2 for object storage** | Separate growing artifacts from constrained database-project storage. | Copying is not retirement: reconciliation, read cutover, removal of fallback and deletion of originals all matter. | Writes moved in August; legacy cleanup completed after September's quota outage. |
| **Descriptive Race Board instead of prediction** | July validation did not support forecasting. Retain a narrower question the system can answer: what do monitored inputs show? | Familiar electoral band labels still invite overinterpretation. The interface must state the boundary and the denominator. | Direction locked September 19; production cutover September 20; predictive claim retired. |
| **District evidence rather than state proxy** | A House seat is not its whole state. Copying state coverage into every district manufactures specificity. | Sparse relevant reporting and shared provider limits leave much of the House unmonitored. | Bounded district gathering implemented; nationwide evidence completeness not achieved. |
| **Missing as an explicit public state** | Missing components can numerically collapse to the midpoint. Eligibility must be carried to every aggregate and selection path. | Every downstream consumer must preserve `has_signal`; a label fix in one view is insufficient. | October 9 correction covered tally, spotlight and retrospective calibration selection. |
| **Digital-placement estimates as context only** | Weekly state-apportioned estimates cannot justify district-level rating precision. | Less data contributes to the band than a broad "campaign money" label might imply. | October 2 specification and display corrected; rating remains FEC-based for finance. |
| **Isolate the attention shadow** | Exploratory research must not interrupt the established publication path. | Swallowing its failure can hide zero output behind a successful publisher job. | Shadow-only; October 9 staging failure repaired, final pilot acceptance not established. |
| **Retire superseded paths instead of keeping parallel products** | Multiple active publication owners and product branches multiply drift and operational ambiguity. | Historical feature breadth is no longer executable in the final snapshot. | Party lanes and legacy battleground product removed in September. |
| **Reduce edition cadence, keep maintenance** | Wind-down should reduce publication work without silently abandoning recovery or infrastructure checks. | Date logic must follow calendar parity across boundaries and distinguish intentional silence from failure. | October 23 rollout recorded; later edition outcomes outside this snapshot. |

## Alternatives that were not validated into production

- **NYT editorial-attention ground truth:** rejected because it reused a gathered source and could create circular validation. API feasibility did not resolve construct validity.
- **More aggressive threshold tuning as a predictive rescue:** the July sweep did not improve the claim under its control design. Its weak controls still prevent a universal conclusion that the signal is noise.
- **State-level House proxy:** easier to fill a board, harder to justify. A visibly incomplete map was preferable to unsupported district precision.
- **Autonomous operator/source/editor agents:** described as a possible advisory layer; not presented here as completed work.
- **A complete offline cloud emulator:** not the purpose of this release. The demo executes the real calculation/export/rendering path; orchestration remains reference source rather than a pretend service.

## What these decisions do not prove

They do not prove the system always recovered, every deployment was correct, all source evidence was sound, or users found the product valuable. The [incident studies](incidents/retry-amplification.md) show concrete failures; the [evidence notes](evidence.md) delimit observations; the [evaluation](evaluation.md) separates implementation correctness, measurement validity and commercial usefulness.
