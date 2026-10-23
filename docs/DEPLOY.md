# Deployment

## Quickstart (judges, no credentials needed)

```bash
git clone <repo-url>
cd <repo>
docker compose up --build
# open http://localhost:8008
```

What you get in under 5 minutes:

- The FastAPI backend serves the full investigation dashboard (frontend is
  static, part of the same container).
- Approximately 3 s after start, `prepare_data` rebuilds the SQLite graph
  store from the publishable synthetic CSVs (`data/synthetic/`) — 12,235
  transactions, 4,201 identity records, 28 closed cases, 20 investigation
  cases. No third-party data is used anywhere.
- `GRAPH_BACKEND=local`: TigerGraph's traversal logic runs against the
  local SQLite store. The cloud TigerGraph instance is an option, not a
  dependency for the demo.
- **Demo mode is the default (`DEMO_MODE=1`)**: no `NEBIUS_API_KEY` is
  required, and no Token Factory credit is spent. Nemotron answers replay
  from the local answer cache (`data/logs/llm_answer_cache.json`), and the
  deterministic policy engine always produces the final decisions.

## live mode (optional — real Nemotron calls)

```yaml
# docker-compose.yml
environment:
  DEMO_MODE: "0"                      # or 1 to keep the cache active
  NEBIUS_API_KEY: "your-nebius-api-key"
```

Live mode still has protections on by default (see below). Model tiers used:

| Role | Tier | Model id |
|---|---|---|
| Pattern proposal (role 1) | Nano | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` |
| Verification draft (role 2) | Nano | same |
| Narrative / SAR draft (role 3) | Ultra | `nvidia/Nemotron-3-Ultra-550b-a55b` |
| Analyst Q&A | Ultra | same |

(The model ids are as verified against the Nebius Token Factory endpoint in
October 2026. The base URL and models are set in `.env.example`.)

## Built-in cost protections (live mode)

| Mechanism | Default | Config |
|---|---|---|
| Per-IP hourly limiter | 20 calls / IP / hour | `LLM_CALLS_PER_IP_PER_HOUR` |
| Global daily cap | 200 calls / day, then deterministic-only | `LLM_DAILY_CALL_CAP` |
| Demo answer cache | unlimited replay, zero credits | `DEMO_MODE=1` |
| Call log | JSONL, one row per call | `/api/llm/status` |

## Local (no Docker) quickstart

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt   # Windows: .venv\Scripts\...
python -m backend.scripts.prepare_data                # build the SQLite store
uvicorn backend.main:app --port 8008                  # serve API + dashboard
```

Environment variables are documented in `.env`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/health` reports `graph` unhealthy in cloud mode | The defense has a `graph_hint` on `/health` and `scripts/wake_graph.py` polls until the TS suspend-wake completes. Demo/local graph (default in the container) is always healthy. |
| Nemotron answers show `cache-replay` | Demo mode; expected. Set `DEMO_MODE=0` + key for fresh calls. |
| `daily credit cap reached` responses | Capped at `LLM_DAILY_CALL_CAP` calls; the app keeps running deterministically. |
| Port busy | `ports: "9000:8000"` in compose, then open `:9000`. |
