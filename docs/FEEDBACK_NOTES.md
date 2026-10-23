# Feedback Notes (honest engineering ledger)

Known gaps, design debts, and reviewer-facing answers. If a claim is not
in the README, tests, or `docs/BENCHMARK.md`, treat it as not implemented.

## Hackathon-round specifics

- **Demo mode cache replaces live calls**: in `DEMO_MODE=1` (the default
  in the container), the Nemotron advisory replies come from
  `data/logs/llm_answer_cache.json`. The cache is seeded only by real
  calls made by the maintainer's runs; a judge disabling demo mode and
  without a key gets deterministic behavior instead (`llm_provider:
  none` on `/health`). This is by design, not a hidden call path.
- **TigerGraph cloud vs local**: `GRAPH_BACKEND=local` runs the GSQL
  traversal logic against a SQLite store in the container. The Savanna
  Cloud instance (which idles after inactivity) is exercised in live
  mode; `/health` reports graph state and `graph_hint` when it is down.
- **SENTINEL vendored UI**: `sentinel-ui/` is an upstream's separate
  console vendored from an unlicensed source project; it is NOT wired to
  this backend and is excluded from our benchmark story
  (`sentinel-ui/NOTICE.md`). Public release preparation should likely
  drop this directory unless upstream attribution is resolved.

## Code-level debts

- `requirements.txt` contains a stray duplicate `httpx` and dev deps
  (`pytest`, `pytest-asyncio`) in the runtime list; the Docker image
  installs all of them.
- `backend/evaluation/run_benchmark.py` currently overwrites
  `artifacts/`-style answer files under `cases/` on every benchmark run
  (keeps the pack in sync; acceptable for the synthetic data contract).
- Legacy `LLM_PROVIDER` (anthropic/openai/groq) narrative path still
  exists (`backend/llm/client.py`-equivalent) alongside the Nemotron
  path; it is unused by the Nemotron advisory flow and should be retired
  or abstracted behind `roles.py` in a next version.
- Windows console shows mojibake for some Unicode box-drawing chars in
  docs; the repository text itself is UTF-8.
- The per-IP limiter keys on the request's client host; behind a shared
  NAT/proxy (e.g., judges on one hotspot) all traffic shares a bucket,
  bounded by the daily cap (see README §Limitations).

## Security / release prep

- The maintainer's `.env` (real `NEBIUS_API_KEY`) is gitignored; no
  secrets are committed. History scrubbing already rehearsed: any file
  with round-provided third-party data is filtered from all commits
  before the public push (final pass runs post-README, per plan).
- The public push should be preceded by a fresh `git log --all --full-history -- <paths>`
  check for: `data/prepared/*`, `data/full_load_staging/*`,
  `closed_cases_history.csv` (round-provided), and any earlier README
  versions (they traverse the same filter).

## Area still open

- Ultralarge reasoning models leak "chain-of-thought-like" preambles on
  Q&A; the `ANSWER:` marker contract plus markdown post-processing
  handles the current prompts, but sampling seeds/temperature still
  leave small nondeterminism in freetext answers (bounded by the
  advisory-only role).
