# Evidence notes and claim boundaries

[Case study](case-study.md) · [Evaluation](evaluation.md) · [Evolution](evolution.md)

These notes are a **self-contained, redacted digest** of dated source records inspected while preparing the October 23, 2026 snapshot (`71070bb`). They are not live measurements, an independent audit or copied private operational logs. Private source paths, line ranges and commit traceability are maintained outside this release; there are deliberately no broken links to private files here.

Three evidence types are kept distinct:

- **Retained implementation:** source a reader can inspect in this repository. It establishes code behavior, not historical deployment by itself.
- **Dated operator record:** work-log/report observations summarized below. These bound historical claims to their measured window; underlying accounts and raw production data are not published.
- **Owner account or proposal:** labelled as such; neither is treated as a verified deployment or result.

## E01: Origin and provenance

**February 2026 / May 1, 2026.** The owner dates the idea to February. The earliest verified main-repository commit is `b693f18`, dated May 1, titled “Initial commit: Serverless NewsCloud architecture.” No February–April artifact was located in inspected relevant sources. Git history starts where it starts; this release neither invents earlier commits nor equates the first commit with conception.

## E02: May runtime and delivery

**May 1–20.** Commit history and dated work entries show the serverless pipeline, scoring, an idempotent export finalizer, delivery retries and durable delivery jobs. The record also distinguishes completed regional processing from missing email service/permission failures. This supports a developed operational pipeline, not uninterrupted service since inception.

## E03: June reconciliation and reader quality

**June 19–28.** The source record describes cold-reader editorial review, named comparison baselines, visible freshness and live-date checks. A June 28 atomic retry migration was deployed; its recovery initially reached historical work, prompting a current-run restriction. The [retained retry SQL](../reference/supabase/migrations/20260628100000_add_atomic_stage_retry_claims.sql) makes the ownership mechanism inspectable. It does not erase the rollout mistake.

## E04: Party lanes and the delivery gap

**July 2–12.** Two party-framed products were merged July 2 before their functions were deployed. A July 10 audit found July 4–9 syntheses without generated artifacts or delivery jobs, then recorded recovery and automation. July 11–12 unattended delivery was subsequently recorded. Both lanes were retired in September. Neither merged code nor a synthesis row proves an email was delivered.

## E05: July backtest

**July 21; interpretation clarified September 24.** Six special-election events yielded one prior move, one same-day move, two lags and two misses. The prior move led by 38 days. All six events were party holds. Ten assumed-quiet states all registered false positives. The report's generated optimistic headline overstated what the table could establish. The controls used national polling stability as a proxy for state-specific quietness: a material limitation. **Predictive validity was not established; “proven noise” is also too strong.** [Retained analyzer](../reference/scripts/analyze_validity.py)

## E06: Sensitivity sweep

**July 27.** Sixteen decisive-band/smoothing combinations reused the six events and ten controls. Fifteen returned a control false-positive rate of 1.00; the remaining combination returned 0.90 while losing the captured leads. This did not rescue the claim through the tested tuning choices. It was neither independent replication nor an exhaustive search, and the weak control assumption stayed fixed. [Retained sweep](../reference/scripts/sensitivity_sweep.py)

## E07: Rejected replacement control

**August 10 design; September 24 interpretation.** A NYT editorial-attention replacement was researched and specified but rejected before implementation because NYT already fed gathered inputs. This was a circular-validation concern, not a completed improved backtest. The proposal cannot be counted as a shipped evaluation feature.

## E08: Finance integration

**August 6–10; display correction October 2.** The record shows FEC ingestion, a missing deployed credential binding and a primary-election attribution error: opposition spending against a same-party candidate had been credited across the aisle. Real-data replay informed the correction. The historical lane classifier was later retired. In October, weekly state-apportioned digital estimates were explicitly separated from band inputs. This supports a carefully bounded finance feature, not complete campaign-spending coverage or validated campaign utility.

## E09: Evidence links and regional topic quality

**August 23–31.** Supporting URLs were propagated through editorial output. Regional topic publication was held when transitive connections merged unrelated articles; complete-link matching and stricter entity evidence preceded a dated title-level acceptance review. This is evidence of a release quality gate, not a general clustering-accuracy metric or permission to redistribute original news excerpts.

## E10: Publication ownership

**August 31–September 23.** A CI-owned export could fail before artifact creation even when synthesis succeeded. GCP publisher shadow runs, hash/manifests comparison and active cutover followed. The Race Board cutover was recorded September 20, and retired party/battleground code and infrastructure were removed afterward. [Retained publisher](../reference/jobs/site_publisher/runner.py) exposes the final ordering. Old transitional architecture descriptions are not the current architecture.

## E11: Descriptive Race Board

**September 19–24.** Product direction locked September 19; production cutover was recorded September 20. The September 24 interpretation explicitly prohibits predicting, leading or forecasting election results from this evidence. The retained band calculator describes monitored coverage/finance inputs. Post-election calibration was positioned as a retrospective limitations audit, not a validation result already available in October.

## E12: House coverage limit

**September 25 snapshot.** The audit recorded 362 of 435 House races without qualifying signal: 356 outside the bounded target list and six targeted races without adequate coverage or FEC coverage. Only two House races had at least two supporting outlets; 23 had any. Targeting and evidence availability both matter. These figures measure the system's inputs on that date, not the amount of journalism that existed nationwide.

## E13: Retry amplification and durable district state

**September 28–30.** The audit recorded state work exhausting shared credits while districts were missed. Slow serialized handling, stale recovery and repeated delivery interacted. Atomic gather claims prevented a duplicate from making another provider call; dead-letter policies bounded redelivery. On September 30, the record says district-run state and claims were applied, giving empty, failed and never-attempted districts a durable distinction. [Region claim](../reference/supabase/migrations/20260928140000_add_region_gather_claim.sql), [district claim](../reference/supabase/migrations/20260930120000_add_district_runs.sql), [incident](incidents/retry-amplification.md)

## E14: Paced dispatch observation

**October 9 report, covering early October.** Three pre-change days recorded 23,648–28,010 gatherer invocations against roughly 53 expected. Four October 4–7 fan-outs recorded 53–54 HTTP requests for 53 regions, settled median spacing of 64–65 seconds and drained queues. The October 3–7 runs published 56–59 minutes after fan-out. Transition replay/duplicate observations were separately recorded and claim-skipped. These counters are not identical across transports; the comparison is bounded operational evidence, not an indefinite throughput/SLA or savings claim.

## E15: Storage quota outage

**September 29–30.** About 1.13 GB in 6,841 legacy objects exceeded a 1 GB Supabase Storage allowance after writes had moved to R2. Project restriction returned HTTP 402 from both data and storage APIs, blocking even cleanup. Static sites remained reachable but stale. After the owner restored access, equal-size object reconciliation preceded deletion; the record reports zero remaining objects/bytes and a late September 30 publication after additional delivery recovery. Equal-size reconciliation is not a claim that every copied object was cryptographically compared. [Incident](incidents/storage-quota.md)

## E16: Follow-up and cost limits

**October 7–9.** Follow-up recorded zero objects/bytes in legacy storage. The cost report separated empty Supabase Storage from structural image/secret overages and distinguished measurable vendor usage from a send-only email API key's limits. It does not prove permanent free operation or billed savings. [Retained usage reporter](../reference/scripts/free_tier_report.py)

## E17: Silent pruning success

**October 2.** A pruning script reported 40 accepted deletions while the long-running operations had failed on tagged versions. The repair deleted tags and counted only completed error-free operations; an initial rerun recorded 37 actual deletions and three failures, with a later tag-propagation fix addressing the remainder. Byte totals lagged and concurrent deployments changed storage, so deletion count was not immediately equivalent to billed savings. The side-effecting pruning script is intentionally not exported. [Evaluation](evaluation.md#three-different-meanings-of-success)

## E18: October 9 missing-input correction

**October 9 snapshot.** The report records a displayed tossup correction from 377 to 27 after unmonitored races were excluded. A coherent snapshot breakdown is 156 monitored / 353 unmonitored out of 509: Senate 34/35, House 86/435, governors 36/39. A later same-day grid note gives a different House missing count; it is not combined with this breakdown. Monitoring means `source_count >= 2` or `fec_coverage > 0`, not necessarily multi-outlet news coverage. The correction reached tally, email spotlight and retrospective calibration selection. It is a denominator/data-state correction, **not electoral accuracy**. [Retained export contract](../scripts/export_race_board_data.py)

## E19: Silent attention-shadow failure

**October 9.** The publisher completed but the attention pilot wrote nothing: its runner was absent from the staged image. Isolation allowed publication to proceed as designed. The stager was repaired and the intended pilot window extended to October 23. No inspected final acceptance report proves that the intended sequence of shadow runs completed successfully. Passing the end date is not evidence of acceptance.

## E20: Historical test record

**October 9 source report.** Recorded: 874 tests passed, 52 skipped, 78.0% coverage and clean source lint. The skips were described as migration-backed SQL requiring PostgreSQL. This is a historical source-session result, not a result for the portfolio candidate or proof of scientific/customer validity. [Candidate verification boundary](evaluation.md#candidate-verification-status)

## E21: October 23 wind-down

**October 23.** The source records a move to every two calendar days, anchored October 23, with maintenance cadence preserved. A live off-day invocation recorded a skip and the next scheduled date; read-only maintenance audits also ran. No publication-day replay or subsequent edition outcome follows from that evidence. The release snapshot ends at `71070bb`. [Calendar implementation](../shared/publication_schedule.py)

## E22: Commercial evidence boundary

**Record inspected through October 23.** Signup and delivery functionality, prospect research and pricing plans do not establish sustained paid demand, retention, campaign outcomes or product-market fit. The absence of that proof here is not a claim that no conversation ever occurred. Private contacts and raw research are not exported.

## E23: Owner and AI assistance

**May–October source record; owner context.** The record documents owner direction alongside AI-assisted coding, research, investigation and critique. No line-by-line human/AI authorship allocation is supported. Advisor-style role-play documents do not establish real advisory relationships or investor endorsement.

## E24: Calculator and diagnostic semantics

**October 23 source snapshot.** [`rate_race`](../shared/coverage_rating.py) renormalizes available components and attenuates by input confidence; incumbency alone cannot justify a directional band. [`coverage_quality`](../shared/coverage_quality.py) returns diagnostics rather than making publication decisions. [`export_race_board_data`](../scripts/export_race_board_data.py) owns the monitoring predicate. These are inspectable contracts, not evidence of calibrated probability, a hard source-quality publication gate, or nationwide coverage completeness.
