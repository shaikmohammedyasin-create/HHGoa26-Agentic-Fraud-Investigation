# Data directory

This project was built on the fraud-detection dataset provided for the
TigerGraph hackathon round (an IEEE-CIS–derived corpus: `transactions.csv`,
`identity.csv`, `closed_cases_history.csv`, `case_pack.csv`).

**The round-provided dataset is NOT redistributed in this repository.** We do
not have confirmed redistribution rights for it, so none of the original CSVs
(or prepared SQLite views derived from them) are committed to git, and they
must not be re-added. Each file's root copy is local-only and gitignored.

## What is published instead

- `data/synthetic/` — a small, fixed-seed, fully synthetic dataset generated
  by `scripts/make_synthetic_data.py`. It contains normal transaction flows
  plus planted fraud rings (circular transfers, shared-device bursts,
  multi-account clusters) **with ground-truth labels by construction**. The
  precomputed `cases/CASE-*.json` investigations are regenerated from this
  synthetic data, so the whole demo runs without any third-party data or
  external credentials.
- `data/prepared/investigation.db` — the local SQLite graph store, built from
  whichever CSVs are configured (see below). Large, generated, gitignored.

## How to obtain the original round data (for contributors)

Request it through the TigerGraph hackathon platform where the round data
package was distributed. After downloading, place the four CSVs at the
repository root, then:

```
python -m backend.scripts.prepare_data     # builds data/prepared/investigation.db
```

## Synthetic-only run (no third-party data, judges path)

```
python scripts/make_synthetic_data.py      # writes data/synthetic/*.csv
set TRANSACTIONS_CSV=data/synthetic/transactions.csv
set IDENTITY_CSV=data/synthetic/identity.csv
set CLOSED_CASES_CSV=data/synthetic/closed_cases_history.csv
set CASE_PACK_CSV=data/synthetic/case_pack.csv
python -m backend.scripts.prepare_data
```

Or simply run the app with `DEMO_MODE=1`, which serves the precomputed
case results in `cases/` and needs no dataset at all.
