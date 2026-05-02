# Research rules (methodology guardrails)

These rules exist to keep the Kalshi **NO carry** study statistically honest and deployable without accidental leakage.

## Leakage-safe clustering (v0.5)

1. **Cluster before splitting.** All markets that share the same Kalshi **`event_ticker`** belong to the **same** research cluster. Events and markets with matching `event_ticker` **merge** into one cluster.
2. **No randomness** in clustering or split assignment — both are **deterministic** for a fixed raw snapshot.
3. **Fallback keys** (when a market row lacks `event_ticker`) use `series_ticker` + normalized title material + date bucket so orphan markets still land in a **stable** cluster.
4. **Order clusters in time** using `event_clusters.close_time`, then `cluster_id`, before taking contiguous **60% / 20% / 20%** train / validation / test fractions (see `research.build_splits`).

## Splitting and evaluation

5. **Chronological splits only.** Never shuffle rows that share a time axis; preserve causal ordering. **`strategy_splits`** rows are keyed by **`(cluster_id, split_version)`** (v0.5.1+), so multiple split policies can coexist for the same clusters. Treat each `split_version` as a fixed line of research once it has informed strategy selection; use **`overwrite=True`** in `assign_chronological_splits` only for deliberate rebuilds of **that** version, not for casual edits.
6. **Split by event cluster**, not by raw row, individual market refresh, or orderbook snapshot. Assigning each snapshot independently would **split structurally identical markets** across sets and **leak** information between train and test.
7. **Why row- or snapshot-level splits are forbidden:** correlated outcomes, shared resolution, and shared information arrive at the **event** level. A model must not see any held-out event’s structure or labels via a sibling market or later snapshot that still belongs to a training cluster.
8. **Hold out the final ~20% test set (chronological tail).** After it is **sealed**, do not tune hyperparameters, thresholds, or strategy rules against it.
9. **Strategy iteration** must use **train + validation only.** Treat the **final test** like a one-time audit: open it **at most once per frozen strategy** when reporting definitive performance. Downstream backtests and notebooks should require an **explicit flag** to score on final test (not implemented in v0.5).
10. **Do not optimize after seeing the final test set.** Any change motivated by test performance voids the reported test metrics — treat it as exploratory only and re-collect / re-split if needed.

## Pricing, costs, and execution realism

11. **Use executable prices**, not last-trade prints, when simulating entries and exits (e.g., bid/ask or join-leave assumptions tied to depth).
12. **Include fees and spread** in all PnL and edge estimates. Prefer conservative fee models when uncertain.

## Market and legal / operational risk

13. **Avoid resolution-rule ambiguity** when possible; flag markets where interpretation risk dominates statistical signal (`features` / human review in future phases).
14. **Track correlated exposure** across clusters that respond to the same macro shock or overlapping information sets. Position sizing must respect joint risk, not per-market independence.

## Implementation hygiene

15. **No future information** in features or labels relative to the modeled decision timestamp (see module docstrings under `research/` when implemented).
16. **Configuration via environment variables** for credentials and deployment-specific paths — never commit secrets.

For engineering context, see `ARCHITECTURE.md`. For table-level details, see `DATA_SCHEMA.md`.
