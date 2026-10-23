"""
Nemotron smoke test - makes ONE REAL Token Factory call per role.

Requires NEBIUS_API_KEY in .env / environment. NOT part of CI: judge runs
and the pytest suite never execute this file.

Usage:  python scripts/smoke_nemotron.py
Output: per-role latency_ms and token counts, or the failure reason.
Exit:   0 when every available role call succeeded (or key is absent),
        1 when key present but a role call failed.
"""
from __future__ import annotations

import os
import sys

# Make `backend` importable when run from any cwd.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import settings                      # noqa: E402
from backend.llm import nebius_client, roles             # noqa: E402
from backend.models import FraudPattern                  # noqa: E402

PATTERN_ENUM = [p.value for p in FraudPattern]

CARDS = [
    {"evidence_id": "EV-01",
     "claim": "6 online attempts in 4 minutes on one card; average check size stable.",
     "source": "graph", "ref": "query:card_transaction_history"},
    {"evidence_id": "EV-02",
     "claim": "Device profile shared with 3 other cards opened last week.",
     "source": "graph", "ref": "query:accounts_sharing_device"},
]


def _fmt_usage(usage: dict) -> str:
    return (f"latency/token check (in={usage.get('prompt_tokens')} "
            f"out={usage.get('completion_tokens')})")


def main() -> int:
    print("Nebius Token Factory smoke")
    print("base_url:", settings.nebius_base_url)
    print("models  :", nebius_client.model_nano(), "|",
          nebius_client.model_super(), "|", nebius_client.model_ultra())

    failures: list[str] = []

    # Role 1: pattern classifier (Nano)
    proposal = roles.classify_pattern(CARDS)
    if proposal:
        assert proposal["pattern"] in PATTERN_ENUM
        print("role 1 pattern_classifier   OK", proposal["pattern"],
              round(proposal["confidence"], 2), _fmt_usage(proposal["usage"]))
    else:
        failures.append("role 1 pattern_classifier FAILED (None - check key/limits)")

    # Role 2: verification draft (Nano)
    draft = roles.draft_verification(
        "risk alert on transaction", "4012147", "211.25 USD",
        "confirm you placed this purchase")
    if draft:
        print("role 2 verification_draft   OK", _len(draft), "chars;",
              draft[:80].replace("\n", " "), "...")
    else:
        failures.append("role 2 verification_draft FAILED (None)")

    # Role 3: narrative + SAR draft (Ultra)
    out = roles.narrative_and_sar(
        {"case_id": "SMOKE", "verdict": "fraud", "pattern": "card_testing",
         "exposure_usd": 211.25}, CARDS)
    if out:
        print("role 3 narrative_and_sar    OK", _len(out["summary"]), "+",
              _len(out["sar_narrative"]), "chars")
    else:
        failures.append("role 3 narrative_and_sar FAILED (None)")

    # Role 4: analyst Q&A (Ultra)
    answer = roles.analyst_qa({"case_id": "SMOKE"}, CARDS,
                              "How many attempts were made?")
    if answer:
        print("role 4 analyst_qa           OK", _len(answer), "chars;",
              answer[:80].replace("\n", " "), "...")
    else:
        failures.append("role 4 analyst_qa FAILED (None)")

    if failures:
        print()
        for f in failures:
            print("-", f)
        return 1
    print("\nAll four roles OK.")
    return 0


def _len(text: str) -> int:
    return len(text or "")


if __name__ == "__main__":
    if not nebius_client.available():
        print("NEBIUS_API_KEY not set - skipping live calls (smoke test needs the key).")
        sys.exit(0)
    sys.exit(main())
