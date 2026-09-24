"""
Hybrid investigation planner.

The agent does not run a fixed query script.  After each evidence round a
planner decides WHICH retrieval tools to run next, based on the current
evidence gaps.  Decision logic is deterministic (auditable, reproducible);
the LLM never selects tools — when an LLM is configured it only drafts a
natural-language rationale that is stored alongside the deterministic plan
(hence "hybrid").  Without an LLM the deterministic rationale stands alone.

Every planned step is recorded in case.plan_trace as:
  {
    "round": n,
    "tools": ["get_accounts_sharing_device", ...],
    "gap": "why these tools were chosen",
    "rationale_llm": "<optional LLM draft>" ,
    "skipped": [...tools intentionally not run and why...]
  }
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from backend.logging import get_logger
from backend.models import FraudPattern

log = get_logger(__name__)


@dataclass
class PlanStep:
    tool: str
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    purpose: str = ""
    gap: str = ""          # which evidence gap this closes
    priority: int = 0      # lower runs first


@dataclass
class InvestigationPlan:
    round_no: int
    gap: str
    steps: list[PlanStep] = field(default_factory=list)
    done: bool = False
    done_reason: str = ""
    rationale_llm: str = ""

    @property
    def tool_names(self) -> list[str]:
        return [s.tool for s in self.steps]


class ToolRegistry:
    """
    Named, schema-described graph tools the planner may invoke.
    Each entry: callable + a short description of when it is relevant.
    The orchestrator wires backend.graph functions into this registry, so the
    planner stays pure decision logic and is trivially testable.
    """

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}

    def register(self, name: str, fn: Callable, description: str) -> None:
        self._tools[name] = {"fn": fn, "description": description}

    def get(self, name: str) -> Callable:
        return self._tools[name]["fn"]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> dict[str, str]:
        return {k: v["description"] for k, v in self._tools.items()}


def plan_initial_round(ctx: dict[str, Any]) -> InvestigationPlan:
    """
    Round 0 plan: identify the subject and establish baselines.
    Always: flagged transaction, identity, card history, amount stats, window.
    Conditional: device neighbours (only when an identity/device exists),
    region window check only when a new region appears (needs txn first, so it
    belongs to round 1).
    """
    steps = [
        PlanStep("get_transaction", args=(ctx["flagged_txn_id"],),
                 purpose="Identify subject transaction", gap="subject", priority=0),
        PlanStep("get_transaction_identity", args=(ctx["flagged_txn_id"],),
                 purpose="Identity/device record for the flagged txn",
                 gap="identity", priority=1),
        PlanStep("get_card_transaction_history",
                 args=(ctx["card_id"],), kwargs={"limit": 50},
                 purpose="Spending baseline for the card", gap="baseline", priority=2),
        PlanStep("get_card_amount_stats", args=(ctx["card_id"],),
                 purpose="Amount statistics", gap="baseline", priority=3),
        PlanStep("get_card_window", args=(ctx["card_id"], ctx["flagged_ts"]),
                 kwargs={"hours": 48}, purpose="48h activity window",
                 gap="baseline", priority=4),
    ]
    return InvestigationPlan(round_no=0, gap="subject_and_baseline", steps=steps)


def plan_adaptive_round(ctx: dict[str, Any]) -> InvestigationPlan:
    """
    Round 1+ plan: chosen by the evidence gaps still open after the previous
    round.  This is where the agent becomes adaptive: different cases run
    different follow-up tools depending on what round 0 actually showed.
    """
    sig = ctx["signals"]
    steps: list[PlanStep] = []
    skipped: list[str] = []
    gaps: list[str] = []

    # Gap: is the flagged region genuinely new?  Only checked when a new region
    # appeared — otherwise the region-streak traversal is wasted work.
    if ctx.get("txn_region") and ctx.get("new_region"):
        steps.append(PlanStep(
            "get_cards_in_same_region_window",
            args=(ctx["txn_region"], ctx["flagged_ts"]),
            kwargs={"days": 4},
            purpose="Distinguish travel from cloning in the new region",
            gap="region_streak", priority=1))
    elif "region" in ctx.get("closed_gaps", []):
        skipped.append("get_cards_in_same_region_window: no new region on this card")

    # Gap: is the device shared / a fraud hub?  Only when a device exists.
    if ctx.get("device_label"):
        steps.append(PlanStep(
            "get_accounts_sharing_device", args=(ctx["device_label"],),
            kwargs={"limit": 20},
            purpose="Shared-infrastructure discovery", gap="device_sharing",
            priority=2))
        # Fraud-ring expansion only pays off when the device is actually shared.
        steps.append(PlanStep(
            "get_device_fraud_ring", args=(ctx["device_label"],),
            purpose="Connected fraud-ring analysis around the device",
            gap="fraud_ring", priority=3))
    else:
        skipped.append("get_accounts_sharing_device: no device profile on the flagged txn")
        skipped.append("get_device_fraud_ring: no device profile on the flagged txn")

    # Gap: velocity context — only when the window showed online activity.
    if ctx.get("online_window_count", 0) >= 1 or sig.card_testing_sequence:
        steps.append(PlanStep(
            "get_transaction_velocity", args=(ctx["card_id"], ctx["flagged_ts"]),
            kwargs={"hours": 24},
            purpose="Quantify transaction velocity", gap="velocity", priority=5))
    else:
        skipped.append("get_transaction_velocity: no online activity in window")

    # Gap: prior history on every connected entity (cheap, always informative).
    steps.append(PlanStep(
        "get_closed_cases_for_customer", args=(ctx["customer_id"],),
        purpose="Prior case memory on customer", gap="memory", priority=6))
    steps.append(PlanStep(
        "get_closed_cases_for_card", args=(ctx["card_id"],),
        purpose="Prior case memory on card", gap="memory", priority=6))
    if ctx.get("device_label"):
        steps.append(PlanStep(
            "get_closed_cases_by_device", args=(ctx["device_label"],),
            purpose="Prior fraud on the same device", gap="memory", priority=7))
    steps.append(PlanStep(
        "get_closed_cases_involving_txn", args=(ctx["flagged_txn_id"],),
        purpose="Prior cases naming this transaction", gap="memory", priority=7))

    # Gap: card-testing confirmation — tiny-sequence query only when the window
    # suggests it (>=1 tiny/online txn) or the trigger hints at it.
    if ctx.get("online_window_count", 0) >= 1 or ctx.get("trigger_risk_score", 0) or True:
        steps.append(PlanStep(
            "get_tiny_transaction_sequence",
            args=(ctx["card_id"], ctx["flagged_ts"]),
            purpose="Card-testing micro-authorizations", gap="card_testing",
            priority=4))

    gap_label = "+".join(gaps) if gaps else "adaptive_followups"
    return InvestigationPlan(round_no=ctx.get("round", 1), gap=gap_label, steps=steps)


def plan_retrieval_round(case: Any, ctx: dict[str, Any]) -> InvestigationPlan:
    """
    Post-assessment retrieval round (GraphRAG): similar prior cases by detected
    pattern + keyword search over analyst notes.  Runs only when a pattern was
    detected or the case is borderline — otherwise skipped entirely.
    """
    steps: list[PlanStep] = []
    pattern = ctx.get("pattern")
    if pattern and pattern != FraudPattern.none:
        steps.append(PlanStep(
            "get_closed_cases_by_pattern", args=(pattern.value,),
            kwargs={"limit": 15},
            purpose="Similar historical cases by pattern", gap="graphrag", priority=0))
    steps.append(PlanStep(
        "search_closed_cases_text", args=(ctx.get("retrieval_query", "")[:100],),
        kwargs={"limit": 5},
        purpose="Keyword retrieval over analyst notes", gap="graphrag", priority=1))
    return InvestigationPlan(round_no=ctx.get("round", 2),
                             gap="historical_similarity", steps=steps)


def should_stop_investigating(ctx: dict[str, Any]) -> tuple[bool, str]:
    """
    Explicit stopping criteria, evaluated between rounds.  Returns
    (should_stop, reason).  The agent stops when:
      - the verdict band is decisive (prob >= high or <= low) with sufficient
        independent evidence, or
      - the evidence plan is exhausted (no tool would add information), or
      - the investigation-round budget is spent.
    """
    prob = ctx.get("fraud_probability", 0.0)
    high = ctx.get("stop_high", 0.85)
    low = ctx.get("stop_low", 0.15)
    indep = ctx.get("independent_evidence_count", 0)
    min_ev = ctx.get("min_evidence_for_stop", 2)
    rounds_used = ctx.get("rounds_used", 0)
    max_rounds = ctx.get("max_rounds", 3)

    if prob >= high and indep >= min_ev:
        return True, f"decisive: fraud probability {prob:.2f} >= {high} with {indep} independent evidence sources"
    if prob <= low and indep >= min_ev:
        return True, f"decisive: fraud probability {prob:.2f} <= {low} with {indep} independent evidence sources"
    if rounds_used >= max_rounds:
        return True, f"investigation budget exhausted after {rounds_used} rounds"
    return False, ""
