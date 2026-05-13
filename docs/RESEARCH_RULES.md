# Research rules

Methodology guardrails for the Kalshi **NO carry** study: keep statistics honest, prevent train/test leakage, and keep deployment and evaluation disciplined.

> [!NOTE]
> These rules complement the engineering docs. They do not replace careful review when changing splits, labels, or strategy code.

## Table of Contents

- [Leakage-safe clustering (v0.5)](#leakage-safe-clustering-v05)
- [Splitting and evaluation](#splitting-and-evaluation)
- [Pricing, costs, and execution realism](#pricing-costs-and-execution-realism)
- [Market and legal or operational risk](#market-and-legal-or-operational-risk)
- [Implementation hygiene](#implementation-hygiene)
- [Feature engineering dataset (v0.6)](#feature-engineering-dataset-v06)
- [Read-only backtesting (v0.7)](#read-only-backtesting-v07)
- [Outcome labeling (v0.8)](#outcome-labeling-v08)
- [Research pipeline runner (v0.9)](#research-pipeline-runner-v09)
- [Research audit reports (v0.10)](#research-audit-reports-v010)
- [Collectors and CI (v0.11)](#collectors-and-ci-v011)
- [Executable quotes and modeling prerequisites (v0.12)](#executable-quotes-and-modeling-prerequisites-v012)
- [Persisted backtest idempotency (v0.12)](#persisted-backtest-idempotency-v012)
- [Public repository alpha hygiene (v0.13)](#public-repository-alpha-hygiene-v013)
- [Public deployment and infrastructure (v0.14)](#public-deployment-and-infrastructure-v014)
- [Market lifecycle refresh (v0.15)](#market-lifecycle-refresh-v015)
- [Connectivity diagnostics (v0.16)](#connectivity-diagnostics-v016)
- [Related documentation](#related-documentation)


## Leakage-safe clustering (v0.5)

1. **Cluster before splitting.** Markets that share the same Kalshi `event_ticker` belong to one research cluster. Events and markets with matching `event_ticker` merge into a single cluster.
2. **No randomness** in clustering or split assignment—both are **deterministic** for a fixed raw snapshot.
3. **Fallback keys** (when a market row lacks `event_ticker`) use `series_ticker`, normalized title material, and a date bucket so orphan markets still land in a **stable** cluster.
4. **Order clusters in time** using `event_clusters.close_time`, then `cluster_id`, before taking contiguous **60% / 20% / 20%** train, validation, and test fractions (see `research.build_splits`).


## Splitting and evaluation

5. **Chronological splits only.** Do not shuffle rows that share a time axis; preserve causal ordering. `strategy_splits` rows are keyed by `(cluster_id, split_version)` (v0.5.1+), so multiple split policies can coexist. Treat each `split_version` as a fixed line of research once it has informed strategy selection; use `overwrite=True` in `assign_chronological_splits` only for deliberate rebuilds of **that** version.
6. **Split by event cluster**, not by raw row, individual market refresh, or orderbook snapshot. Per-snapshot assignment would split structurally identical markets across sets and **leak** information between train and test.
7. **Why row- or snapshot-level splits are forbidden:** correlated outcomes, shared resolution, and shared information arrive at the **event** level. A model must not see any held-out event’s structure or labels via a sibling market or a later snapshot that still belongs to a training cluster.
8. **Hold out the final ~20% test set (chronological tail).** After it is **sealed**, do not tune hyperparameters, thresholds, or strategy rules against it.
9. **Strategy iteration** must use **train and validation only.** Treat the **final test** like a one-time audit: open it **at most once per frozen strategy** when reporting definitive performance. Downstream backtests and notebooks should require an **explicit flag** to score on final test (not implemented in v0.5).
10. **Do not optimize after seeing the final test set.** Any change motivated by test performance voids the reported test metrics—treat it as exploratory only and re-collect or re-split if needed.


## Pricing, costs, and execution realism

11. **Use executable prices**, not last-trade prints, when simulating entries and exits (for example bid/ask or join-leave assumptions tied to depth).
12. **Include fees and spread** in all PnL and edge estimates. Prefer conservative fee models when uncertain.


## Market and legal or operational risk

13. **Avoid resolution-rule ambiguity** when possible; flag markets where interpretation risk dominates statistical signal (`features` or human review in future phases).
14. **Track correlated exposure** across clusters that respond to the same macro shock or overlapping information sets. Position sizing must respect joint risk, not per-market independence.


## Implementation hygiene

15. **No future information** in features or labels relative to the modeled decision timestamp (see module docstrings under `research/` when implemented).
16. **Configuration via environment variables** for credentials and deployment-specific paths—never commit secrets.


## Feature engineering dataset (v0.6)

17. **Causal timestamp:** feature rows use only information available at or before `fetched_at` (snapshot time). **Settlement and outcome** must **not** be used as model inputs; when stored for backtests, use the `label_` prefix (for example `label_market_result`).
18. **Sealed test default:** `scripts/build_features.py` exports **train and validation only** by default. The **test** split is included **only** with an explicit `--include-test` flag—treat that as a **dangerous, audited** action.
19. **Frozen feature versions:** once a `feature_version` feeds model or strategy work, do not silently overwrite those rows; bump `feature_version` when definitions change.
20. **Not a strategy:** engineered rows include NO-carry *scaffolding* (prices, spreads, fee-adjusted breakeven probabilities) but **no** realized edge, PnL, or order simulation.


## Read-only backtesting (v0.7)

21. **Train and validation by default:** `scripts/run_backtest.py` mirrors feature export defaults—**test is excluded** unless `--include-test`. Treat that flag like a sealed envelope: document why it was used.
22. **No peeking for tuning:** iterate thresholds and rules on **train and validation** only. After you have looked at **test** results for a configuration, **do not** retroactively tune that same `backtest_version` to fit test—bump `backtest_version` and treat prior numbers as exploratory if you change rules after seeing test.
23. **Frozen inputs:** tie every run to explicit `feature_version` and `split_version`. Do not silently mix feature definitions in one reported run.
24. **Labels only for scoring:** `label_*` fields (for example `label_market_result`) may inform **hypothetical** PnL after resolution; they must **not** be fed as inputs to entry rules in this baseline (no outcome leakage into “features” at decision time).


## Outcome labeling (v0.8)

25. **Unknown beats wrong:** if API fields are missing, conflicting, or ambiguous, normalize to `unknown` (or `void` only when status or result clearly indicates cancel or void). Never infer winners from **title**, subtitle, or price history in `research/outcomes.py`.
26. **Versioned extraction:** each row in `research_market_labels` carries `label_version`. Changing extraction rules requires a **new** `label_version`; old rows stay for audit.
27. **Scoring only on feature rows:** `label_*` columns (including merged `outcome_label_version`) exist for **backtests and coverage metrics**, not for candidate selection or executable quote math.
28. **Sealed test:** `build_labels`, `audit_research_dataset`, `build_features`, `run_backtest`, `run_research_pipeline`, and `run_research_report` all treat the test split as **opt-in** (explicit flags), consistent with v0.6 and v0.7.


## Research pipeline runner (v0.9)

29. **Orchestration only:** `scripts/run_research_pipeline.py` and `research.pipeline_runner` coordinate **read-only** research steps. They **do not** replace methodology discipline: you must still avoid tuning on the sealed **test** split and must not treat `next_recommended_action` as permission to trade.
30. **No “optimize until test looks good”:** running the pipeline repeatedly with `--include-test` to tweak strategy inputs until test metrics improve **voids** honest test claims—the runner cannot detect gaming; authors and reviewers must enforce these rules manually.
31. **`next_recommended_action`:** heuristic offline hints only (coverage, labels, features). It must **never** suggest **live trading**, execution, or deploying real capital—only research data work or read-only analysis.


## Research audit reports (v0.10)

32. **Summarize train and validation by default:** `report.md` and `summary.json` from `run_research_report.py` follow pipeline defaults—**test excluded** unless `--include-test`. Use reports for coverage and readiness, not for secret test peeking during iteration.
33. **Explicit test reports:** a report generated with `--include-test` is a **final sealed-evaluation style** artifact—document why it was produced; do **not** tune parameters afterward to “fit” that report without re-splitting and a new protocol.
34. **No test tuning:** reports **must not** be used to adjust strategy thresholds or rules specifically to improve **test** metrics; iterate only on train and validation and treat test as locked.
35. **No live-trading advice:** readiness verdicts and Markdown sections **must never** recommend **live trading** or capital deployment—they describe offline data sufficiency only.
36. **No phantom edge:** reports **must not** claim exploitable edge; hypothetical backtest PnL is clearly labeled simulation and may be **zero unscored** when labels are missing.
37. **Dry-run is non-mutating:** `scripts/run_research_report.py --dry-run` must **not** alter `research_market_labels`, `research_feature_rows`, `strategy_splits`, clusters, `backtest_runs`, `backtest_trades`, or run **migrations** or `create_all`. It is safe to run repeatedly against a shared research database.
38. **Report previews are safe:** use `--dry-run` for repeated “what is the dataset state?” checks; only a **non–dry-run** report run may request pipeline materialization and write artifacts under `reports/`.


## Collectors and CI (v0.11)

39. **No live Kalshi in default tests:** collector and pipeline **integration tests** must **mock** HTTP or client calls or use **fakes**. The default **`pytest`** suite **must not** require network access or Kalshi availability. Optional manual “public data smoke” runs are documented in `README.md` only.


## Executable quotes and modeling prerequisites (v0.12)

40. **Never fabricate executable prices:** if orderbook bids are missing or the book is empty, `no_ask_cents` and related fields stay `null`; do not infer from titles, last trade, or unrelated markets.
41. **Kalshi-implied asks from bids only:** executable **NO ask** cents = **100 − best YES bid** cents; executable **YES ask** cents = **100 − best NO bid** cents, using the **best** (highest) bid level per side per API ordering.


## Persisted backtest idempotency (v0.12)

42. **No manual DB cleanup for reruns:** when `run_no_carry_backtest_persisted` writes `backtest_runs` and `backtest_trades`, repeating the **same** configuration must **not** require deleting rows by hand. The harness replaces the prior deterministic `run_id` in one transaction instead of failing on a unique constraint.
43. **Fix extraction before modeling:** if `audit_orderbook_prices.py` shows raw books support implied asks but `research_feature_rows` lack `no_ask_cents`, treat that as a **data pipeline bug** to fix (re-ingest or rebuild features)—not as a signal to patch models around bad rows.


## Public repository alpha hygiene (v0.13)

44. **No proprietary strategy selection in public code:** this repository must **not** encode alpha-specific market picking, profitable category filters, threshold tuning hooks marketed as “best,” or secret ranking or scoring rules intended only for production trading research.
45. **Generic coverage tooling only:** CLI flags such as `--market-status`, `--collect-status-set`, and `--orderbook-source-status` exist to widen **honest offline dataset coverage** (status mixes, liquidity diagnostics). They must **not** be repurposed as thin wrappers around undisclosed edge logic.
46. **Private alpha stays private:** strategy-specific modules, tuned parameters, and proprietary notebooks belong in **ignored local paths** or a **private repository**; wire them only through **explicit local imports** or documented extension points—never commit them here.


## Public deployment and infrastructure (v0.14)

47. **Public deployment configs must not contain secrets:** committed templates use **placeholders** only; real `DATABASE_URL`, API identifiers, and key paths live in **ignored** env files on the host.
48. **Scheduled jobs must remain read-only:** default systemd templates invoke **ingest** and **stored-data report** CLIs only—**no** order placement, portfolio management, or execution paths.
49. **Scheduled jobs must use generic coverage collection only:** committed units use **public** flags (for example status-set presets)—**not** proprietary market-selection or edge filters.
50. **Private alpha modules must not be referenced in public systemd units:** wire private logic only through **local** wrappers or configs outside this repository.
51. **Deployment docs must use placeholders** for credentials, hosts, and paths—never copy live infrastructure identifiers into git.
52. **Generated reports, logs, and generated `build/` outputs must not be committed** unless explicitly sanitized for sharing.
53. **Deployment infrastructure must not reveal** alpha-sensitive strategy timing, filters, thresholds, or signal logic—keep tuning and selection in **private** research workflows.


## Market lifecycle refresh (v0.15)

54. **Lifecycle state only:** refresh candidate selection may use **generic** stored facts (for example: tickers with orderbook snapshots, missing or non-definitive labels, unsettled-looking statuses). It must **not** encode proprietary **edge**, **category profitability**, **threshold tuning**, or **strategy timing** heuristics in this public repository.
55. **Ticker refresh scope:** public refresh jobs should target **previously observed markets** (stored tickers) or **explicit user-supplied tickers**—not undisclosed “alpha baskets.”
56. **No outcome inference:** lifecycle refresh **updates `raw_markets`** only; labels still come from `research/outcomes.py` rules—**never** infer outcomes from **titles** or **current price**.
57. **Extension points:** private repos may plug in additional selection or filtering **locally**; keep such logic out of committed public modules, docs, and systemd templates.
58. **Read-only network:** lifecycle refresh uses `GET /markets` (including optional batched `tickers` query) and `GET /markets/{ticker}` fallback only—**no** orders, **no** portfolio mutations.
59. **Batch refresh is not selection:** batched `/markets?tickers=` calls reduce round-trips only; they must **not** be used in public code to encode **ranking**, **profit filters**, or proprietary **market baskets**—keep selection logic generic (lifecycle or label state) or **private and off-repo**.


## Connectivity diagnostics (v0.16)

60. **Read-only endpoints only:** connectivity diagnostics must call **GET** exchange status, listings, and per-market reads only. They must **not** invoke order placement, **not** call portfolio, balance, fills, or positions routes, and must **not** become a trading or execution surface.
61. **Redact secrets and paths:** diagnostics output must remain **sanitized** (for example: boolean flags for credential presence, scheme and host for API hosts) and must **not** echo raw `DATABASE_URL`, API key material, PEM contents, full private filesystem paths, or entire `.env` payloads.
62. **Not strategy selection:** connectivity diagnostics answer **reachability, timeouts, and config sanity** only. They must **not** encode proprietary **market-selection** rules, **not** validate predictive models, and must **not** act as “alpha checks” for strategies.


## Related documentation

- **Engineering context:** [`ARCHITECTURE.md`](ARCHITECTURE.md)
- **Table-level detail:** [`DATA_SCHEMA.md`](DATA_SCHEMA.md)
