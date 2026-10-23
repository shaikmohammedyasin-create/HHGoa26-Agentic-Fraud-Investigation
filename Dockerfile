# HHGOA Agentic Fraud Investigation — single-container image.
# API-only single-container image; the Sentinel UI (sentinel-ui/) is a
# separate Next.js app.
#
# Judge-friendly defaults (this is a demo image):
#   - Only the publishable synthetic data is copied in (data/synthetic/).
#     The SQLite store (investigation.db) is rebuilt from the synthetic CSVs
#     in ~3 s at each container start.
#   - GRAPH_BACKEND=local (no TigerGraph cloud needed for the demo).
#   - DEMO_MODE defaults to 1: Nemotron answers are served from the local
#     answer cache so judges spend zero API credits unless they explicitly
#     opt into live mode with NEBIUS_API_KEY + DEMO_MODE=0/1-with-key.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY cases ./cases
COPY prompts ./prompts
COPY scripts ./scripts
COPY tigergraph ./tigergraph
COPY data/README.md data/README.md
COPY data/synthetic ./data/synthetic

# Synthetic CSVs are the data source inside the container.
ENV TRANSACTIONS_CSV=data/synthetic/transactions.csv \
    IDENTITY_CSV=data/synthetic/identity.csv \
    CLOSED_CASES_CSV=data/synthetic/closed_cases_history.csv \
    CASE_PACK_CSV=data/synthetic/case_pack.csv \
    GRAPH_BACKEND=local \
    DEMO_MODE=${DEMO_MODE:-1}

EXPOSE 8000

# Rebuild the prepared SQLite store from the synthetic CSVs, then serve.
# prepare_data is deterministic and takes seconds on the synthetic set.
CMD ["sh", "-c", "python -m backend.scripts.prepare_data && uvicorn backend.main:app --host 0.0.0.0 --port 8000"]
