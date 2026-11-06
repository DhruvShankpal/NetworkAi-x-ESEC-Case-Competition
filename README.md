# NetworkAi-x-ESEC-Case-Competition

## Series Desk: burglary case linkage for detectives

Prototype for the Cascade City burglary case (stage 6, detective follow-up). For each new burglary, Series Desk
shows the 3 most likely linked cases with plain-language reasons; a detective accepts or rejects every link.

- **Linkage is statistics, not an LLM:** logistic regression over distance, time, rarity-weighted MO overlap and
  "closest neighbour" ranks (`backend/seriesdesk/linkage.py`, `ranking.py`). Per-fact contributions are exact.
- **Tested on real LAPD data** (MO codes, locations, times; injected series), leave-one-year-out 2020–2023:
  hit@3 92% (88–94%) vs 36% for a standard model; hit@1 72% vs 20% (`eval/multiyear.py`).
- **Business case** (cost-benefit, clearance logic, pilot): `docs/business-case.html`, numbers from `eval/business_case.py`.
- **Guardrails:** read-only DB roles, append-only hash-chained audit log, citation verifier, no demographics as features,
  no facial recognition. Project rules: `CLAUDE.md`.

### Run it
```
uv sync
./db/setup_local.sh                      # Postgres 16 + PostGIS; needs .env (copy .env.example)
uv run pytest -q                         # 73 tests
uv run python scripts/pull_lapd.py --start 2023-04-01 --end 2023-11-30
uv run python eval/multiyear.py          # slow: builds ~2M candidate pairs per year
uv run python eval/business_case.py
```
All metrics are on public data with injected (synthetic) series; see the business case for limits.
