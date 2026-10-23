"""
make_synthetic_data.py

Generates a small, fixed-seed SYNTHETIC dataset that is safe to publish:

    data/synthetic/transactions.csv          ~9k rows, IEEE-CIS-compatible columns
    data/synthetic/identity.csv              device / identity rows for a subset of txns
    data/synthetic/closed_cases_history.csv  historical closed-case memory the agent uses
    data/synthetic/case_pack.csv             the 20 investigation triggers

Nothing here is derived from the round-provided dataset: every id, amount,
timestamp, device string and note is produced by this script with a fixed
RNG seed, so two runs always yield the identical hermetic dataset.

The generator plants 20 investigation scenarios whose labels match
cases/ground_truth.json:

  CASE-001/002/003/007/012   verdict=legitimate  (benign flows)
  CASE-004/006/008/011/017/018  card_not_present_fraud (online burst, known device)
  CASE-005/010/013/015/016/020  card_not_present_new_device (burst on a NEW device)
  CASE-009/014               undocumented        (large shared-device syndicate)
  CASE-019                   account_takeover    (new device + mixed channel + proxy)
  CASE-004 group also gets   prior confirmed-fraud card history (drivers risk).

Cards are derived downstream by backend/scripts/prepare_data.py using
fingerprint = md5(customer_id|card1..card6), so the generator writes the
card1..card6 fields consistently per virtual card and keeps
known[txn_id → card_id] mappings consistent between case_pack and
closed_cases_history.

Run:  python scripts/make_synthetic_data.py
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

SEED = 20261030
NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


def _ts(dt: datetime) -> str:
    """ISO timestamp with explicit UTC offset (safe for fromisoformat everywhere)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _ts_space(dt: datetime) -> str:
    """Space separated variant used in the transactions.csv 'ts' column."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ─── Population constants ──────────────────────────────────────────────────────
N_CUSTOMERS = 600
PRODUCTS = ["W", "C", "R", "H", "S", "P"]
PRODUCT_W = [30, 25, 10, 15, 10, 10]
EMAILS = ["gmail.com", "outlook.com", "yahoo.com", "hotmail.com", "synthmail.example"]
OS_LIST = ["Windows 10", "Windows 11", "macOS 11.6.1", "iOS 16.2", "Android 12"]
BROWSER_LIST = ["chrome 123.0", "safari 17.4", "firefox 122.0", "edge 123.0"]
SCREEN_LIST = ["1920x1080", "1366x768", "1440x900", "390x844", "412x915"]
DEVICE_INFO_LIST = [
    "Samsung SM-G973F map400 Playlist for Android",
    "Windows Desktop MatchOS windows x64 dggfwmdd",
    "IOS Device (Apple)",
    "Mac OS X 10_15_5 Firefox 89.0",
    "Linux x86_64 Chrome 96.0",
]
AMOUNT_MEAN, AMOUNT_MAX = 95.0, 480.0
TXN_WINDOW_DAYS = 115

# ─── Ground truth for the 20 synthetic cases (matches cases/ground_truth.json) ─
GROUND_TRUTH = {
    "CASE-001": ("legitimate", "none"),
    "CASE-002": ("legitimate", "none"),
    "CASE-003": ("legitimate", "none"),
    "CASE-004": ("fraud", "card_not_present_fraud"),
    "CASE-005": ("fraud", "card_not_present_new_device"),
    "CASE-006": ("fraud", "card_not_present_fraud"),
    "CASE-007": ("legitimate", "none"),
    "CASE-008": ("fraud", "card_not_present_fraud"),
    "CASE-009": ("fraud", "undocumented"),
    "CASE-010": ("fraud", "card_not_present_new_device"),
    "CASE-011": ("fraud", "card_not_present_fraud"),
    "CASE-012": ("legitimate", "none"),
    "CASE-013": ("fraud", "card_not_present_new_device"),
    "CASE-014": ("fraud", "undocumented"),
    "CASE-015": ("fraud", "card_not_present_new_device"),
    "CASE-016": ("fraud", "card_not_present_new_device"),
    "CASE-017": ("fraud", "card_not_present_fraud"),
    "CASE-018": ("fraud", "card_not_present_fraud"),
    "CASE-019": ("fraud", "account_takeover"),
    "CASE-020": ("fraud", "card_not_present_new_device"),
}


def _fingerprint(customer_id: str, card1: int, card2: int, card3: int, card4: int, card5: int, card6: str) -> str:
    """Same key the production card-derivation uses."""
    key = "|".join(str(v) for v in [customer_id, card1, card2, card3, card4, card5, card6])
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ─── Base population ───────────────────────────────────────────────────────────
rng = random.Random(SEED)

customers: list[dict] = []
cards: list[dict] = []          # {"customer": cid, "card1": .., ..., "region_home": int, "email": str}
txn_rows: list[dict] = []
identity_rows: list[dict] = []  # keyed by TransactionID
closed_rows: list[dict] = []

_txn_seq = 4_000_000          # synthetic TransactionIDs start here


def _new_txn_id() -> int:
    global _txn_seq
    _txn_seq += 1
    return _txn_seq


def _add_customer(idx: int) -> dict:
    cid = f"SC-{idx:05d}"
    home_region = rng.choice([362, 414, 486, 527, 598, 246, 310])
    cust = {
        "id": cid,
        "home_region": home_region,
        "email": rng.choice(EMAILS),
        "n_cards": rng.choices([1, 2, 3], weights=[55, 35, 10])[0],
        "tx_activity": rng.choice(["low", "mid", "mid", "high"]),
    }
    customers.append(cust)
    return cust


def _add_card(cust: dict) -> dict:
    """One virtual card: stable fingerprint fields + behavioural profile."""
    card = {
        "customer": cust["id"],
        "card1": rng.randint(1500, 4800),
        "card2": rng.choice([100, 200, 300, 325, 360]),
        "card3": rng.choice([156, 185, 201, 221]),
        "card4": rng.choice([2000, 2000, 2000, 3000]),
        "card5": rng.randint(120, 240),
        "card6": rng.choice(["visa", "mastercard", "visa", "discover"]),
        "email": cust["email"],
        "fps": len(cards),
        "customer": cust,
    }
    card["fp"] = _fingerprint(cust["id"], card["card1"], card["card2"], card["card3"], card["card4"], card["card5"], card["card6"])
    cards.append(card)
    return card


def _normal_txn_ts(cust: dict) -> datetime:
    base = NOW - timedelta(days=rng.randint(2, TXN_WINDOW_DAYS))
    base += timedelta(hours=rng.randint(7, 23), minutes=rng.randint(0, 59), seconds=rng.randint(0, 59))
    return base


def _normal_amount(card: dict, cust: dict) -> float:
    if cust["tx_activity"] == "low":
        return round(rng.uniform(5, 60), 2)
    if cust["tx_activity"] == "high":
        return round(rng.uniform(40, AMOUNT_MAX), 2)
    return round(rng.uniform(10, 180), 2)


def _txn_row(
    txn_id: int, ts: datetime, card: dict, cust: dict,
    amount: float, product: str, channel: str, region: int | None,
    risk_score: float, email: str | None = None,
) -> dict:
    c1 = rng.randint(1, 9)                 # count of addresses used on card
    c_count = rng.randint(1, 30)
    d1 = rng.randint(1, 20)
    row = {
        "TransactionID": str(txn_id),
        "TransactionDT": int((ts - datetime(2017, 12, 1, tzinfo=timezone.utc)).total_seconds()),
        "ts": _ts_space(ts),
        "channel": channel,
        "TransactionAmt": amount,
        "ProductCD": product,
        "card1": card["card1"], "card2": card["card2"], "card3": card["card3"],
        "card4": card["card4"], "card5": card["card5"], "card6": card["card6"],
        "addr1": region if region is not None else cust["home_region"],
        "addr2": rng.choice([302.0, 310.0, 318.5, None]),
        "dist1": rng.choice([0, 1, 2, 4, None]),
        "dist2": rng.choice([0, 1, 3, None]),
        "P_emaildomain": email or card["email"],
        "R_emaildomain": rng.choice(["gmail.com", None]),
        "customer_id": cust["id"],
        "risk_score": round(risk_score, 2),
    }
    # C1 = address count, C14 = transaction count; fill the rest as noise
    for i in range(2, 15):
        row[f"C{i}"] = round(rng.uniform(1, 40), 1)
    row["C1"] = float(c1)
    row["C14"] = float(c_count)
    for i in range(1, 6):
        row[f"D{i}"] = float(d1) if i == 1 else round(rng.uniform(1, 60), 1)
    for i in range(1, 10):
        row[f"M{i}"] = rng.choice(["T", "F", "M0"]) if i != 4 else rng.choice(["M0", "M1", "M2"])
    for i in (20, 45, 127, 130, 131, 307, 308, 309, 310):
        row[f"V{i}"] = round(rng.uniform(0, 200), 1)
    return row


_device_seq = 0


def _next_device_suffix() -> str:
    """Unique device suffix so profile collisions only happen where planted."""
    global _device_seq
    _device_seq += 1
    return f"{_device_seq:05d}"


def _identity_row(txn_id: str, is_new_device: bool = False, anomaly_match: bool = False,
                  device_id: str | None = None, os_in: str | None = None,
                  browser_in: str | None = None, screen_in: str | None = None) -> dict:
    dev_status = "New" if is_new_device else rng.choice(["Found", "Found", "Found", "NotFound", "Unknown"])
    if anomaly_match:
        # real dataset domain: "match_status:N"; 0 = mismatch anomaly
        match_status = "match_status:0"
    else:
        match_status = rng.choice(["match_status:2", "match_status:1", "match_status:0"])
    if device_id is None:
        device_id = _next_device_suffix()
    device_info = f"{rng.choice(DEVICE_INFO_LIST)} unit-{device_id}"
    proxy = rng.choice(["IP_PROXY:ANONYMOUS " + rng.choice(["argentina", "india", "netherlands"]),
                        "proxy transparent " + rng.choice(["brazil", "spain"]),
                        "NotFound", "NotFound", "NotFound"])
    return {
        "TransactionID": txn_id,
        "DeviceType": rng.choice(["desktop", "mobile"]),
        "DeviceInfo": device_info,
        "id_01": round(rng.uniform(0, 5), 2),
        "id_02": round(rng.uniform(1, 25), 1),
        "id_05": round(rng.uniform(0, 15), 1),
        "id_06": round(rng.uniform(0, 60), 1),
        "id_11": round(rng.uniform(0, 30), 1),
        "id_12": rng.choice(["Found", "NotFound"]),
        "id_13": rng.randint(1, 4),
        "id_14": round(rng.uniform(0, 10), 1),
        "id_15": dev_status,
        "id_16": rng.randint(1, 14),
        "id_23": proxy,
        "id_30": os_in or rng.choice(OS_LIST),
        "id_31": browser_in or rng.choice(BROWSER_LIST),
        "id_33": screen_in or rng.choice(SCREEN_LIST),
        "id_34": match_status,
        "id_35": rng.choice(["T", "F"]),
        "id_36": rng.choice(["T", "F"]),
        "id_37": rng.choice(["T", "F"]),
        "id_38": rng.choice(["Found", "NotFound"]),
    }


def populate_baselines() -> None:
    """Normal transaction flow across the whole population plus benign history."""
    for idx in range(1, N_CUSTOMERS + 1):
        cust = _add_customer(idx)
        for _ in range(cust["n_cards"]):
            card = _add_card(cust)
            n_txns = {"low": rng.randint(3, 8), "mid": rng.randint(9, 18), "high": rng.randint(19, 32)}[cust["tx_activity"]]
            has_idle = rng.random() < 0.25  # some cards have no activity in the window
            for _ in range(n_txns if not has_idle else max(1, n_txns // 2)):
                ts = _normal_txn_ts(cust)
                amount = _normal_amount(card, cust)
                product = rng.choices(PRODUCTS, weights=PRODUCT_W)[0]
                channel = "online" if rng.random() < 0.42 else "in_person"
                region = cust["home_region"] if rng.random() < 0.85 else None
                risk = round(rng.uniform(0.05, 0.38), 2)
                txn_rows.append(_txn_row(_new_txn_id(), ts, card, cust, amount, product, channel, region, risk))
    # Identity for a subset of the benign population
    for row in txn_rows[:]:
        if rng.random() < 0.34:
            identity_rows.append(_identity_row(row["TransactionID"]))


# ─── Closed-case memory rows ───────────────────────────────────────────────────
CC_SEQ = 4300              # avoids clashing with internal ids, cosmetic ONLY


def _new_cc_id() -> str:
    global CC_SEQ
    CC_SEQ += 1
    return f"CC-{CC_SEQ}"


def add_closed_case(
    customer_id: str, card_id: str, opened: datetime, outcome: str,
    pattern: str, txn_ids: list[str], exposure: float,
    connected: list[str] | None = None, notes: str = "", report: bool | None = None,
) -> str:
    """Record one historical closed case row for the agent's case memory."""
    global NOW
    if report is None:
        report = pattern not in ("none", "undocumented") or outcome == "confirmed_fraud"
    ccid = _new_cc_id()
    closed_rows.append({
        "case_id": ccid,
        "customer_id": customer_id,
        "card_id": card_id,
        "opened_at": _ts(opened),
        "closed_at": _ts(opened + timedelta(days=rng.randint(1, 9))),
        "outcome": outcome,
        "pattern": pattern,
        "first_fraud_txn_id": txn_ids[0] if (txn_ids and outcome == "confirmed_fraud") else "",
        "txn_ids": "|".join(txn_ids),
        "n_txns": len(txn_ids),
        "exposure_usd": exposure,
        "connected_card_ids": "|".join(connected or []),
        "actions_taken": rng.choice(["BLOCK_CARD", "BLOCK_CARD|FILE_REPORT", "MONITOR_CONNECTED_CARDS", "REQUEST_CUSTOMER_CONFIRMATION"]),
        "report_filed": "YES" if report else "NO",
        "analyst_notes": notes,
    })
    return ccid


# ─── Planted templates ────────────────────────────────────────────────────────
TRIGGER_SEQ_START = 350_000          # flagged txn ids for case scenarios live here
_scenario_rows: list[dict] = []      # case_id -> txn rows (kept but merged into txn_rows)


def _case_card(cust: dict) -> dict:
    """Fresh card for a planted case customer, always distinct fingerprint."""
    return _add_card(cust)


def _plant_benign(case_id: str, cust: dict, card: dict) -> dict:
    flagged_ts = NOW - timedelta(days=rng.randint(3, 14), hours=2)
    amount = _normal_amount(card, cust)
    flagged_id = _new_txn_id()
    flagged = _txn_row(flagged_id, flagged_ts, card, cust, amount,
                       "W", "in_person", None, rng.uniform(0.6, 0.65))
    identity_rows.append(_identity_row(str(flagged_id)))                       # device Found
    trigger_txt = (
        f"Trigger (risk_score): Real-time model scored transaction {flagged_id} "
        f"(${amount:.2f}, in billing region {cust['home_region']}) at "
        f"{round(rng.uniform(0.55, 0.68), 2)}. Review and decide."
    )
    return {
        "case_id": case_id,
        "flagged_txn_id": str(flagged_id),
        "card_id": f"{cust['id']}-K{card['fps'] + 1}",
        "customer_id": cust["id"],
        "trigger_type": "risk_score",
        "trigger_text": trigger_txt,
        "risk_score": round(rng.uniform(0.55, 0.68), 2),
        "opened_at": _ts(flagged_ts + timedelta(minutes=3)),
        "row": flagged,
    }


def _plant_burst(case_id: str, cust: dict, card: dict, pattern: str) -> dict:
    """card_not_present_fraud (burst on a KNOWN device) and,
    with is_new_device=True for puzzle cases, cnp_new_device cases."""
    burst_n = rng.choices([2, 3, 4], weights=[25, 55, 20])[0]
    base_ts = NOW - timedelta(days=rng.randint(3, 12), hours=rng.randint(4, 16))
    flagged_id = _new_txn_id()
    big_amount = round(_normal_amount(card, cust) * rng.uniform(3.1, 4.6), 2)
    is_new_device = pattern == "card_not_present_new_device"
    flagged_ts = base_ts + timedelta(hours=2, minutes=rng.randint(0, 40))
    flagged = _txn_row(
        flagged_id, flagged_ts, card, cust, big_amount, "W", "online",
        None, rng.uniform(0.82, 0.88),
    )
    burst_ids = [str(flagged_id)]
    burst = 0
    flagged_ident = _identity_row(str(flagged_id), is_new_device=is_new_device,
                                  anomaly_match=False, device_id=f"case{case_id}",
                                  os_in=f"synth-os-{case_id.lower()}",
                                  browser_in=f"synth-browser-{case_id.lower()}",
                                  screen_in=f"synth-screen-{case_id.lower()}")
    if pattern == "card_not_present_new_device":
        # deterministic new-device variant: New device + proxy so the README
        # tiebreakers favour card_not_present_new_device over plain CNP
        flagged_ident["id_23"] = "IP_PROXY:ANONYMOUS argentina"
    for b in range(burst_n - 1):
        burst_am = round(big_amount * rng.uniform(0.45, 0.95), 2)
        ts = flagged_ts + timedelta(hours=rng.uniform(1, 8), minutes=rng.randint(0, 50))
        tid = _new_txn_id()
        burst += 1
        txn_rows.append(_txn_row(tid, ts, card, cust, burst_am, "W", "online", None, rng.uniform(0.80, 0.9)))
        burst_ids.append(str(tid))
        # burst txns ride the same device profile as the flagged txn
        bident = dict(flagged_ident)
        bident["TransactionID"] = str(tid)
        bident["id_15"] = "Found"      # only the flagged txn carries the New-device flag
        identity_rows.append(bident)
    identity_rows.append(flagged_ident)
    device_info = flagged_ident["DeviceInfo"]
    debit_adds = burst_ids + [str(flagged_id)]
    trigger_txt = (
        f"Trigger (risk_score): Real-time model scored transaction {flagged_id} "
        f"(${big_amount:.2f}, in billing region 'domestic') at "
        f"{round(rng.uniform(0.8, 0.9), 2)}. Review and decide."
    )
    return {
        "case_id": case_id,
        "flagged_txn_id": str(flagged_id),
        "card_id": f"{cust['id']}-K{card['fps'] + 1}",
        "customer_id": cust["id"],
        "trigger_type": "risk_score",
        "trigger_text": trigger_txt,
        "risk_score": round(rng.uniform(0.8, 0.9), 2),
        "opened_at": _ts(flagged_ts + timedelta(minutes=4)),
        "row": flagged,
        "burst_txn_ids": burst_ids,
        "device_info": device_info,
    }


def _plant_account_takeover(case_id: str, cust: dict, card: dict) -> dict:
    flagged_ts = NOW - timedelta(days=rng.randint(3, 10), hours=3)
    flagged_id = _new_txn_id()
    amount = round(_normal_amount(card, cust) * rng.uniform(6, 9), 2)
    flagged = _txn_row(flagged_id, flagged_ts, card, cust, amount, "W", "online",
                       None, rng.uniform(0.86, 0.92))
    # New device + proxy + match anomaly => account_takeover signature
    # (id_34 uses the real dataset domain; "match_status:0" is the mismatch anomaly
    # the pattern detector keys on)
    flagged_ident = _identity_row(str(flagged_id), is_new_device=True, anomaly_match=True,
                                  device_id=f"case{case_id}",
                                  os_in=f"synth-os-{case_id.lower()}",
                                  browser_in=f"synth-browser-{case_id.lower()}",
                                  screen_in=f"synth-screen-{case_id.lower()}")
    flagged_ident["id_23"] = "IP_PROXY:ANONYMOUS argentina"
    identity_rows.append(flagged_ident)
    # Mixed-channel burst right before
    chan_ids = []
    for h in (16, 25, 33):
        tid = _new_txn_id()
        ch = "in_person" if h == 16 else "online"
        txn_rows.append(_txn_row(tid, flagged_ts - timedelta(hours=h), card, cust,
                                 round(rng.uniform(40, 160), 2), "W", ch, None, 0.72))
        chan_ids.append(str(tid))
        # prior activity rides the same device profile (all "Found" except flagged)
        cident = dict(flagged_ident)
        cident["TransactionID"] = str(tid)
        cident["id_15"] = "Found"
        cident["id_23"] = "NotFound"
        cident["id_34"] = "match_status:2"
        identity_rows.append(cident)
    exposure = amount + sum(float(a) for a in [120.0, 80.0, 150.0])
    trigger_txt = (
        f"Trigger (risk_score): Real-time model scored transaction {flagged_id} "
        f"(${amount:.2f}, billing mismatch) at {round(rng.uniform(0.85, 0.92), 2)}. Review and decide."
    )
    return {
        "case_id": case_id,
        "flagged_txn_id": str(flagged_id),
        "card_id": f"{cust['id']}-K{card['fps'] + 1}",
        "customer_id": cust["id"],
        "trigger_type": "risk_score",
        "trigger_text": trigger_txt,
        "risk_score": round(rng.uniform(0.85, 0.92), 2),
        "opened_at": _ts(flagged_ts + timedelta(minutes=6)),
        "row": flagged,
        "prior_txn_ids": chan_ids,
        "exposure": exposure,
        "device_info": flagged_ident["DeviceInfo"],
    }


def _plant_syndicate(case_id: str, cust: dict, card: dict) -> dict:
    """Shared-device syndicate: >=15 other cards share the flagged device
    (drives undocumented per R9)."""
    flagged_ts = NOW - timedelta(days=rng.randint(4, 14), hours=1)
    flagged_id = _new_txn_id()
    amount = round(rng.uniform(700, 2400), 2)
    flagged = _txn_row(flagged_id, flagged_ts, card, cust, amount, "W", "online", None, rng.uniform(0.8, 0.9))
    flagged_ident = _identity_row(str(flagged_id), device_id=f"{case_id.lower()}-ring",
                                  os_in=f"synth-os-{case_id.lower()}-ring",
                                  browser_in=f"synth-browser-{case_id.lower()}",
                                  screen_in=f"synth-screen-{case_id.lower()}")
    flagged_ident["id_15"] = "Found"      # NOT new-device: prevents diverting to cnp_new_device
    flagged_ident["id_23"] = "NotFound"
    flagged_ident["id_34"] = "match_status:2"
    identity_rows.append(flagged_ident)
    device_info, os_v, browser, screen = (flagged_ident["DeviceInfo"], flagged_ident["id_30"],
                                          flagged_ident["id_31"], flagged_ident["id_33"])

    # 17 additional customer cards riding the SAME device label
    for i in range(17):
        rcust = _add_customer(9000 + i)
        while rcust["home_region"] in (None,):
            rcust = _add_customer(9000 + i)
        rcard = _add_card(rcust)
        is_fraud_member = i < 4
        ts = flagged_ts - timedelta(hours=rng.randint(3, 36))
        tid = _new_txn_id()
        amt = round(rng.uniform(2, 9), 2) if is_fraud_member else round(rng.uniform(12, 110), 2)
        risk = rng.uniform(0.75, 0.88) if is_fraud_member else rng.uniform(0.2, 0.5)
        row = _txn_row(tid, ts, rcard, rcust, amt, "W", "online", None, risk)
        txn_rows.append(row)
        ident = dict(flagged_ident)
        ident["TransactionID"] = str(tid)
        ident["id_15"] = "Found"
        ident["id_23"] = "NotFound"
        # id_34 uses the real dataset domain (match_status:N); "0" would be a
        # credential-mismatch anomaly we do not want on ordinary ring members
        ident["id_34"] = rng.choice(["match_status:2", "match_status:2", "match_status:1"])
        if is_fraud_member:
            ident["id_34"] = "match_status:1"
        identity_rows.append(ident)
        device_tuple = (device_info, os_v, browser, screen)
        if is_fraud_member:
            # NOTE: do not mention the ring device string here — the ring count
            # works off card_id, and device-linked cases would set
            # prior_fraud_cases > 0, which suppresses the R9 undocumented gate.
            add_closed_case(rcust["id"], f"{rcust['id']}-K1", ts,
                            "confirmed_fraud", "card_testing", [str(tid)], amt,
                            notes=("Confirmed card-testing on syndicate member; "
                                   "micro-authorization sequence before larger cash-out."))
    # A couple of tiny txn sequences shared across the ring for realism
    tiny_ids = []
    for h in (2, 4, 6):
        tid = _new_txn_id()
        txn_rows.append(_txn_row(tid, flagged_ts - timedelta(hours=h), card, cust, round(rng.uniform(1.5, 6), 2), "W", "online", None, 0.7))
        tiny_ids.append(str(tid))
    for tid in tiny_ids:
        tident = dict(flagged_ident)
        tident["TransactionID"] = tid
        identity_rows.append(tident)
    trigger_txt = (
        f"Trigger (risk_score): Real-time model scored transaction {flagged_id} "
        f"(${amount:.2f}) at {round(rng.uniform(0.8, 0.9), 2)}. Review and decide."
    )
    return {
        "case_id": case_id,
        "flagged_txn_id": str(flagged_id),
        "card_id": f"{cust['id']}-K{card['fps'] + 1}",
        "customer_id": cust["id"],
        "trigger_type": "risk_score",
        "trigger_text": trigger_txt,
        "risk_score": round(rng.uniform(0.8, 0.9), 2),
        "opened_at": _ts(flagged_ts + timedelta(minutes=8)),
        "row": flagged,
        "exposure": amount,
        "prior_txn_ids": tiny_ids,
        "device_info": flagged_ident["DeviceInfo"],
    }


# ─── Case pack assembly ────────────────────────────────────────────────────────


def build_cases() -> list[dict]:
    """Build the 20 scenario trigger rows in a deterministic order."""
    LEGIT = ["CASE-001", "CASE-002", "CASE-003", "CASE-007", "CASE-012"]
    BURST_KNOWN = ["CASE-004", "CASE-006", "CASE-008", "CASE-011", "CASE-017", "CASE-018"]
    BURST_NEW = ["CASE-005", "CASE-010", "CASE-013", "CASE-015", "CASE-016", "CASE-020"]
    SYNDICATE = ["CASE-009", "CASE-014"]
    ATO = ["CASE-019"]
    plan: list[tuple[str, str]] = []
    for cid in LEGIT:
        plan.append((cid, "benign"))
    for cid in BURST_KNOWN:
        plan.append((cid, "burst"))
    for cid in BURST_NEW:
        plan.append((cid, "burst_new"))
    for cid in SYNDICATE:
        plan.append((cid, "syndicate"))
    for cid in ATO:
        plan.append((cid, "ato"))
    triggers = {}
    for cid, kind in plan:
        cust = _add_customer(3000 + int(cid.split("-")[1]))
        card = _case_card(cust)
        triggers[cid] = (cust, card, kind)
    rows = []
    for cid, kind in plan:
        cust, card, _ = triggers[cid]
        if kind == "benign":
            sc = _plant_benign(cid, cust, card)
        elif kind == "burst":
            sc = _plant_burst(cid, cust, card, "card_not_present_fraud")
        elif kind == "burst_new":
            sc = _plant_burst(cid, cust, card, "card_not_present_new_device")
        elif kind == "syndicate":
            sc = _plant_syndicate(cid, cust, card)
        else:
            sc = _plant_account_takeover(cid, cust, card)
        rows.append(sc)
    return rows


# ─── CSV writers ───────────────────────────────────────────────────────────────
IDENTITY_KEEP = [
    "TransactionID", "id_01", "id_02", "id_05", "id_06", "id_11", "id_12",
    "id_13", "id_14", "id_15", "id_16", "id_23", "id_30", "id_31", "id_33",
    "id_34", "id_35", "id_36", "id_37", "id_38", "DeviceType", "DeviceInfo",
]


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    print(f"wrote {path} ({len(df)} rows)")


def main() -> None:
    random.seed(SEED)
    populate_baselines()
    scenarios = build_cases()
    scenario_txn_rows = []
    for sc in scenarios:
        scenario_txn_rows.append(sc.pop("row"))
    # Merge scenario txns with base txns and build identity rows for each scenario txn not already present
    all_txn_rows = txn_rows + scenario_txn_rows
    have_identity = {i["TransactionID"] for i in identity_rows}
    for sc in scenarios:
        if sc["flagged_txn_id"] not in have_identity:
            identity_rows.append(_identity_row(sc["flagged_txn_id"], is_new_device=False))
        for tid in sc.get("burst_txn_ids", []) + sc.get("prior_txn_ids", []):
            if tid not in have_identity:
                identity_rows.append(_identity_row(tid, is_new_device=False))

    # Historical closed-case memory: one cleared + one confirmed pattern for
    # each planted fraud card so graph evidenced lookups see prior knowledge.
    for sc in scenarios:
        trig = sc["trigger_type"]
        is_undocumented = GROUND_TRUTH[sc["case_id"]][1] == "undocumented"
        notes = f"Prior confirmed fraud for synthetic {sc['case_id']} subject."
        if trig == "risk_score" and GROUND_TRUTH[sc["case_id"]][0] == "fraud" and not is_undocumented:
            # Confirmed prior fraud on this device profile. The device string in
            # the notes links the case to the flagged device label
            # (get_closed_cases_by_device matches analyst_notes LIKE %DeviceInfo%),
            # so device_linked_fraud >= 1 at investigation time.
            first_burst = (sc.get("burst_txn_ids") or [sc["flagged_txn_id"]])[0]
            device = sc.get("device_info", "")
            add_closed_case(
                sc["customer_id"], sc["card_id"],
                opened=NOW - timedelta(days=rng.randint(200, 300)),
                outcome="confirmed_fraud", pattern=GROUND_TRUTH[sc["case_id"]][1],
                txn_ids=[first_burst], exposure=rng.uniform(2_000, 12_000),
                notes=f"{notes} Device profile on file: {device}.",
            )
        else:
            # Syndicate subjects must keep prior_fraud_cases == 0 (the R9
            # undocumented pattern requires no prior fraud on the flagged
            # customer/card) — a cleared case supplies the history instead.
            add_closed_case(
                sc["customer_id"], sc["card_id"],
                opened=NOW - timedelta(days=rng.randint(200, 300)),
                outcome="cleared", pattern="none",
                txn_ids=[sc["flagged_txn_id"]], exposure=rng.uniform(30, 480),
                notes="Prior cleared legit flow for synthetic subject.",
            )

    trans_df = pd.DataFrame(all_txn_rows)
    identity_df = pd.DataFrame(identity_rows, columns=IDENTITY_KEEP)
    closed_df = pd.DataFrame(closed_rows)
    pack_df = pd.DataFrame([{
        "case_id": sc["case_id"],
        "opened_at": sc["opened_at"],
        "trigger_type": sc["trigger_type"],
        "trigger_text": sc["trigger_text"],
        "flagged_txn_id": sc["flagged_txn_id"],
        "card_id": sc["card_id"],
        "customer_id": sc["customer_id"],
        "risk_score": sc["risk_score"],
    } for sc in scenarios])

    out = Path(__file__).resolve().parent.parent / "data" / "synthetic"
    trans_df = trans_df.sort_values("ts").reset_index(drop=True)
    _write_csv(trans_df, out / "transactions.csv")
    _write_csv(identity_df, out / "identity.csv")
    _write_csv(closed_df, out / "closed_cases_history.csv")
    _write_csv(pack_df, out / "case_pack.csv")
    print(f"total customers={N_CUSTOMERS} cards={len(cards)} txns={len(trans_df)} identity={len(identity_df)} closed={len(closed_df)}")


if __name__ == "__main__":
    main()
