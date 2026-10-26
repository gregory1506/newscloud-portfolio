# Evaluation: implementation, measurement and product value

[Case study](case-study.md) · [Evidence notes](evidence.md)

**The retained result is not a validated election predictor.** NewsCloud's useful public evidence is a functioning production-derived implementation, documented operational corrections, and a narrower descriptive product after the predictive claim failed to earn support.

## Scientific result: not validated, not proven noise

The **July 21, 2026** backtest compared the historical language-leaning signal with **six election events**:

| Relationship to event | Events |
|---|---:|
| Prior signal move | 1 |
| Same-day signal move | 1 |
| Lagging move | 2 |
| No qualifying move | 2 |

The prior move was **38 days before its event**. All six elections were party holds; the sample did not test party flips. The generated report headline grouped the same-day and prior cases into a favorable-looking verdict. That label is weaker evidence than the event table.

The negative-control exercise marked **10 of 10 assumed-quiet states** as false positives. The **July 27** sensitivity sweep reused the same events and controls across **16 threshold/smoothing combinations**, with control false-positive rates of **0.90–1.00**. It did not rescue the claim through the tested tuning choices. [E05–E06](evidence.md#e05-july-backtest)

However, the controls were **small and non-state-specific**: national generic-ballot stability stood in for evidence that each state was quiet. Changing signal thresholds while preserving that assumption cannot fix the control design. A proposed NYT editorial-attention replacement was rejected before implementation because NYT already contributed gathered inputs, making it circular. The September 24 interpretation therefore concluded **predictive validity was not established**, not that all possible signal value had been disproven. [E07](evidence.md#e07-rejected-replacement-control)

The retained [`analyze_validity.py`](../reference/scripts/analyze_validity.py) and [`sensitivity_sweep.py`](../reference/scripts/sensitivity_sweep.py) expose the analysis logic for review. Original private series and ground-truth artifacts are not supplied as a reproducible scientific dataset here. The offline demo does not rerun this study.

## Coverage limits are part of the result

In the **October 9 snapshot**, **156 of 509 races** met the exporter's monitoring predicate; **353 did not**. Its chamber breakdown was **34/35 Senate, 86/435 House and 36/39 governor races**. "Monitored" meant at least two sources **or** recorded FEC coverage, not a guarantee of broad news reporting. These are snapshot counts, not stable service reach. [E18](evidence.md#e18-october-9-missing-input-correction)

Earlier, the **September 25** review found only **two House races with at least two supporting outlets** and **23 with any**. The target list was intentionally bounded, and some targeted districts still lacked adequate evidence. The later monitoring count cannot be read as an equivalent increase in multi-outlet journalism. [E12](evidence.md#e12-house-coverage-limit)

The confidence value in [`rate_race`](../shared/coverage_rating.py) is an availability/source-breadth heuristic. It is not a calibrated confidence interval, probability of winning, or estimate of model accuracy. A retrospective band/outcome comparison after the November election would be a limitations audit, not retroactive proof that the October product was a forecast.

## Historical source verification—not candidate verification

The **October 9 source session report** recorded:

- **874 tests passing**;
- **52 skipped**, described as migration-backed SQL tests needing PostgreSQL;
- **78.0% coverage**;
- a clean source `ruff check .` result;
- selected live queue, storage, board and rendered-email inspections.

Those checks belong to that source session and environment. They were **not rerun while preparing this narrative** and must not be attached to this candidate as a passing badge. Passing unit tests also cannot establish third-party API shape, successful deployment, news-source quality or predictive usefulness. [E20](evidence.md#e20-historical-test-record)

### Candidate verification status

On **October 26, 2026**, the separately prepared candidate passed **131 tests with no skips** under Python 3.13.15 and pytest 9.1.1. The selected source tests and new demo/release-boundary regressions are not the full private production suite. No candidate coverage percentage was measured.

The actual CLI generated the board, race details, local evidence pages, JSON and HTML/plain-text email with an empty environment and Python's `-S` flag. Cold-import regression checks denied socket/URL networking and database construction; other checks compared repeated builds byte-for-byte and resolved generated links locally. Browser inspection exercised board → House race → evidence → email navigation at desktop and mobile widths, with no observed horizontal overflow on the board, detail or email surfaces.

The export verifier checked **128 recorded hashes**, enforced the source allowlist and checked local documentation paths. A deliberately unlisted source file reproduced a verifier gap; the corrected verifier rejected it, and the probe was removed. Gitleaks 8.30.1 reported no findings in the scanned candidate directory or the separately scanned original history (775 commits). Static privacy review found no remaining concrete production authority identifiers, private contacts or embedded credentials in the selected source. These are bounded checks, not a guarantee of secret absence, legal clearance or production security.

The retained screenshot is from the synthetic local preview. Its PNG contains only image/header/end chunks, with no text or EXIF metadata. New CI is read-only verification; it was inspected locally, not executed on a public repository. Licensing and publication authorization remain independent release gates.

## Three different meanings of success

| Layer | Useful evidence | Misleading substitute |
|---|---|---|
| Work executed | Claimed stage completed and expected output exists | Message accepted or HTTP request returned successfully |
| Publication completed | Dated artifacts, delivery ledger, live-date/content checks and terminal publication state | A green CI or publisher job |
| Information is useful | Relevant diverse sources, clear limitations and observed reader value | More rows, more tests or a sophisticated score |

Two incidents make the distinction concrete. The **October 2** pruning script reported accepted long-running operations as deletions although the operations had failed. The **October 9** attention shadow produced no records because its runner was absent from the image, while the publisher correctly continued. The latter demonstrates isolation—not successful research. No inspected acceptance report establishes that the subsequent planned shadow window completed successfully. [E17, E19](evidence.md)

## Product evaluation

The record contains publication, email delivery, signup implementation and customer-development plans. It does not establish sustained paid usage, retention, campaign outcomes or product-market fit. Prospects in private planning documents are not customers; role-framed investor critiques are not endorsements. October's cadence reduction is documented as a wind-down, not evidence of scale.

The portfolio conclusion is consequently specific: **NewsCloud demonstrates building and operating an evidence-bearing pipeline, correcting its failure modes, and narrowing claims responsibly. It does not demonstrate validated electoral prediction or an established business.**
