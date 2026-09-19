# Development

## Prerequisites

- Python 3.11+
- The four CSVs and `README.md` at the repository root
- Optional: TigerGraph Savanna or Community Edition
- Optional: `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` for narrative synthesis

## Setup

```bash
python -m venv .venv
# Windows Git Bash:
source .venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env
```

## Prepare investigation tables

This reads `transactions.csv` + `identity.csv` + closed cases + case pack, derives `card_id`, and writes `data/prepared/investigation.db`.

```bash
python -m backend.scripts.prepare_data
```

Expect a few minutes. Re-runs are idempotent (rebuilds the prepared DB).

## Run the API

```bash
uvicorn backend.main:app --reload --port 8000
```

OpenAPI: `http://127.0.0.1:8000/openapi.json`  
Docs: `http://127.0.0.1:8000/docs`  
Health: `http://127.0.0.1:8000/health`

## Run one investigation

```bash
curl -X POST http://127.0.0.1:8000/investigations \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-HHG-001" \
  -d "{\"case_id\": \"HHG-001\"}"
```

Or run the pack:

```bash
python -m backend.evaluation.run_benchmark
```

Writes `cases/HHG-001.json` … `cases/HHG-020.json`.

## Tests

```bash
pytest tests/unit -q
pytest tests/integration -q
pytest tests/e2e -q
```

Unit tests do not require the 708 MB CSV. Integration/e2e need `data/prepared/investigation.db`.

## TigerGraph (optional)

1. Create a workspace at https://savanna.tgcloud.io or install Community Edition.
2. Set `TG_HOST`, `TG_GRAPH`, `TG_USERNAME`, `TG_PASSWORD` (or token) in `.env`.
3. `python -m backend.scripts.install_schema`
4. `python -m backend.scripts.load_graph`
5. `GRAPH_BACKEND=tigergraph`

GSQL lives in `tigergraph/`. MCP: follow https://github.com/tigergraph/tigergraph-mcp and set `MCP_URL`.

## Modes

`APP_ENV=development|benchmark|production`

- `development` allows the local graph store.
- `production` refuses to start without TigerGraph health = ok (see `backend/config.py`).
- Benchmark always uses the same orchestrator; it never special-cases `HHG-*` IDs.
