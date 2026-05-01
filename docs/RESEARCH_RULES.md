# Research rules (methodology guardrails)

These rules exist to keep the Kalshi **NO carry** study statistically honest and deployable without accidental leakage.

## Splitting and evaluation

1. **Chronological splits only.** Never shuffle rows that share a time axis; preserve causal ordering.
2. **Split by event cluster**, not by individual order-book snapshots. All observations from one cluster move together into train, validation, or test.
3. **Hold out the final 20% test set.** After it is locked, do not tune hyperparameters, thresholds, or strategy rules against it.
4. **Do not optimize after seeing the final test set.** Any change motivated by test performance voids the reported test metrics — treat it as exploratory only and re-collect / re-split if needed.

## Pricing, costs, and execution realism

5. **Use executable prices**, not last-trade prints, when simulating entries and exits (e.g., bid/ask or join-leave assumptions tied to depth).
6. **Include fees and spread** in all PnL and edge estimates. Prefer conservative fee models when uncertain.

## Market and legal / operational risk

7. **Avoid resolution-rule ambiguity** when possible; flag markets where interpretation risk dominates statistical signal (`features` / human review in future phases).
8. **Track correlated exposure** across clusters that respond to the same macro shock or overlapping information sets. Position sizing must respect joint risk, not per-market independence.

## Implementation hygiene

9. **No future information** in features or labels relative to the modeled decision timestamp (see module docstrings under `research/` when implemented).
10. **Configuration via environment variables** for credentials and deployment-specific paths — never commit secrets.

For engineering context, see `ARCHITECTURE.md`. For persisted tables (future), see `DATA_SCHEMA.md`.
