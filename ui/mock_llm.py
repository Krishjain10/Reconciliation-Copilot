"""
ui.mock_llm — Deterministic rule-based fallback LLM for demo mode.

Provides a callable that mimics the LLM interface (prompt → response)
without requiring an API key, so the Streamlit app can always run.
"""

from __future__ import annotations

import re
from typing import Callable


def create_fallback_llm() -> Callable[[str], str]:
    """Return a deterministic rule-based LLM for the demo."""

    def fallback(prompt: str) -> str:
        # ---- confidence scoring call ------------------------------------
        if "Rate your confidence" in prompt:
            delta_m = re.search(r"Delta\s*:\s*([\-\d.]+)", prompt)
            if delta_m:
                delta = abs(float(delta_m.group(1)))
                if delta < 10:
                    return "0.92"
                if delta < 100:
                    return "0.78"
                if delta < 500:
                    return "0.65"
                return "0.45"
            return "0.70"

        # ---- explanation generation call --------------------------------
        delta_m = re.search(r"Delta\s*:\s*([\-\d.]+)", prompt)
        expected_m = re.search(r"Expected Net\s*:\s*([\d.]+)", prompt)
        payout_m = re.search(r"Payout Total\s*:\s*([\d.]+)", prompt)
        fees_m = re.search(r"Total Fees\s*:\s*([\d.]+)", prompt)

        delta = float(delta_m.group(1)) if delta_m else 0
        expected = float(expected_m.group(1)) if expected_m else 0
        payout = float(payout_m.group(1)) if payout_m else 0
        fees = float(fees_m.group(1)) if fees_m else 0

        parts: list[str] = []

        if delta > 0:
            parts.append(
                f"The settlement payout (₹{payout:,.2f}) is ₹{delta:,.2f} "
                f"less than the expected net amount (₹{expected:,.2f}) after "
                f"applying ₹{fees:,.2f} in known fees."
            )
            if delta < 50:
                parts.append(
                    "This small discrepancy is most likely caused by rounding "
                    "differences in fee calculations, minor processing charges, "
                    "or small tax deductions (such as TDS) applied by the bank "
                    "but not yet reflected in the merchant's fee schedule."
                )
            elif delta < 200:
                parts.append(
                    "This moderate discrepancy could indicate an additional "
                    "service charge or gateway fee not captured in the current "
                    "fee schedule, a partial refund processed at the bank level, "
                    "or a currency conversion adjustment on a cross-border "
                    "transaction."
                )
            else:
                parts.append(
                    "This significant discrepancy strongly suggests one or more "
                    "missing transactions in the batch — possibly an unrecorded "
                    "chargeback, a refund that was settled but not logged in the "
                    "ledger, or a fee structure change (e.g. a new surcharge "
                    "tier) that has not been updated in the merchant's records."
                )
        elif delta < 0:
            parts.append(
                f"The settlement payout (₹{payout:,.2f}) is ₹{abs(delta):,.2f} "
                f"more than expected (₹{expected:,.2f}). This overpayment may "
                f"indicate a credit adjustment, fee reversal, or incentive "
                f"payment from the payment processor."
            )
        else:
            parts.append("The amounts match exactly — no discrepancy found.")

        parts.append(
            "**Recommendation:** Cross-reference the bank statement line items "
            "for this settlement batch against the ledger entries to identify "
            "the specific transaction(s) causing the difference."
        )
        return " ".join(parts)

    return fallback
