# Engineering Decisions

## D1. Modular monolith, not microservices

The challenge is one investigation pipeline. Queues, Kubernetes, and extra databases add failure modes without helping accuracy or next-best-action scoring.

## D2. Custom state machine, not LangGraph

One orchestrator with explicit persisted states (TRIGGERED … COMPLETED / FAILED / ESCALATED). LangGraph would duplicate the policy-gated control plane we must own anyway.

## D3. Query port over TigerGraph and a local graph store

TigerGraph is the intended investigation engine (GSQL, algorithms, MCP, case vertices). Credentials and a live workspace are not in this repository. A local SQLite store implements the **same query interface** so:

- unit/e2e tests and the 20-case benchmark can run against real CSVs
- switching `GRAPH_BACKEND=tigergraph` does not change agent or policy code

This is not a fake graph. It is the same entities, relationships, and investigation questions.

## D4. Slim investigation columns only

`transactions.csv` is ~708 MB and 393+ Vesta columns. Investigation questions in the README need identity, amounts, time, channel, card, region, email, a few C/D/M signals, and risk_score. V1–V339 are unnamed model features; we do not load them into the graph. If used later they are cited as unnamed signals.

## D5. Card ID derivation

`transactions.csv` has `customer_id` and `card1`–`card6`, not `C01234-K1`. Case pack and closed cases use `C01234-K1` / `K2`.

Mapping:

1. Fingerprint = `(card1, card2, card3, card4, card5, card6)` per customer.
2. Bind fingerprints to known `card_id` values via `case_pack.flagged_txn_id` and `closed_cases.txn_ids`.
3. Remaining fingerprints on that customer get the smallest unused `K{n}` in first-seen order.

Assumption is documented in DATASET_ANALYSIS.md. Flagged-transaction lookup does not depend on K-number assignment.

## D6. No second vector database

Closed-case notes + policy + pattern text are retrieved with BM25/token overlap. If TigerGraph vector search is configured, GraphRAG prefers it. Adding FAISS/Chroma would split retrieval away from the graph without a dataset requirement to do so.

## D7. Deterministic risk and policy; optional LLM text

`fraud_probability` is a documented heuristic over evidence, not an LLM sample. Actions, routes, and SAR-filing decisions come from the Fraud Policy (R1–R10). The LLM may write `summary`, `sar.narrative`, and `what_changed`. Invalid or missing LLM output falls back to templates. That keeps calibration and policy scoring honest.

## D8. Simulated additional evidence is explicit

The README states customer/analyst replies are not provided and must be simulated, with the assumption recorded in `evidence_requests`. Simulation is deterministic from graph evidence (recurring charge, travel-like region streak, testing sequence, shared-device fraud history). Assumptions are never presented as graph facts (`source: customer`).

## D9. SQLite for application state

Investigations must survive process restart (pending evidence, pending approvals, audit). SQLite is local, transactional enough for this monolith, and does not duplicate the transaction graph.

## D10. MCP is real when configured, never faked

`backend/mcp` talks to the official [tigergraph-mcp](https://github.com/tigergraph/tigergraph-mcp) tool surface. If MCP is down, tools return a structured error (`mcp_unavailable`). The orchestrator records that as missing capability, not as empty evidence.

## D11. Answer files are the evaluation contract

`cases/<case_id>.json` matches the README Answer Format exactly. Internal models are richer (timeline, tool provenance, before/after snapshots) and map into that schema at export time.
