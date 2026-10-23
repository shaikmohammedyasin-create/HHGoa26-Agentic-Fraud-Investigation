# Changelog

All notable changes to this project. Dates use YYYY-MM-DD.

## 2026-10-23 — Hackathon submission build (Nebius x NVIDIA Token Factory)

### Added
- **NVIDIA Nemotron integration via Nebius Token Factory**
  - Native Token Factory client (`backend/llm/nebius_client.py`): OpenAI-compatible chat completions with 30 s timeout, 2 retries, and an explicit fail-soft `None` contract — LLM outages never degrade the API.
  - Four advisory roles (`backend/llm/roles.py`): pattern classifier (proposes fraud pattern with evidence citations), verification request drafter, narrative + SAR drafter, analyst Q&A. Tiered: Nano for roles 1–2, Ultra for roles 3–4.
  - Prompt files under `prompts/` with prompt-injection rejection and evidence-id grounding contracts (enforced by tests).
  - `Nemotron Advisory` tab in the dashboard: proposal vs policy decision with agree/overruled badges, verification drafts, SAR "Part II: Nemotron draft" tagging, and an ask-a-question box.
  - `POST /investigations/{case_id}/ask` and `GET /api/llm/status` endpoints (the latter exposes calls, tokens, and p50/p95 latency from the JSONL call log).
  - Propose/decide separation recorded on every completed case: `model_proposal` vs `policy_decision`, `model_agreed`, `model_override_reason`.
- **Demo & cost governance**
  - Demo answer cache (`DEMO_MODE=1`): zero-credit replays, no key needed.
  - Per-IP hourly limiter (429) and global daily cap (deterministic fallback) on Nemotron-spending endpoints.
  - `/health` gains `demo_mode` and `graph_hint` fields; dashboard shows a demo banner.
- **Evaluation**
  - `scripts/eval_heldout.py`: fixed-seed (20261030) held-out harness — engine fidelity vs ground truth, risk-threshold baseline sweep, plain-LLM-no-graph ablation, propose/decide agreement, and Token Factory cost/latency stats.
  - `scripts/smoke_nemotron.py`: one live call per role; verified all four roles against the actual endpoint (model ids verified, including the `nvidia/Nemotron-3-Ultra-550b-a55b` casing).
  - 11 new mocked Nemotron role tests (`tests/integration/test_nemotron_roles.py`); CI runs fully offline (conftest clears `NEBIUS_API_KEY`).
- **Deployment**
  - `docker-compose.yml` + hardened `Dockerfile`: single-container app served with the synthetic-data-only image (SQLite store rebuilt in ~3 s at start), demo mode on by default, `NEBIUS_API_KEY` optional.
  - `.dockerignore` preventing local datasets/secrets from entering images.
  - [`docs/DEPLOY.md`](DEPLOY.md) and [`docs/BENCHMARK.md`](BENCHMARK.md); README rewritten with a 5-minute quickstart, a Nemotron/Token Factory section, and honest limitation notes.
- Maintenance scripts: `scripts/wake_graph.py` (poll until the cloud graph wakes) and refreshed benchmark answer pack.

### Changed
- Benchmark answer pack regenerated with the proposal/decide fields present on completed cases.
- README test badge updated (278 passed / 9 skipped); removed stale repo-name note.

### Data governance
- All published evaluation data is generated in-repo by
  `scripts/make_synthetic_data.py` (synthetic; no third-party rows).
  Round-provided third-party CSVs and derived SQLite stores remain
  local-only (gitignored) and are scheduled for full git-history
  scrubbing before the public push.
