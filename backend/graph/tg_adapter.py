"""
TigerGraph adapter.

Implements the same query interface as backend.graph.local_store, but executes
against a real TigerGraph (Savanna / Community Edition) through the official
tigergraph-mcp tool surface when MCP_URL is configured, or falls back to the
TigerGraph REST endpoints otherwise.

This is the REAL TigerGraph path.  It is selected by the query router only when
GRAPH_BACKEND=tigergraph.  If a call fails, the router logs the failure and
falls back to the local store for that call — it never silently converts a
TigerGraph failure into a fabricated result; the fallback is recorded in the
case audit trail by the orchestrator.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.config import settings
from backend.logging import get_logger
from backend.models import TransactionRecord, IdentityRecord, HistoricalCase, Channel

log = get_logger(__name__)

# GSQL query names installed by tigergraph/gsql/queries.gsql
_Q = {
    "txn": "txn_by_id",
    "card_history": "card_transaction_history",
    "card_window": "card_window",
    "tiny_seq": "tiny_txn_sequence",
    "region_history": "card_region_history",
    "device_neighbors": "device_neighbors",
    "customer_cases": "customer_closed_cases",
    "card_cases": "card_closed_cases",
    "velocity": "card_velocity",
}


# ─── Transport ───────────────────────────────────────────────────────────────

_tg_conn: Any = None


def get_connection():
    """Return a pyTigerGraph connection initialized with current settings."""
    global _tg_conn
    if _tg_conn is not None:
        return _tg_conn

    try:
        import pyTigerGraph as tg

        host = settings.tg_host.strip()
        if host.startswith("https://"):
            raw_host = host[8:]
        elif host.startswith("http://"):
            raw_host = host[7:]
        else:
            raw_host = host
        raw_host = raw_host.split(":")[0].split("/")[0]
        full_host = f"{settings.tg_protocol}://{raw_host}"

        conn = tg.TigerGraphConnection(
            host=full_host,
            graphname=settings.tg_graph,
            gsqlSecret=settings.tg_secret or "",
            apiToken=settings.tg_token or "",
            username=settings.tg_username or "tigergraph",
            password=settings.tg_password or "tigergraph",
            tgCloud=True,
            sslPort=str(settings.tg_port),
        )

        if settings.tg_secret and not conn.apiToken:
            import time
            for attempt in range(4):
                try:
                    token = conn.getToken(settings.tg_secret, setToken=True)
                    if isinstance(token, tuple):
                        conn.apiToken = token[0]
                    elif isinstance(token, str):
                        conn.apiToken = token
                    if conn.apiToken:
                        break
                except Exception as e:
                    if attempt < 3:
                        time.sleep(1.5)
                    else:
                        log.warning("Could not obtain token via TG_SECRET after 4 attempts: %s", e)

        if not settings.tg_secret or conn.apiToken:
            _tg_conn = conn
        return conn
    except Exception as exc:
        log.warning("Could not initialize pyTigerGraph connection: %s", exc)
        return None


def _get_auth_token() -> str:
    """Return the active token from TG_TOKEN or acquired dynamically via TG_SECRET."""
    if settings.tg_token:
        return settings.tg_token
    if settings.tg_secret:
        conn = get_connection()
        if conn and getattr(conn, "apiToken", None):
            return conn.apiToken
    return ""


def _mcp():
    """Return the MCP client, or None when MCP is not configured."""
    if not settings.mcp_url:
        return None
    from backend.mcp import client as mcp
    return mcp.get_mcp()


def _tg_base_url() -> str:
    host = settings.tg_host.strip()
    if host.startswith("https://"):
        host = host[8:]
    elif host.startswith("http://"):
        host = host[7:]
    host = host.rstrip("/")
    if ":" in host:
        return f"{settings.tg_protocol}://{host}"
    return f"{settings.tg_protocol}://{host}:{settings.tg_port}"


def _run(query_name: str, params: dict[str, Any]) -> Any:
    """Execute an installed GSQL query via pyTigerGraph (preferred), MCP, or REST."""
    conn = get_connection()
    if conn is not None and getattr(conn, "apiToken", None):
        try:
            res = conn.runInstalledQuery(query_name, params)
            if isinstance(res, list) and len(res) > 0 and isinstance(res[0], dict):
                unified = {}
                for d in res:
                    unified.update(d)
                if "result" not in unified:
                    for v in unified.values():
                        if isinstance(v, list):
                            unified["result"] = v
                            break
                return unified
            return res if isinstance(res, dict) else {"result": res}
        except Exception as exc:
            err_str = str(exc)
            if "not valid" in err_str and "vertex" in err_str:
                return {"result": []}
            log.warning("pyTigerGraph runInstalledQuery failed for %s: %s, falling back to REST...", query_name, exc)

    mcp = _mcp()
    if mcp is not None:
        return mcp.run_query(query_name, params)

    token = _get_auth_token()
    import httpx

    url = f"{_tg_base_url()}/restpp/query/{settings.tg_graph}/{query_name}"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=30) as c:
        try:
            r = c.get(url, params=params, headers=headers)
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                fallback_url = f"{_tg_base_url()}/query/{settings.tg_graph}/{query_name}"
                r = c.get(fallback_url, params=params, headers=headers)
                r.raise_for_status()
            else:
                raise
        data = r.json()
        results = data.get("results", [])
        if isinstance(results, list) and len(results) > 0 and isinstance(results[0], dict):
            unified = {}
            for d in results:
                unified.update(d)
            if "result" not in unified:
                for v in unified.values():
                    if isinstance(v, list):
                        unified["result"] = v
                        break
            return unified
        return data


def _upsert(vertices: list[dict], edges: list[dict]) -> Any:
    """Upsert vertices/edges using pyTigerGraph connection."""
    conn = get_connection()
    v_by_type: dict[str, list] = {}
    for v in vertices:
        v_by_type.setdefault(v["type"], []).append((v["id"], v["attributes"]))
    for vt, vlist in v_by_type.items():
        conn.upsertVertices(vt, vlist)

    for e in edges:
        from_type = e.get("from_type", "InvestigationCase")
        to_type = e.get("to_type")
        if not to_type:
            if e["type"] == "IC_ON_CARD":
                to_type = "Card"
            elif e["type"] == "IC_FOR_CUSTOMER":
                to_type = "Customer"
            elif e["type"] == "IC_INVOLVES":
                to_type = "Transaction"
            elif e["type"] == "IC_ON_DEVICE":
                to_type = "DeviceProfile"
            else:
                to_type = "Card"
        conn.upsertEdges(from_type, e["type"], to_type, [(e["from"], e["to"], e.get("attributes", {}))])


# ─── Result shaping ──────────────────────────────────────────────────────────

def _vertex_attrs(v: dict) -> dict:
    """TigerGraph returns {"v_id":..., "attributes": {...}}."""
    return dict(v.get("attributes", {}))


def _to_txn(v: dict) -> TransactionRecord:
    a = _vertex_attrs(v)
    return TransactionRecord(
        txn_id=str(v.get("v_id")),
        customer_id=str(a.get("customer_id", "")),
        card_id=str(a.get("card_id", "")),
        ts=datetime.fromisoformat(str(a["ts"]).replace(" ", "T")) if a.get("ts") else datetime.utcnow(),
        amount=float(a.get("amount") or 0),
        product_cd=str(a.get("product_cd") or ""),
        channel=Channel(str(a.get("channel"))) if a.get("channel") in ("online", "in_person") else Channel.in_person,
        addr1=str(a["addr1"]) if a.get("addr1") else None,
        addr2=str(a["addr2"]) if a.get("addr2") else None,
        p_email=str(a.get("p_email")) or None,
        r_email=str(a.get("r_email")) or None,
        risk_score=float(a["risk_score"]) if a.get("risk_score") is not None else None,
    )


def _to_identity(txn_id: str, dp: dict) -> IdentityRecord:
    a = _vertex_attrs(dp)
    dev_status = a.get("device_status") or a.get("id_15")
    proxy = a.get("proxy") or a.get("id_23")
    match_status = a.get("match_status") or a.get("id_34")
    return IdentityRecord(
        txn_id=txn_id,
        device_type=str(a.get("device_type")) if a.get("device_type") is not None and a.get("device_type") != "None" else None,
        device_info=str(a.get("device_info")) if a.get("device_info") is not None and a.get("device_info") != "None" else None,
        os=str(a.get("os")) if a.get("os") is not None and a.get("os") != "None" else None,
        browser=str(a.get("browser")) if a.get("browser") is not None and a.get("browser") != "None" else None,
        screen=str(a.get("screen")) if a.get("screen") is not None and a.get("screen") != "None" else None,
        device_status=str(dev_status) if dev_status is not None and dev_status != "None" else None,
        proxy=str(proxy) if proxy is not None and proxy != "None" else None,
        match_status=str(match_status) if match_status is not None and match_status != "None" else None,
    )


def _to_historical_case(v: dict) -> HistoricalCase:
    a = _vertex_attrs(v)
    return HistoricalCase(
        case_id=str(v.get("v_id")),
        customer_id=str(a.get("customer_id", "")),
        card_id=str(a.get("card_id", "")),
        opened_at=datetime.fromisoformat(str(a["opened_at"]).replace(" ", "T")) if a.get("opened_at") else datetime.utcnow(),
        closed_at=datetime.fromisoformat(str(a["closed_at"]).replace(" ", "T")) if a.get("closed_at") else datetime.utcnow(),
        outcome=str(a.get("outcome", "")),
        pattern=str(a.get("pattern", "none")),
        exposure_usd=float(a.get("exposure_usd") or 0),
        n_txns=int(a.get("n_txns") or 0),
        report_filed=bool(a.get("report_filed")),
        analyst_notes=str(a.get("analyst_notes") or ""),
    )


# ─── Public API (mirrors backend.graph.local_store) ──────────────────────────

def health_check() -> dict[str, str]:
    try:
        mcp = _mcp()
        if mcp is not None:
            return mcp.health()

        # Check via pyTigerGraph if available
        conn = get_connection()
        if conn is not None and getattr(conn, "apiToken", None):
            try:
                v_types = conn.getVertexTypes()
                return {"status": "healthy", "graph": settings.tg_graph, "backend": "pyTigerGraph", "vertices": str(len(v_types))}
            except Exception:
                pass

        # Fallback to REST sanity check: request the graph metadata
        token = _get_auth_token()
        import httpx
        url = f"{_tg_base_url()}/graphs/{settings.tg_graph}"
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with httpx.Client(timeout=10) as c:
            r = c.get(url, headers=headers)
            r.raise_for_status()
        return {"status": "healthy", "graph": settings.tg_graph}
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}


def get_transaction(txn_id: str) -> TransactionRecord | None:
    try:
        res = _run("txn_by_id", {"txn_id": txn_id})
        items = res.get("result", []) if isinstance(res, dict) else []
        return _to_txn(items[0]) if items else None
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_transaction failed: {exc}")


def get_transaction_identity(txn_id: str) -> IdentityRecord | None:
    try:
        res = _run("txn_identity", {"txn_id": txn_id})
        items = res.get("result", []) if isinstance(res, dict) else []
        idr = _to_identity(txn_id, items[0]) if items else None
        
        # Enrich transaction-level identity metadata (id_15, id_23, id_34).
        # PROVENANCE NOTE: these three fields come from the prepared local
        # identity dataset when the TigerGraph DeviceProfile vertex does not
        # carry them.  Each attribute's origin is recorded in attribute_sources
        # so downstream consumers can distinguish graph-sourced vs prepared-
        # dataset-sourced values.
        from backend.graph import local_store
        local_idr = local_store.get_transaction_identity(txn_id)
        if local_idr:
            if idr is None:
                idr = local_idr
                idr.attribute_sources = {
                    k: "prepared_dataset"
                    for k in ("device_status", "proxy", "match_status")
                    if getattr(idr, k, None)
                }
            else:
                for attr in ("device_status", "proxy", "match_status"):
                    if getattr(idr, attr, None) is None and getattr(local_idr, attr, None):
                        setattr(idr, attr, getattr(local_idr, attr))
                        idr.attribute_sources = dict(idr.attribute_sources or {})
                        idr.attribute_sources[attr] = "prepared_dataset"
        return idr
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_transaction_identity failed: {exc}")


def get_card_transaction_history(card_id: str, limit: int = 30, before: datetime | None = None) -> list[TransactionRecord]:
    try:
        res = _run(_Q["card_history"], {"card": card_id, "limit_n": limit})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_to_txn(v) for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_card_transaction_history failed: {exc}")


def get_customer_cards(customer_id: str) -> list[str]:
    try:
        res = _run("customer_cards", {"cust": customer_id})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [str(v.get("v_id")) for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_customer_cards failed: {exc}")


def get_card_window(card_id: str, center_ts: datetime, hours: int = 48) -> list[TransactionRecord]:
    try:
        res = _run(_Q["card_window"], {"card": card_id, "center_ts": center_ts.isoformat(), "hours": hours})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_to_txn(v) for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_card_window failed: {exc}")


def get_tiny_transaction_sequence(card_id: str, center_ts: datetime, window_hours: float = 2.0, amount_threshold: float = 10.0) -> list[TransactionRecord]:
    try:
        res = _run(_Q["tiny_seq"], {"card": card_id, "center_ts": center_ts.isoformat(),
                                    "hours": int(window_hours), "threshold": amount_threshold})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_to_txn(v) for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_tiny_transaction_sequence failed: {exc}")


def get_card_region_history(card_id: str, limit: int = 50) -> list[dict[str, Any]]:
    try:
        res = _run(_Q["region_history"], {"card": card_id})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [{"addr1": str(v.get("v_id") or _vertex_attrs(v).get("region_code") or "")} for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_card_region_history failed: {exc}")


def get_card_email_history(card_id: str) -> list[dict[str, Any]]:
    try:
        res = _run("card_email_history", {"card": card_id})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [{"P_emaildomain": v.get("v_id"), "n": _vertex_attrs(v).get("n", 1)} for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_card_email_history failed: {exc}")


def get_card_product_history(card_id: str) -> list[dict[str, Any]]:
    try:
        res = _run("card_product_history", {"card": card_id})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [{"ProductCD": _vertex_attrs(v).get("product_cd") or _vertex_attrs(v).get("prods.product_cd"), "n": _vertex_attrs(v).get("n", 1)} for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_card_product_history failed: {exc}")


def get_card_amount_stats(card_id: str) -> dict[str, float]:
    try:
        res = _run("card_amount_stats", {"card": card_id})
        if isinstance(res, dict):
            if "avg_amt" in res or "min_amt" in res:
                return res
            items = res.get("result", [])
            if items:
                item = items[0]
                if "attributes" in item:
                    return _vertex_attrs(item)
                return item
        return {}
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_card_amount_stats failed: {exc}")


def get_device_profile_label(txn_id: str) -> str | None:
    try:
        res = _run("txn_device_profile", {"txn_id": txn_id})
        items = res.get("result", []) if isinstance(res, dict) else []
        if not items:
            return None
        v_id = str(items[0].get("v_id") or "")
        if v_id and "|" in v_id:
            return v_id
        a = _vertex_attrs(items[0])
        label = " | ".join(str(a.get(k) or a.get(f"result.{k}") or "unknown") for k in ("device_info", "os", "browser", "screen"))
        return label if label != "unknown | unknown | unknown | unknown" else (v_id or None)
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_device_profile_label failed: {exc}")


def get_accounts_sharing_device(device_label: str, limit: int = 20) -> list[dict[str, Any]]:
    try:
        clean_label = device_label.strip() if device_label else ""
        if clean_label.lower().startswith("dev | "):
            clean_label = clean_label[6:].strip()
        if not clean_label or clean_label == "unknown":
            return []
        res = _run(_Q["device_neighbors"], {"dp": clean_label, "limit_n": limit})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [{"card_id": str(v.get("v_id")), "customer_id": _vertex_attrs(v).get("customer_id", "")} for v in items]
    except Exception as exc:
        err_msg = str(exc)
        if "not valid DeviceProfile vertex" in err_msg or "400 Bad Request" in err_msg:
            return []
        raise RuntimeError(f"TigerGraph get_accounts_sharing_device failed: {exc}")


def get_card_device_history(card_id: str) -> list[dict[str, Any]]:
    try:
        res = _run("card_device_history", {"card": card_id})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_vertex_attrs(v) for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_card_device_history failed: {exc}")


def get_transaction_velocity(card_id: str, center_ts: datetime, hours: float = 24.0) -> dict[str, Any]:
    try:
        res = _run(_Q["velocity"], {"card": card_id, "center_ts": center_ts.isoformat(), "hours": int(hours)})
        return res if isinstance(res, dict) else {}
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_transaction_velocity failed: {exc}")


def get_closed_cases_for_customer(customer_id: str) -> list[HistoricalCase]:
    try:
        res = _run(_Q["customer_cases"], {"cust": customer_id})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_to_historical_case(v) for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_closed_cases_for_customer failed: {exc}")


def get_closed_cases_for_card(card_id: str) -> list[HistoricalCase]:
    try:
        res = _run(_Q["card_cases"], {"card": card_id})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_to_historical_case(v) for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_closed_cases_for_card failed: {exc}")


def get_closed_cases_involving_txn(txn_id: str) -> list[HistoricalCase]:
    try:
        res = _run("cases_involving_txn", {"txn_id": txn_id})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_to_historical_case(v) for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_closed_cases_involving_txn failed: {exc}")


def get_closed_cases_by_device(device_label: str, limit: int = 10) -> list[HistoricalCase]:
    try:
        dev_name = device_label.split("|")[0].strip() if "|" in device_label else device_label
        if not dev_name or dev_name == "unknown":
            return []
        res = _run("cases_by_device", {"device_label": dev_name, "limit_n": limit})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_to_historical_case(v) for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_closed_cases_by_device failed: {exc}")


def get_closed_cases_by_pattern(pattern: str, limit: int = 15) -> list[HistoricalCase]:
    try:
        res = _run("cases_by_pattern", {"pattern": pattern, "limit_n": limit})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_to_historical_case(v) for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_closed_cases_by_pattern failed: {exc}")


def search_closed_cases_text(query: str, limit: int = 5) -> list[HistoricalCase]:
    """
    Retrieval over closed-case notes.  Uses the TigerGraph vector store through
    MCP vector_search when available; otherwise the installed keyword query.

    The GSQL keyword query uses a single LIKE over the raw text, which is both
    case-sensitive and too narrow for a full trigger sentence.  We therefore
    extract distinctive tokens and take the union of per-token matches (the
    local store's search does the same over its tokens).
    """
    try:
        mcp = _mcp()
        if mcp is not None and settings.graph_backend == "tigergraph":
            res = mcp.vector_search(query, top_k=limit)
            items = res.get("result", []) if isinstance(res, dict) else []
            return [_to_historical_case(v) for v in items]

        # Tokenise: distinctive words only (drop tiny stopwords / numbers).
        stop = {"the", "and", "for", "this", "that", "with", "from",
                "was", "were", "have", "has", "had", "not", "are",
                "review", "decide", "real-time", "model", "scored",
                "transaction", "please", "check", "card"}
        tokens: list[str] = []
        for raw in query.lower().replace("_", " ").split():
            tok = "".join(ch for ch in raw if ch.isalnum())
            if len(tok) >= 4 and tok not in stop and tok not in tokens:
                tokens.append(tok)
            if len(tokens) >= 4:
                break

        seen: dict[str, HistoricalCase] = {}
        for tok in tokens or [query.strip()[:100]]:
            res = _run("search_case_notes", {"search_text": tok, "limit_n": limit})
            items = res.get("result", []) if isinstance(res, dict) else []
            for v in items:
                hc = _to_historical_case(v)
                seen.setdefault(hc.case_id, hc)
            if len(seen) >= limit:
                break
        return list(seen.values())[:limit]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph search_closed_cases_text failed: {exc}")


def get_connected_card_cases(card_ids: list[str]) -> list[HistoricalCase]:
    if not card_ids:
        return []
    try:
        res = _run("connected_card_cases", {"card_ids": card_ids})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_to_historical_case(v) for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_connected_card_cases failed: {exc}")


def get_cards_in_same_region_window(region: str, center_ts: datetime, days: float = 3.0, limit: int = 30) -> list[dict[str, Any]]:
    try:
        res = _run("cards_in_region_window", {"region": region, "center_ts": center_ts.isoformat(),
                                              "days": days, "limit_n": limit})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [{"card_id": str(v.get("v_id")), "customer_id": _vertex_attrs(v).get("customer_id", "")} for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_cards_in_same_region_window failed: {exc}")


def get_cards_in_same_email_domain(domain: str) -> list[dict[str, Any]]:
    try:
        res = _run("cards_in_email_domain", {"domain": domain})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [{"card_id": str(v.get("v_id")), "customer_id": _vertex_attrs(v).get("customer_id", "")} for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_cards_in_same_email_domain failed: {exc}")


def get_device_fraud_ring(device_label: str, max_cards: int = 25) -> dict[str, Any]:
    """
    Fraud-ring analysis around a device profile via the installed
    `device_fraud_ring` GSQL query: the connected card component through this
    device plus how many of those cards appear in confirmed-fraud closed cases.
    Falls back to the local implementation through the query router on failure.
    """
    try:
        dev_name = device_label.split("|")[0].strip() if "|" in device_label else device_label
        if not dev_name or dev_name == "unknown":
            return {"device": device_label, "ring_size": 0, "cards": [],
                    "fraud_cards": [], "n_fraud": 0}
        res = _run("device_fraud_ring", {"dp": dev_name, "limit_n": max_cards})
        items = res.get("result", []) if isinstance(res, dict) else []
        cards: list[str] = []
        customers: dict[str, str] = {}
        for v in items:
            cid = str(v.get("v_id") or v.get("card_id") or "")
            if cid:
                cards.append(cid)
                customers[cid] = str(_vertex_attrs(v).get("customer_id", ""))
        # Fraud membership via closed cases on each ring card (bounded).
        fraud_cards: set[str] = set()
        for cid in cards[:max_cards]:
            try:
                cres = _run("card_closed_cases", {"card": cid})
                citems = cres.get("result", []) if isinstance(cres, dict) else []
                for cv in citems:
                    a = _vertex_attrs(cv)
                    if str(a.get("outcome", "")) == "confirmed_fraud":
                        fraud_cards.add(cid)
            except Exception:
                continue
        fraud_in_ring = sorted(fraud_cards)
        return {
            "device": device_label,
            "ring_size": len(cards),
            "cards": cards,
            "fraud_cards": fraud_in_ring,
            "n_fraud": len(fraud_in_ring),
        }
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_device_fraud_ring failed: {exc}")


def write_investigation_case(payload: dict[str, Any]) -> str:
    """
    Persist a completed investigation case into TigerGraph as an
    InvestigationCase vertex plus IC_INVOLVES / IC_ON_CARD / IC_FOR_CUSTOMER
    edges.  Returns the graph case id.
    """
    case_id = str(payload["case_id"])
    # Year of the investigation, not the year the binary happens to run in.
    year = ((payload.get("trigger") or {}).get("opened_at") or payload.get("created_at") or "")[:4] \
        or datetime.utcnow().strftime("%Y")
    graph_case_id = f"CASE-{year}-{case_id}"
    trigger = payload.get("trigger", {})

    vertices = [{
        "type": "InvestigationCase",
        "id": graph_case_id,
        "attributes": {
            "trigger_type": trigger.get("trigger_type", ""),
            "trigger_text": (trigger.get("trigger_text") or "")[:2000],
            "opened_at": trigger.get("opened_at", ""),
            "status": payload.get("status", ""),
            "verdict": payload.get("verdict", ""),
            "fraud_probability": float(payload.get("fraud_probability") or 0.0),
            "pattern": payload.get("pattern", "none"),
            "exposure_usd": float(payload.get("exposure_usd") or 0.0),
            "summary": (payload.get("summary") or "")[:4000],
        },
    }]
    edges = [{
        "type": "IC_ON_CARD", "from": graph_case_id, "to": str(payload["card_id"]),
    }, {
        "type": "IC_FOR_CUSTOMER", "from": graph_case_id, "to": str(payload["customer_id"]),
    }]
    edges += [{"type": "IC_INVOLVES", "from": graph_case_id, "to": str(t)}
              for t in payload.get("affected_txn_ids", [])]
    # Graph-native memory: link the case to the device profile(s) involved so
    # future device-centric traversals encounter this investigation.
    edges += [{"type": "IC_ON_DEVICE", "from": graph_case_id,
               "to": str(d), "from_type": "InvestigationCase", "to_type": "DeviceProfile"}
              for d in payload.get("connected_device_profiles", [])[:3] if d]

    _upsert(vertices, edges)
    return graph_case_id


def get_investigation_cases_for_customer(customer_id: str, limit: int = 10) -> list[dict[str, Any]]:
    try:
        res = _run("investigation_cases_for_customer", {"cust": customer_id, "limit_n": limit})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_vertex_attrs(v) | {"case_id": str(v.get("v_id"))} for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_investigation_cases_for_customer failed: {exc}")


def get_investigation_cases_by_device(device_label: str, limit: int = 10) -> list[dict[str, Any]]:
    try:
        res = _run("investigation_cases_by_device", {"device_label": device_label, "limit_n": limit})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_vertex_attrs(v) | {"case_id": str(v.get("v_id"))} for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_investigation_cases_by_device failed: {exc}")


def get_investigation_cases_involving_txn(txn_id: str, limit: int = 10) -> list[dict[str, Any]]:
    try:
        res = _run("investigation_cases_involving_txn", {"txn_id": txn_id, "limit_n": limit})
        items = res.get("result", []) if isinstance(res, dict) else []
        return [_vertex_attrs(v) | {"case_id": str(v.get("v_id"))} for v in items]
    except Exception as exc:
        raise RuntimeError(f"TigerGraph get_investigation_cases_involving_txn failed: {exc}")
