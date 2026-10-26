# Case study: from news pipeline to evidence-aware coverage board

[Project introduction](../README.md) · [Timeline](evolution.md) · [Evidence](evidence.md)

## The problem and the eventual product

NewsCloud began with a practical question: could a recurring view of regional news make political coverage easier to follow without reading every source? The implementation combined gathering, word clouds, language scoring, a static dashboard and email. The early ambition also included interpreting the signal as politically predictive. Those are different problems, and the project ultimately had to separate them.

By September, the U.S. product was a Race Board: a descriptive view of monitored coverage and public campaign finance, with supporting evidence and an email edition. Trinidad & Tobago and United Kingdom regional pages retained a topic-oriented presentation. The October 23 snapshot records a reduced, every-other-day edition cadence while maintenance continued independently. It does not establish subsequent live service status. [E01–E11, E21](evidence.md)

## Responsibility and method

This was an owner-directed, AI-assisted project rather than a claim of solo unaided coding. The owner chose direction and authorized production decisions. AI tools assisted architecture, implementation, incident diagnosis, research and critique. The meaningful accountability is visible in the decisions: stop claiming prediction, hold a release when its evidence is wrong, inspect actual production outcomes, and remove superseded paths.

The history contains advisor-style and investor-style critiques. Those are analysis formats, not evidence that named firms advised or endorsed NewsCloud. Likewise, prospective customer segments and signup infrastructure are not paying customers. No sustained product-market fit is established by this record. [E22–E23](evidence.md)

## Five defensible wins

### 1. Retries acquired an owner

A distributed pipeline cannot treat every delivery as fresh work. Database-backed stage claims and leases made the right to retry explicit; quota reservations put provider limits in durable state rather than in one process's memory. October's Cloud Tasks rollout then spaced the regional fan-out instead of expecting a slow consumer to absorb a burst.

The October 9 report contrasts three earlier days with **23,648–28,010 gatherer invocations** against roughly **53 expected**, with **53–54 HTTP requests for 53 regions** per fan-out during October 4–7. These are different transport counters and a short observation window, not a general performance benchmark. The useful result is the bounded production evidence that the new path stayed close to intended work. [Incident and source map](incidents/retry-amplification.md)

### 2. Publication stopped depending on routine CI execution

GitHub Actions initially bridged data export, artifact generation and publishing. A successful synthesis could therefore leave no email artifact when the operational workflow never started. The migration introduced a claimed Cloud Run publisher, shadow comparison, immutable manifests and publication ordering before active cutover. GitHub remained a delivery tool for code rather than the intended daily runtime owner.

This was not a clean first attempt: permissions, differing sanitized snapshots, missing staged files and stale images all produced real defects. The win was establishing explicit ownership and checking deployed output, not merely moving a script between vendors. [Architecture](architecture.md), [E10](evidence.md#e10-publication-ownership)

### 3. Missing inputs became part of the interface

A rating near its midpoint is not evidence of an evenly balanced race. In the October 9 snapshot, the board had counted absent inputs as tossups. The corrected presentation counted **27 monitored tossups rather than 377 apparent tossups**, and reported **156 monitored / 353 unmonitored races out of 509**. The same eligibility mistake was corrected in email spotlight selection and the retrospective calibration path.

That is a substantial correctness fix—but strictly a coverage-tally fix. The House still had qualifying inputs for only **86 of 435 seats in that snapshot**, and those inputs could be finance rather than broad news coverage. [Incident](incidents/missing-coverage.md)

### 4. Evidence could veto attractive copy

The editorial work went beyond rewriting a summary. Supporting story URLs were carried through generation and export; unmatched evidence received less specific language rather than invented support. Regional topic publication was held when unrelated articles merged through transitive connections. The eventual matcher required direct compatibility within a cluster and more careful entity evidence.

Rendered email review also found defects that code inspection missed: distribution bars visually overstated the monitored footprint, and HTML exposed an empty money sentence that text had guarded. The response was to repair both the data contract and its presentation. [E09, E18](evidence.md)

### 5. The product claim changed when validation did not support it

The July backtest and sensitivity sweep did not establish predictive validity. September's explicit interpretation preserved the limits of the negative controls, rejected a circular replacement design, and retired the predictive product claim. A deterministic rating remained useful as an inspectable description of inputs; it was not relabelled as a validated forecast.

This is a decision-quality win, not a positive scientific result. [Evaluation](evaluation.md)

## What did not work

**An incomplete migration became an outage.** R2 received production writes while old objects continued to count against Supabase Storage. The September 30 record attributes project-wide API restriction to **6,841 objects, about 1.13 GB against a 1 GB allowance**. The blocked API also prevented cleanup until the owner restored access. Static pages remained reachable but stale. [Storage incident](incidents/storage-quota.md)

**Green execution was not always useful execution.** An image-pruning script counted accepted operations as deletions even when they later failed. An attention pilot was isolated so it could not block publication; that same boundary let the publisher succeed while the pilot wrote nothing because its script was absent from the image. Neither a green job nor a submitted API operation is the business postcondition. [E17, E19](evidence.md)

**District sourcing was the binding product constraint.** State coverage could not honestly stand in for House-district coverage. Adding feeds and headlines did not necessarily yield relevant, diverse district evidence. Quota fairness helped attempts happen; it could not create missing journalism or validate the resulting scores. [Missing-coverage incident](incidents/missing-coverage.md)

**Operational maturity outpaced customer proof.** Working ingestion, an email subscription flow and prospective-market analysis did not establish retention, willingness to pay or measurable customer outcomes. It would be misleading to describe the wind-down as a commercial success. [E22](evidence.md)

## What this release demonstrates

The offline demo deliberately exercises a narrower, real boundary: authored inputs enter the retained rating and public-export functions, then the retained email renderers. It makes the monitored/missing distinction and a prior-edition change inspectable without accounts or live news rights. The cloud orchestration is retained as reviewed reference source, not simulated as a fake running service.

The transferable engineering lesson is that **data quality, runtime completion and product value require different evidence**. NewsCloud became more honest when it stopped letting one stand in for the others.
