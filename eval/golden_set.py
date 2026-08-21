"""
eval.golden_set — Golden Evaluation Suite

A curated set of 8 reconciliation batches with known ground-truth
outcomes.  Measures how accurately the system:

    1. Classifies batches (matched / tolerance / mismatch)
    2. Explains the likely cause of each mismatch
    3. Assigns appropriate confidence scores
    4. Keeps PII out of every LLM payload

Run directly:
    python eval/golden_set.py
"""

from __future__ import annotations

import pathlib
import sys

# Ensure project root is importable
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd

from matching.engine import MatchStatus
from ui.app import run_pipeline


# ═══════════════════════════════════════════════════════════════════════════
# GOLDEN DATA
# ═══════════════════════════════════════════════════════════════════════════

GOLDEN_LEDGER = pd.DataFrame([
    # --- BATCH_G01  (exact match) -----------------------------------------
    {"order_id": "G001", "settlement_batch_id": "BATCH_G01",
     "amount": 3000.0, "fee_category": "payment"},
    {"order_id": "G002", "settlement_batch_id": "BATCH_G01",
     "amount": 2000.0, "fee_category": "payment"},
    # --- BATCH_G02  (exact match, mixed fee types) ------------------------
    {"order_id": "G003", "settlement_batch_id": "BATCH_G02",
     "amount": 4000.0, "fee_category": "payment"},
    {"order_id": "G004", "settlement_batch_id": "BATCH_G02",
     "amount": 1000.0, "fee_category": "refund"},
    # --- BATCH_G03  (tolerance match, delta = 1.0) ------------------------
    {"order_id": "G005", "settlement_batch_id": "BATCH_G03",
     "amount": 5000.0, "fee_category": "payment"},
    # --- BATCH_G04  (mismatch, small delta = 30) --------------------------
    {"order_id": "G006", "settlement_batch_id": "BATCH_G04",
     "amount": 6000.0, "fee_category": "payment"},
    {"order_id": "G007", "settlement_batch_id": "BATCH_G04",
     "amount": 4000.0, "fee_category": "payment"},
    # --- BATCH_G05  (mismatch, moderate delta = 90) -----------------------
    {"order_id": "G008", "settlement_batch_id": "BATCH_G05",
     "amount": 3000.0, "fee_category": "payment"},
    # --- BATCH_G06  (mismatch, large delta = 330) -------------------------
    {"order_id": "G009", "settlement_batch_id": "BATCH_G06",
     "amount": 2000.0, "fee_category": "payment"},
    {"order_id": "G010", "settlement_batch_id": "BATCH_G06",
     "amount": 1500.0, "fee_category": "payment"},
    # --- BATCH_G07  (exact match) -----------------------------------------
    {"order_id": "G011", "settlement_batch_id": "BATCH_G07",
     "amount": 8000.0, "fee_category": "payment"},
    # --- BATCH_G08  (mismatch, very large delta = 480) --------------------
    {"order_id": "G012", "settlement_batch_id": "BATCH_G08",
     "amount": 1000.0, "fee_category": "payment"},
])

#   Payout totals are set to produce specific match outcomes:
#   G01: 5000-2%(100)=4900  payout=4900 → exact
#   G02: 5000-80-5=4915     payout=4915 → exact
#   G03: 5000-100=4900      payout=4899 → tolerance (Δ1)
#   G04: 10000-200=9800     payout=9770 → mismatch (Δ30)
#   G05: 3000-60=2940       payout=2850 → mismatch (Δ90)
#   G06: 3500-70=3430       payout=3100 → mismatch (Δ330)
#   G07: 8000-160=7840      payout=7840 → exact
#   G08: 1000-20=980        payout=500  → mismatch (Δ480)

GOLDEN_SETTLEMENTS = pd.DataFrame([
    {"settlement_batch_id": "BATCH_G01", "payout_total": 4900.00,
     "utr": "UTR_G01", "date": "2024-02-01",
     "account_number": "910020033344455", "beneficiary_name": "Arjun Mehta",
     "ifsc_code": "HDFC0009876"},
    {"settlement_batch_id": "BATCH_G02", "payout_total": 4915.00,
     "utr": "UTR_G02", "date": "2024-02-01",
     "account_number": "820030044455566", "beneficiary_name": "Kavitha Iyer",
     "ifsc_code": "ICIC0008765"},
    {"settlement_batch_id": "BATCH_G03", "payout_total": 4899.00,
     "utr": "UTR_G03", "date": "2024-02-02",
     "account_number": "730040055566677", "beneficiary_name": "Suresh Nair",
     "ifsc_code": "SBIN0007654"},
    {"settlement_batch_id": "BATCH_G04", "payout_total": 9770.00,
     "utr": "UTR_G04", "date": "2024-02-02",
     "account_number": "640050066677788", "beneficiary_name": "Deepa Joshi",
     "ifsc_code": "UTIB0006543"},
    {"settlement_batch_id": "BATCH_G05", "payout_total": 2850.00,
     "utr": "UTR_G05", "date": "2024-02-03",
     "account_number": "550060077788899", "beneficiary_name": "Ramesh Rao",
     "ifsc_code": "PUNB0005432"},
    {"settlement_batch_id": "BATCH_G06", "payout_total": 3100.00,
     "utr": "UTR_G06", "date": "2024-02-03",
     "account_number": "460070088899900", "beneficiary_name": "Anita Das",
     "ifsc_code": "BARB0004321"},
    {"settlement_batch_id": "BATCH_G07", "payout_total": 7840.00,
     "utr": "UTR_G07", "date": "2024-02-04",
     "account_number": "370080099900011", "beneficiary_name": "Kiran Puri",
     "ifsc_code": "BKID0003210"},
    {"settlement_batch_id": "BATCH_G08", "payout_total": 500.00,
     "utr": "UTR_G08", "date": "2024-02-04",
     "account_number": "280090011011122", "beneficiary_name": "Meena Sen",
     "ifsc_code": "CNRB0002109"},
])

GOLDEN_FEE_SCHEDULE = pd.DataFrame([
    {"fee_category": "payment", "fee_type": "percentage", "fee_value": 2.0},
    {"fee_category": "refund",  "fee_type": "flat",       "fee_value": 5.0},
]).set_index("fee_category")

TOLERANCE = 2.0   # ₹2 tolerance for the eval run


# ═══════════════════════════════════════════════════════════════════════════
# EXPECTED OUTCOMES
# ═══════════════════════════════════════════════════════════════════════════

EXPECTED = {
    "BATCH_G01": {
        "status": MatchStatus.MATCHED,
        "delta": 0.0,
    },
    "BATCH_G02": {
        "status": MatchStatus.MATCHED,
        "delta": 0.0,
    },
    "BATCH_G03": {
        "status": MatchStatus.TOLERANCE_MATCHED,
        "delta": 1.0,
    },
    "BATCH_G04": {
        "status": MatchStatus.MISMATCHED,
        "delta": 30.0,
        # Small delta → expect keywords about rounding / minor fees / TDS
        "keywords": ["rounding", "minor", "processing", "tax", "TDS",
                      "deduction", "small"],
        "confidence_range": (0.60, 1.0),
    },
    "BATCH_G05": {
        "status": MatchStatus.MISMATCHED,
        "delta": 90.0,
        # Moderate delta → service charge / gateway fee / partial refund
        "keywords": ["service", "gateway", "additional", "partial",
                      "charge", "moderate", "conversion"],
        "confidence_range": (0.60, 1.0),
    },
    "BATCH_G06": {
        "status": MatchStatus.MISMATCHED,
        "delta": 330.0,
        # Large delta → missing transaction / chargeback / refund
        "keywords": ["missing", "chargeback", "refund", "unrecorded",
                      "significant", "fee structure"],
        "confidence_range": (0.40, 0.90),
    },
    "BATCH_G07": {
        "status": MatchStatus.MATCHED,
        "delta": 0.0,
    },
    "BATCH_G08": {
        "status": MatchStatus.MISMATCHED,
        "delta": 480.0,
        # Very large delta → missing transaction / chargeback
        "keywords": ["missing", "chargeback", "refund", "unrecorded",
                      "significant", "fee structure"],
        "confidence_range": (0.40, 0.90),
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# RAW PII VALUES  (must never appear in any LLM payload)
# ═══════════════════════════════════════════════════════════════════════════

RAW_PII_STRINGS = [
    "910020033344455", "820030044455566", "730040055566677",
    "640050066677788", "550060077788899", "460070088899900",
    "370080099900011", "280090011011122",
    "HDFC0009876", "ICIC0008765", "SBIN0007654", "UTIB0006543",
    "PUNB0005432", "BARB0004321", "BKID0003210", "CNRB0002109",
    "Arjun Mehta", "Kavitha Iyer", "Suresh Nair", "Deepa Joshi",
    "Ramesh Rao", "Anita Das", "Kiran Puri", "Meena Sen",
]


# ═══════════════════════════════════════════════════════════════════════════
# EVALUATION RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_evaluation() -> dict:
    """Run the golden evaluation and return a structured report dict."""

    result = run_pipeline(
        GOLDEN_LEDGER,
        GOLDEN_SETTLEMENTS,
        GOLDEN_FEE_SCHEDULE,
        tolerance=TOLERANCE,
    )

    # Build lookup by batch id
    status_by_id: dict[str, MatchStatus] = {}
    for r in result["all_results"]:
        status_by_id[r.settlement_batch_id] = r.status

    explanation_by_id: dict[str, dict] = {}
    for e in result["explanations"]:
        explanation_by_id[e["settlement_batch_id"]] = e

    # ── 1. Classification accuracy ─────────────────────────────────────
    classification_checks: list[dict] = []
    for batch_id, exp in EXPECTED.items():
        got = status_by_id.get(batch_id)
        ok = (got == exp["status"])
        classification_checks.append({
            "batch_id": batch_id,
            "expected": exp["status"].value,
            "got": got.value if got else "MISSING",
            "pass": ok,
        })
    class_pass = sum(c["pass"] for c in classification_checks)
    class_total = len(classification_checks)

    # ── 2. Explanation relevance ───────────────────────────────────────
    explanation_checks: list[dict] = []
    for batch_id, exp in EXPECTED.items():
        if "keywords" not in exp:
            continue
        expl_data = explanation_by_id.get(batch_id, {})
        text = expl_data.get("explanation", "").lower()
        found = [kw for kw in exp["keywords"] if kw.lower() in text]
        ok = len(found) >= 1
        explanation_checks.append({
            "batch_id": batch_id,
            "delta": exp["delta"],
            "keywords_found": found,
            "pass": ok,
            "explanation": expl_data.get("explanation", ""),
        })
    expl_pass = sum(c["pass"] for c in explanation_checks)
    expl_total = len(explanation_checks)

    # ── 3. Confidence calibration ──────────────────────────────────────
    confidence_checks: list[dict] = []
    for batch_id, exp in EXPECTED.items():
        if "confidence_range" not in exp:
            continue
        expl_data = explanation_by_id.get(batch_id, {})
        conf = expl_data.get("confidence", -1)
        lo, hi = exp["confidence_range"]
        ok = lo <= conf <= hi
        confidence_checks.append({
            "batch_id": batch_id,
            "confidence": conf,
            "expected_range": (lo, hi),
            "pass": ok,
        })
    conf_pass = sum(c["pass"] for c in confidence_checks)
    conf_total = len(confidence_checks)

    # ── 4. PII safety ─────────────────────────────────────────────────
    all_payloads: list[str] = []
    for entry in result["audit_log"]:
        all_payloads.extend(entry["llm_payloads"])
    pii_leaks: list[str] = []
    for payload in all_payloads:
        for pii in RAW_PII_STRINGS:
            if pii in payload:
                pii_leaks.append(pii)

    return {
        "classification": {
            "checks": classification_checks,
            "passed": class_pass,
            "total": class_total,
        },
        "explanation": {
            "checks": explanation_checks,
            "passed": expl_pass,
            "total": expl_total,
        },
        "confidence": {
            "checks": confidence_checks,
            "passed": conf_pass,
            "total": conf_total,
        },
        "pii_safety": {
            "total_payloads": len(all_payloads),
            "leaks": pii_leaks,
            "pass": len(pii_leaks) == 0,
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# PRETTY REPORT
# ═══════════════════════════════════════════════════════════════════════════

def print_report(report: dict) -> None:
    """Print a human-readable evaluation report."""
    cl = report["classification"]
    ex = report["explanation"]
    co = report["confidence"]
    pii = report["pii_safety"]

    w = 60
    print()
    print("=" * w)
    print("  GOLDEN EVALUATION REPORT")
    print("=" * w)
    print()

    def pct(n, d):
        return f"{n}/{d}  ({100*n/d:.1f}%)" if d else "N/A"

    print(f"  Classification Accuracy .... {pct(cl['passed'], cl['total'])}")
    print(f"  Explanation Relevance ...... {pct(ex['passed'], ex['total'])}")
    print(f"  Confidence Calibration ..... {pct(co['passed'], co['total'])}")
    pii_label = "PASS" if pii["pass"] else f"FAIL ({len(pii['leaks'])} leaks)"
    print(f"  PII Safety ................. {pii_label}  "
          f"({pii['total_payloads']} payloads checked)")

    # ── Detailed classification ────────────────────────────────────────
    print()
    print("-" * w)
    print("  CLASSIFICATION DETAILS")
    print("-" * w)
    for c in cl["checks"]:
        icon = "PASS" if c["pass"] else "FAIL"
        print(f"  {c['batch_id']}  expected={c['expected']:18s}  "
              f"got={c['got']:18s}  [{icon}]")

    # ── Explanation details ────────────────────────────────────────────
    print()
    print("-" * w)
    print("  MISMATCH EXPLANATION DETAILS")
    print("-" * w)
    for c in ex["checks"]:
        icon = "PASS" if c["pass"] else "FAIL"
        kws = ", ".join(c["keywords_found"]) or "(none)"
        print(f"  {c['batch_id']}  delta={c['delta']:<8.2f}  "
              f"keywords=[{kws}]  [{icon}]")
        snippet = c["explanation"][:100].replace("\n", " ")
        print(f"    \"{snippet}...\"")

    # ── Confidence details ─────────────────────────────────────────────
    print()
    print("-" * w)
    print("  CONFIDENCE CALIBRATION DETAILS")
    print("-" * w)
    for c in co["checks"]:
        icon = "PASS" if c["pass"] else "FAIL"
        lo, hi = c["expected_range"]
        print(f"  {c['batch_id']}  confidence={c['confidence']:.2f}  "
              f"expected=[{lo:.2f}-{hi:.2f}]  [{icon}]")

    # ── Summary ────────────────────────────────────────────────────────
    total_pass = cl["passed"] + ex["passed"] + co["passed"] + (1 if pii["pass"] else 0)
    total_checks = cl["total"] + ex["total"] + co["total"] + 1
    print()
    print("=" * w)
    print(f"  OVERALL ACCURACY: {pct(total_pass, total_checks)}")
    print("=" * w)
    print()


# ═══════════════════════════════════════════════════════════════════════════
# EDGE-CASE RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_edge_cases() -> list[dict]:
    """Test three malformed files and return results."""
    from ingestion.loader import load_ledger

    edge_dir = pathlib.Path(__file__).parent / "edge_cases"
    cases = [
        {
            "name": "Missing Columns",
            "file": edge_dir / "missing_columns.csv",
            "expect_substr": "missing required columns",
        },
        {
            "name": "Non-numeric Amounts",
            "file": edge_dir / "bad_amounts.csv",
            "expect_substr": "non-numeric amount",
        },
        {
            "name": "Empty File",
            "file": edge_dir / "empty_file.csv",
            "expect_substr": "empty",
        },
    ]

    results = []
    for case in cases:
        try:
            load_ledger(case["file"])
            results.append({
                "name": case["name"],
                "quarantined": False,
                "error": None,
                "message": "No error raised — file was accepted incorrectly.",
            })
        except ValueError as exc:
            msg = str(exc)
            results.append({
                "name": case["name"],
                "quarantined": True,
                "error": "ValueError",
                "message": msg,
                "keyword_found": case["expect_substr"].lower() in msg.lower(),
            })
        except Exception as exc:
            results.append({
                "name": case["name"],
                "quarantined": True,
                "error": type(exc).__name__,
                "message": str(exc),
                "keyword_found": False,
            })

    return results


def print_edge_report(results: list[dict]) -> None:
    """Print a human-readable edge-case report."""
    w = 60
    print()
    print("=" * w)
    print("  EDGE-CASE QUARANTINE REPORT")
    print("=" * w)
    print()

    all_ok = True
    for i, r in enumerate(results, 1):
        icon = "QUARANTINED" if r["quarantined"] else "NOT CAUGHT"
        if not r["quarantined"]:
            all_ok = False
        print(f"  Test {i}: {r['name']}")
        print(f"    Status:  {icon}  "
              f"{'PASS' if r['quarantined'] else 'FAIL'}")
        print(f"    Error:   {r.get('error', 'None')}")
        print(f"    Message: \"{r['message'][:80]}\"")
        print()

    print("=" * w)
    if all_ok:
        print("  ALL EDGE CASES QUARANTINED SUCCESSFULLY")
    else:
        print("  SOME EDGE CASES WERE NOT CAUGHT")
    print("=" * w)
    print()


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    import io as _io
    sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("\n>>> Running golden evaluation suite...\n")
    report = run_evaluation()
    print_report(report)

    print("\n>>> Running edge-case quarantine tests...\n")
    edge_results = run_edge_cases()
    print_edge_report(edge_results)


if __name__ == "__main__":
    main()
