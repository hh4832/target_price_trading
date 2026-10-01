# AGENTS.md --- target_price_trading

## Repository purpose

This repository studies broker target-price reports as a research
candidate-selection and forward-outcome pipeline.

Current thresholds are research hypotheses, not validated trading rules.
`CANDIDATE` is not a buy recommendation.

## Inherited engineering rules

Follow the project's general quant-pipeline rules: audit repository
state before changes; Python 3.11; GitHub as code source of truth; no
secret hard-coding; explicit typed boundaries; backward-compatible
schema handling; idempotent state; no silent coercion; one core change
at a time; test before commit/push.

## Research invariants

Do not alter merely to repair engineering failures:

-   target upside threshold (>30%)
-   report-age rule (≤90 calendar days)
-   latest report selection by ticker × broker
-   `NEW_REPORT_CANDIDATE`
-   `THRESHOLD_CROSSING`
-   corporate-action target adjustment semantics
-   raw close used for screening denominator
-   adjusted-price outcome semantics
-   O1→C5/C10/C20/C60 definitions
-   0050 comparison logic
-   research-summary evidence thresholds

Any requested research-rule change must be isolated from engineering
fixes and retested separately.

## External-input contract

The manually maintained Google Sheet is source input. Do not delete,
rewrite, normalize in-place, or silently repair user-entered reports.

Required report fields and optional fields must be validated at the
input boundary.

Ticker/security identifiers are strings, never numeric IDs. Preserve
leading zeroes such as `0050`.

Persistent CSV readers must specify identifier dtype explicitly. Do not
rely on pandas inference.

For optional numeric fields:

-   `None`, `NaN`, `""`, whitespace → missing
-   missing ≠ zero
-   malformed nonblank numeric text → explicit failure with diagnostic

For dates:

-   parse explicitly
-   distinguish report date, market date, first-seen timestamp, and
    execution timestamp
-   do not infer an unavailable publication timestamp

## Persistent-state model

These concepts are separate:

1.  Execution archive: one immutable snapshot per pipeline execution.
2.  Market state: last formally processed FinLab market date.
3.  Current/root outputs: latest complete successful execution.
4.  Signal ledger: cumulative immutable business events with idempotent
    keys.
5.  Report registry: first-seen/provenance state.

Never use one as a substitute for another.

`Archive tracks execution; state tracks FinLab market date.`

Every execution creates a timestamped archive, including
`DATA_NOT_UPDATED` runs.

A same-market-date rerun:

-   must not create duplicate business signals
-   must not falsely advance market state
-   may republish current outputs only after a complete successful
    execution
-   must preserve immutable prior archives

## State continuity

Before processing a new market date, validate that persistent state is
internally consistent.

For example, `state.json.last_successful_market_date` and the market
date represented by `last_screen.csv` must agree according to the
repository contract.

Missing, empty, multi-date, malformed, or contradictory state must fail
loudly. Do not silently reconstruct continuity unless an explicit
recovery/migration task authorizes it.

Do not partially advance state after a failed run.

## DATA_NOT_UPDATED contract

`DATA_NOT_UPDATED` is a valid execution state, not an exception and not
equivalent to skipping the pipeline.

The code path must still have all execution-scoped variables initialized
before branch-specific logic uses them.

Every branch that writes `run_info`, archive metadata, current outputs,
or audit information must receive explicit execution context rather than
relying on variables initialized only in another branch.

Regression tests must execute the full `DATA_NOT_UPDATED` path, not only
unit-test helper functions.

## FinLab price-data contract

Do not forward-fill missing prices.

Missing required execution/outcome price data must remain `PENDING`
where semantically appropriate or fail according to the existing
contract.

Keep raw screening prices and adjusted outcome prices conceptually
separate.

When diagnosing FinLab discrepancies, diagnostics may report dataset
shape, date coverage, ticker membership, dtype, and exact-cell state,
but diagnostics must not alter the data or research result.

## Corporate actions

Original target price is immutable source data.

`effective_target_price` may change only through the repository's
explicit classified corporate-action rules.

Do not infer an unclassified split/reverse split merely to make prices
align. Existing anomaly detection is a warning/failure mechanism, not
permission to mutate source data.

## Report registry and signal identity

`ticker + broker + report_date` is the immutable report key unless an
explicit migration changes the contract.

`first_seen_at` is provenance. Reruns must not rewrite it.

Signal IDs must remain idempotent. Persistent >30% status alone must
not emit a new crossing on every rerun.

Keep `NEW_REPORT_CANDIDATE` and `THRESHOLD_CROSSING` separate because
they represent different market mechanisms.

## Output/archive contract

Do not overwrite old timestamped archives.

A formal archive should remain traceable to the exact Git commit and
execution timestamp and contain the repository's required
snapshots/results/run metadata.

Do not commit generated datasets, credentials, `.env`, tokens, or large
output artifacts unless the repository explicitly requires them.

## Minimum regression tests for state/data bugs

Cover applicable cases:

-   ticker `"0050"` survives CSV round-trip unchanged
-   numeric-looking ticker remains a string
-   optional blank numeric cells remain missing, not zero
-   malformed required value fails loudly
-   same market date rerun is idempotent
-   `DATA_NOT_UPDATED` completes a full archive without advancing market
    state
-   new market date advances state exactly once
-   failed execution does not partially advance state
-   report `first_seen_at` is immutable
-   persistent candidate does not create duplicate signal
-   threshold re-crossing creates the intended new event
-   missing price is not forward-filled
-   archive path is unique and old archive is not overwritten

## Research conclusion

Until sufficient actual forward outcomes and robustness analyses exist,
the strategy conclusion remains:

`修改後再測`
