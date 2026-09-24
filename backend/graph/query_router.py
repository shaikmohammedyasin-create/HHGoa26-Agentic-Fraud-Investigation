"""
Graph query router.

Routes calls to either the local SQLite store or TigerGraph depending on
GRAPH_BACKEND / availability.  Everything above this layer calls this module.
"""
from __future__ import annotations

from typing import Any
from datetime import datetime

from backend.config import settings
from backend.logging import get_logger
from backend.models import TransactionRecord, IdentityRecord, HistoricalCase

log = get_logger(__name__)

# Lazy import the right backend
_local = None
_tg = None


def _local_store():
    global _local
    if _local is None:
        from backend.graph import local_store
        _local = local_store
    return _local


def _tg_adapter():
    global _tg
    if _tg is None:
        try:
            from backend.graph import tg_adapter
            _tg = tg_adapter
        except ImportError:
            return None
    return _tg


def _use_tg() -> bool:
    return settings.graph_backend == "tigergraph" and _tg_adapter() is not None


def _route(local_fn: str, tg_fn: str, *args, **kwargs):
    """Call the appropriate backend function."""
    if _use_tg():
        try:
            fn = getattr(_tg_adapter(), tg_fn)
            return fn(*args, **kwargs)
        except Exception as exc:
            import os
            if settings.strict_graph_backend or os.environ.get("STRICT_GRAPH_BACKEND") in ("1", "true", "True"):
                log.error("tg.strict_mode_failed", error=str(exc), fn=tg_fn)
                raise RuntimeError(f"TigerGraph execution failed in strict mode for {tg_fn}: {exc}") from exc
            log.warning("tg.fallback_to_local", error=str(exc), fn=tg_fn)
    return getattr(_local_store(), local_fn)(*args, **kwargs)


# ─── Public API ───────────────────────────────────────────────────────────────

def get_transaction(txn_id: str) -> TransactionRecord | None:
    return _route("get_transaction", "get_transaction", txn_id)


def get_transaction_identity(txn_id: str) -> IdentityRecord | None:
    return _route("get_transaction_identity", "get_transaction_identity", txn_id)


def get_card_transaction_history(
    card_id: str, limit: int = 30, before: datetime | None = None
) -> list[TransactionRecord]:
    return _route("get_card_transaction_history", "get_card_transaction_history",
                  card_id, limit, before)


def get_customer_cards(customer_id: str) -> list[str]:
    return _route("get_customer_cards", "get_customer_cards", customer_id)


def get_card_window(card_id: str, center_ts: datetime, hours: int = 48) -> list[TransactionRecord]:
    return _route("get_card_window", "get_card_window", card_id, center_ts, hours)


def get_tiny_transaction_sequence(
    card_id: str, center_ts: datetime, window_hours: float = 2.0, amount_threshold: float = 10.0
) -> list[TransactionRecord]:
    return _route("get_tiny_transaction_sequence", "get_tiny_transaction_sequence",
                  card_id, center_ts, window_hours, amount_threshold)


def get_card_region_history(card_id: str, limit: int = 50) -> list[dict[str, Any]]:
    return _route("get_card_region_history", "get_card_region_history", card_id, limit)


def get_card_email_history(card_id: str) -> list[dict[str, Any]]:
    return _route("get_card_email_history", "get_card_email_history", card_id)


def get_card_product_history(card_id: str) -> list[dict[str, Any]]:
    return _route("get_card_product_history", "get_card_product_history", card_id)


def get_card_amount_stats(card_id: str) -> dict[str, float]:
    return _route("get_card_amount_stats", "get_card_amount_stats", card_id)


def get_device_profile_label(txn_id: str) -> str | None:
    return _route("get_device_profile_label", "get_device_profile_label", txn_id)


def get_accounts_sharing_device(device_label: str, limit: int = 20) -> list[dict[str, Any]]:
    return _route("get_accounts_sharing_device", "get_accounts_sharing_device", device_label, limit)


def get_card_device_history(card_id: str) -> list[dict[str, Any]]:
    return _route("get_card_device_history", "get_card_device_history", card_id)


def get_transaction_velocity(
    card_id: str, center_ts: datetime, hours: float = 24.0
) -> dict[str, Any]:
    return _route("get_transaction_velocity", "get_transaction_velocity", card_id, center_ts, hours)


def get_closed_cases_for_customer(customer_id: str) -> list[HistoricalCase]:
    return _route("get_closed_cases_for_customer", "get_closed_cases_for_customer", customer_id)


def get_closed_cases_for_card(card_id: str) -> list[HistoricalCase]:
    return _route("get_closed_cases_for_card", "get_closed_cases_for_card", card_id)


def get_closed_cases_involving_txn(txn_id: str) -> list[HistoricalCase]:
    return _route("get_closed_cases_involving_txn", "get_closed_cases_involving_txn", txn_id)


def get_closed_cases_by_device(device_label: str, limit: int = 10) -> list[HistoricalCase]:
    return _route("get_closed_cases_by_device", "get_closed_cases_by_device", device_label, limit)


def get_closed_cases_by_pattern(pattern: str, limit: int = 15) -> list[HistoricalCase]:
    return _route("get_closed_cases_by_pattern", "get_closed_cases_by_pattern", pattern, limit)


def search_closed_cases_text(query: str, limit: int = 5) -> list[HistoricalCase]:
    return _route("search_closed_cases_text", "search_closed_cases_text", query, limit)


def get_connected_card_cases(card_ids: list[str]) -> list[HistoricalCase]:
    return _route("get_connected_card_cases", "get_connected_card_cases", card_ids)


def get_cards_in_same_region_window(
    region: str, center_ts: datetime, days: float = 3.0, limit: int = 30
) -> list[dict[str, Any]]:
    return _route("get_cards_in_same_region_window", "get_cards_in_same_region_window",
                  region, center_ts, days, limit)


def get_cards_in_same_email_domain(domain: str) -> list[dict[str, Any]]:
    return _route("get_cards_in_same_email_domain", "get_cards_in_same_email_domain", domain)


def get_device_fraud_ring(device_label: str, max_cards: int = 25) -> dict[str, Any]:
    """Fraud-ring analysis around a device profile (connected component + fraud membership)."""
    return _route("get_device_fraud_ring", "get_device_fraud_ring", device_label, max_cards)


# ─── Case memory (investigation cases written by this agent) ──────────────────

def write_investigation_case(payload: dict[str, Any]) -> str:
    """
    Persist a completed investigation case into the graph backend.

    Case-memory writes follow fail-closed semantics: when the configured backend
    is TigerGraph and the write fails, the error propagates to the caller (the
    orchestrator records `written_to_graph=False` + an audit event) instead of
    silently writing to local storage while the UI claims TigerGraph persistence.
    Local storage is only used when the local backend is selected.
    """
    if _use_tg():
        return _tg_adapter().write_investigation_case(payload)
    return _local_store().write_investigation_case(payload)


def get_investigation_cases_for_customer(customer_id: str, limit: int = 10) -> list[dict[str, Any]]:
    return _route("get_investigation_cases_for_customer",
                  "get_investigation_cases_for_customer", customer_id, limit)


def get_investigation_cases_by_device(device_label: str, limit: int = 10) -> list[dict[str, Any]]:
    return _route("get_investigation_cases_by_device",
                  "get_investigation_cases_by_device", device_label, limit)


def get_investigation_cases_involving_txn(txn_id: str, limit: int = 10) -> list[dict[str, Any]]:
    return _route("get_investigation_cases_involving_txn",
                  "get_investigation_cases_involving_txn", txn_id, limit)


def mcp_status() -> dict[str, str]:
    """Health of the TigerGraph MCP tool surface, when configured."""
    if not settings.mcp_url:
        return {"status": "not_configured"}
    try:
        from backend.mcp import client as mcp
        return mcp.get_mcp().health()
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


def get_all_case_triggers() -> list[dict[str, Any]]:
    return _local_store().get_all_case_triggers()


def get_case_trigger(case_id: str) -> dict[str, Any] | None:
    return _local_store().get_case_trigger(case_id)


def health_check() -> dict[str, str]:
    local_health = _local_store().health_check()
    if _use_tg():
        try:
            tg_health = _tg_adapter().health_check()
        except Exception as exc:
            tg_health = {"status": "unavailable", "error": str(exc)}
        return {"local": local_health.get("status", "?"), "tigergraph": tg_health.get("status", "?")}
    return local_health
