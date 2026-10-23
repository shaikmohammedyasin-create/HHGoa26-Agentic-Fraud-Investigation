"""Central configuration loaded from .env / environment variables."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    app_env: Literal["development", "benchmark", "production"] = "development"
    log_level: str = "INFO"

    # ── Graph backend ────────────────────────────────────────────────────────
    graph_backend: Literal["local", "tigergraph"] = "local"
    strict_graph_backend: bool = False

    # ── TigerGraph ───────────────────────────────────────────────────────────
    # Both the short TG_* names and the canonical TIGERGRAPH_* names are
    # accepted; .env.example documents the canonical form.
    tg_host: str = Field("", validation_alias=AliasChoices("TG_HOST", "TIGERGRAPH_HOST"))
    tg_graph: str = Field("fraud_investigation", validation_alias=AliasChoices("TG_GRAPH", "TIGERGRAPH_GRAPH"))
    tg_username: str = Field("", validation_alias=AliasChoices("TG_USERNAME", "TIGERGRAPH_USERNAME"))
    tg_password: str = Field("", validation_alias=AliasChoices("TG_PASSWORD", "TIGERGRAPH_PASSWORD"))
    tg_secret: str = Field("", validation_alias=AliasChoices("TG_SECRET", "TIGERGRAPH_SECRET"))
    tg_token: str = Field("", validation_alias=AliasChoices("TG_TOKEN", "TIGERGRAPH_TOKEN"))
    tg_port: int = Field(443, validation_alias=AliasChoices("TG_PORT", "TIGERGRAPH_PORT"))
    tg_protocol: str = Field("https", validation_alias=AliasChoices("TG_PROTOCOL", "TIGERGRAPH_PROTOCOL"))

    # ── MCP ──────────────────────────────────────────────────────────────────
    mcp_url: str = ""

    # ── LLM ──────────────────────────────────────────────────────────────────
    llm_provider: Literal["anthropic", "openai", "groq", "none"] = "none"
    anthropic_api_key: str = ""
    llm_model: str = "claude-haiku-4-5-20251001"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    llm_timeout_seconds: int = 30
    llm_temperature: float = 0.1

    # ── Data paths ───────────────────────────────────────────────────────────
    data_dir: Path = ROOT / "data"
    prepared_db: Path = ROOT / "data" / "prepared" / "investigation.db"
    app_db: Path = ROOT / "data" / "app" / "app.db"
    cases_dir: Path = ROOT / "cases"

    # Source CSVs (relative to repo root)
    transactions_csv: Path = ROOT / "transactions.csv"
    identity_csv: Path = ROOT / "identity.csv"
    closed_cases_csv: Path = ROOT / "closed_cases_history.csv"
    case_pack_csv: Path = ROOT / "case_pack.csv"

    # ── Investigation limits ──────────────────────────────────────────────────
    max_investigation_steps: int = 25
    max_evidence_requests: int = 3
    fraud_prob_stop_high: float = 0.85
    fraud_prob_stop_low: float = 0.15
    min_evidence_for_stop: int = 2

    # ── Agentic evidence loop ────────────────────────────────────────────────
    # how: simulated  = agent fabricates a documented synthetic response
    #      (benchmark default; flagged as simulated in evidence provenance)
    #      human_in_loop = investigation pauses in MORE_EVIDENCE_REQUIRED and
    #      waits for POST /investigations/{id}/evidence; the UI can supply the
    #      customer / step-up / analyst response.
    evidence_request_mode: Literal["simulated", "human_in_loop"] = "simulated"
    # Minimum expected decision impact (0-1) for the agent to request evidence
    # at all: low-value requests are suppressed so the agent only asks when the
    # answer could materially change the recommendation.
    min_evidence_info_value: float = 0.25
    # Hard bound on reassessment rounds per investigation (stopping criteria).
    max_investigation_rounds: int = 3


settings = Settings()

# Ensure directories exist at import time (non-destructive)
for _dir in (
    settings.data_dir,
    settings.prepared_db.parent,
    settings.app_db.parent,
    settings.cases_dir,
):
    _dir.mkdir(parents=True, exist_ok=True)
