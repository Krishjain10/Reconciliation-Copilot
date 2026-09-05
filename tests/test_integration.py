"""
tests.test_integration — Full Integration & Stress-Test Suite

Comprehensive checklist covering every code path:
    1.  End-to-end pipeline with sample data
    2.  All-matching scenario (no mismatches)
    3.  All-mismatching scenario (every batch unresolved)
    4.  Negative delta (overpayment)
    5.  Zero-amount ledger rows
    6.  Very large amounts (must NOT trigger PII guard)
    7.  Duplicate batch IDs in settlement file
    8.  Ledger batch with no settlement entry
    9.  Settlement batch with no ledger entry (ignored gracefully)
    10. PII guard on every LLM code path
    11. PII guard with decimal large numbers (no false positive)
    12. PII guard with integer-like strings (should catch)
    13. Edge-case file: missing columns
    14. Edge-case file: bad amounts
    15. Edge-case file: empty file
    16. Anonymizer handles empty / None fields
    17. High tolerance (everything resolves)
    18. Zero tolerance (strict matching)
    19. Mixed fee categories with unknown category
    20. Pipeline returns correct structure
"""

from __future__ import annotations

import pathlib
import sys

import pandas as pd
import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from agent.anonymize import Anonymizer, SENSITIVE_FIELDS
from agent.pii_guard import PIILeakError, pii_guard
from agent.explain import explain_mismatch
from ingestion.loader import load_ledger, load_settlements
from matching.engine import (
    BatchResult,
    MatchStatus,
    compute_fee,
    load_fee_schedule,
    match_batches,
    resolved,
    unresolved,
)
from ui.app import run_pipeline
from ui.mock_llm import create_fallback_llm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fee_schedule():
    return pd.DataFrame([
        {"fee_category": "payment", "fee_type": "percentage", "fee_value": 2.0},
        {"fee_category": "refund",  "fee_type": "flat",       "fee_value": 5.0},
    ]).set_index("fee_category")


def _ledger(*rows):
    return pd.DataFrame(rows, columns=[
        "order_id", "settlement_batch_id", "amount", "fee_category",
    ])


def _settlements(*rows):
    cols = ["settlement_batch_id", "payout_total"]
    return pd.DataFrame(rows, columns=cols)


def _settlements_with_pii(*rows):
    cols = [
        "settlement_batch_id", "payout_total", "utr", "date",
        "account_number", "beneficiary_name", "ifsc_code",
    ]
    return pd.DataFrame(rows, columns=cols)


# ═══════════════════════════════════════════════════════════════════════════
# 1. End-to-end pipeline with sample data files
# ═══════════════════════════════════════════════════════════════════════════

class TestEndToEndSampleData:
    def test_pipeline_with_sample_files(self):
        data = _ROOT / "data"
        ledger = load_ledger(data / "sample_ledger.csv")
        settlements = load_settlements(data / "sample_settlements.csv")
        fees = load_fee_schedule(data / "fee_schedule.csv")
        result = run_pipeline(ledger, settlements, fees, tolerance=1.0)

        assert len(result["all_results"]) == 5
        assert len(result["resolved"]) == 3       # 2 exact + 1 tolerance
        assert len(result["tolerance_matched"]) == 1
        assert len(result["unresolved"]) == 2
        assert len(result["explanations"]) == 2
        assert len(result["audit_log"]) == 2

    def test_pipeline_result_structure(self):
        data = _ROOT / "data"
        ledger = load_ledger(data / "sample_ledger.csv")
        settlements = load_settlements(data / "sample_settlements.csv")
        fees = load_fee_schedule(data / "fee_schedule.csv")
        result = run_pipeline(ledger, settlements, fees, tolerance=1.0)

        required_keys = {
            "all_results", "resolved", "tolerance_matched",
            "unresolved", "explanations", "audit_log",
        }
        assert required_keys.issubset(result.keys())

        for expl in result["explanations"]:
            assert "explanation" in expl
            assert "confidence" in expl
            assert "settlement_batch_id" in expl
            assert isinstance(expl["explanation"], str)
            assert len(expl["explanation"]) > 0
            assert 0.0 <= expl["confidence"] <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# 2. All-matching scenario
# ═══════════════════════════════════════════════════════════════════════════

class TestAllMatching:
    def test_no_mismatches(self):
        ledger = _ledger(
            ("O1", "B1", 1000.0, "payment"),
            ("O2", "B2", 2000.0, "payment"),
        )
        settlements = _settlements(("B1", 980.0), ("B2", 1960.0))
        result = run_pipeline(ledger, settlements, _fee_schedule())

        assert len(result["resolved"]) == 2
        assert len(result["unresolved"]) == 0
        assert len(result["explanations"]) == 0
        assert len(result["audit_log"]) == 0


# ═══════════════════════════════════════════════════════════════════════════
# 3. All-mismatching scenario
# ═══════════════════════════════════════════════════════════════════════════

class TestAllMismatching:
    def test_all_unresolved(self):
        ledger = _ledger(
            ("O1", "B1", 1000.0, "payment"),
            ("O2", "B2", 2000.0, "payment"),
        )
        settlements = _settlements(("B1", 500.0), ("B2", 500.0))
        result = run_pipeline(ledger, settlements, _fee_schedule())

        assert len(result["resolved"]) == 0
        assert len(result["unresolved"]) == 2
        assert len(result["explanations"]) == 2


# ═══════════════════════════════════════════════════════════════════════════
# 4. Negative delta (overpayment)
# ═══════════════════════════════════════════════════════════════════════════

class TestNegativeDelta:
    def test_overpayment_produces_explanation(self):
        # Expected net = 980, payout = 1050, delta = -70
        ledger = _ledger(("O1", "B1", 1000.0, "payment"))
        settlements = _settlements(("B1", 1050.0))
        result = run_pipeline(ledger, settlements, _fee_schedule())

        assert len(result["explanations"]) == 1
        expl = result["explanations"][0]
        assert expl["delta"] == -70.0
        assert "more than expected" in expl["explanation"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# 5. Zero-amount ledger rows
# ═══════════════════════════════════════════════════════════════════════════

class TestZeroAmount:
    def test_zero_amount_row_no_crash(self):
        ledger = _ledger(
            ("O1", "B1", 0.0, "payment"),
            ("O2", "B1", 1000.0, "payment"),
        )
        settlements = _settlements(("B1", 980.0))
        results = match_batches(ledger, settlements, _fee_schedule())
        assert len(results) == 1
        # 1000 - 2%(1000) - 2%(0) = 980
        assert results[0].status == MatchStatus.MATCHED


# ═══════════════════════════════════════════════════════════════════════════
# 6. Very large amounts (must NOT trigger PII guard)
# ═══════════════════════════════════════════════════════════════════════════

class TestLargeAmounts:
    def test_large_amount_no_pii_false_positive(self):
        """A 10-billion-rupee amount must not trigger the PII guard.

        Expected net = 10B − 2% fee (200M) = 9.8B.
        Payout = 9.5B → delta = 300M → MISMATCHED → explanation generated.
        The 9/10+ digit amounts must flow through the PII guard without
        a false positive.
        """
        ledger = _ledger(("O1", "B1", 10_000_000_000.0, "payment"))
        settlements = _settlements(("B1", 9_500_000_000.0))
        # This should not raise PIILeakError
        result = run_pipeline(ledger, settlements, _fee_schedule())
        assert len(result["explanations"]) == 1

    def test_pii_guard_allows_decimal_large_numbers(self):
        """Large numbers with decimal points are amounts, not account numbers."""
        pii_guard("Ledger Total    : 10000000000.0")
        pii_guard("Expected Net    : 9800000000.0")
        pii_guard("Amount: 1234567890.50")


# ═══════════════════════════════════════════════════════════════════════════
# 7. Duplicate batch IDs in settlement
# ═══════════════════════════════════════════════════════════════════════════

class TestDuplicateSettlementBatch:
    def test_duplicate_settlement_uses_first(self):
        ledger = _ledger(("O1", "B1", 1000.0, "payment"))
        settlements = _settlements(("B1", 980.0), ("B1", 999.0))
        results = match_batches(ledger, settlements, _fee_schedule())
        # Should use the first entry (980.0) → exact match
        assert results[0].payout_total == 980.0
        assert results[0].status == MatchStatus.MATCHED


# ═══════════════════════════════════════════════════════════════════════════
# 8. Ledger batch with no settlement entry
# ═══════════════════════════════════════════════════════════════════════════

class TestMissingSettlement:
    def test_no_settlement_entry_is_mismatch(self):
        ledger = _ledger(("O1", "B1", 1000.0, "payment"))
        settlements = _settlements()  # empty
        results = match_batches(ledger, settlements, _fee_schedule())
        assert results[0].status == MatchStatus.MISMATCHED
        assert results[0].payout_total == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# 9. Settlement batch with no ledger entry (silently ignored)
# ═══════════════════════════════════════════════════════════════════════════

class TestOrphanSettlement:
    def test_extra_settlement_ignored(self):
        ledger = _ledger(("O1", "B1", 1000.0, "payment"))
        settlements = _settlements(("B1", 980.0), ("B_ORPHAN", 5000.0))
        results = match_batches(ledger, settlements, _fee_schedule())
        # Only B1 appears; B_ORPHAN is ignored
        assert len(results) == 1
        assert results[0].settlement_batch_id == "B1"


# ═══════════════════════════════════════════════════════════════════════════
# 10. PII guard on every LLM code path
# ═══════════════════════════════════════════════════════════════════════════

class TestPIIGuardAllPaths:
    def test_anonymized_data_passes_both_llm_calls(self):
        anon = Anonymizer()
        record = {
            "settlement_batch_id": "B1",
            "ledger_total": 5000.0,
            "total_fees": 100.0,
            "expected_net": 4900.0,
            "payout_total": 4500.0,
            "delta": 400.0,
            "fee_breakdown": {"payment": 100.0},
            "account_number": "920010055501234",
            "ifsc_code": "HDFC0001234",
            "beneficiary_name": "Test Person",
        }
        safe = anon.anonymize_record(record)
        mock = create_fallback_llm()
        result = explain_mismatch(safe, llm_callable=mock)

        # Both payloads must be clean
        for payload in result["llm_payloads"]:
            assert "920010055501234" not in payload
            assert "HDFC0001234" not in payload
            assert "Test Person" not in payload
            assert "TOK_" in payload

    def test_raw_pii_blocked_before_any_llm_call(self):
        record = {
            "settlement_batch_id": "B1",
            "ledger_total": 5000.0,
            "total_fees": 100.0,
            "expected_net": 4900.0,
            "payout_total": 4500.0,
            "delta": 400.0,
            "account_number": "920010055501234",
            "ifsc_code": "HDFC0001234",
        }
        calls = []
        def spy_llm(prompt):
            calls.append(prompt)
            return "test"

        with pytest.raises(PIILeakError):
            explain_mismatch(record, llm_callable=spy_llm)
        assert len(calls) == 0, "LLM must never be called when PII is present"

    def test_pipeline_pii_guard_with_settlement_pii(self):
        """Full pipeline: PII from settlement file must be anonymized."""
        ledger = _ledger(("O1", "B1", 1000.0, "payment"))
        settlements = _settlements_with_pii(
            ("B1", 500.0, "UTR001", "2024-01-01",
             "920010055501234", "Secret Person", "HDFC0001234"),
        )
        result = run_pipeline(ledger, settlements, _fee_schedule())

        for entry in result["audit_log"]:
            for payload in entry["llm_payloads"]:
                assert "920010055501234" not in payload
                assert "HDFC0001234" not in payload
                assert "Secret Person" not in payload


# ═══════════════════════════════════════════════════════════════════════════
# 11-12. PII guard edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestPIIGuardEdgeCases:
    def test_allows_short_numbers(self):
        pii_guard("amount 12345678")   # 8 digits — under threshold

    def test_catches_9_digit_number(self):
        with pytest.raises(PIILeakError):
            pii_guard("account 123456789")

    def test_allows_decimal_9_digit(self):
        pii_guard("amount 123456789.50")   # decimal → not an account

    def test_catches_ifsc(self):
        with pytest.raises(PIILeakError):
            pii_guard("bank HDFC0001234")

    def test_allows_lowercase_ifsc_like(self):
        pii_guard("code hdfc0001234")   # lowercase → not IFSC pattern

    def test_allows_token_strings(self):
        pii_guard("field TOK_A1B2C3D4E5F6G7H8 is safe")


# ═══════════════════════════════════════════════════════════════════════════
# 13-15. Edge-case file quarantine
# ═══════════════════════════════════════════════════════════════════════════

class TestEdgeCaseFiles:
    @pytest.fixture()
    def edge_dir(self):
        return _ROOT / "eval" / "edge_cases"

    def test_missing_columns_quarantined(self, edge_dir):
        with pytest.raises(ValueError, match="missing required columns"):
            load_ledger(edge_dir / "missing_columns.csv")

    def test_bad_amounts_quarantined(self, edge_dir):
        with pytest.raises(ValueError, match="non-numeric amount"):
            load_ledger(edge_dir / "bad_amounts.csv")

    def test_empty_file_quarantined(self, edge_dir):
        with pytest.raises(ValueError, match="empty"):
            load_ledger(edge_dir / "empty_file.csv")


# ═══════════════════════════════════════════════════════════════════════════
# 16. Anonymizer edge cases
# ═══════════════════════════════════════════════════════════════════════════

class TestAnonymizerEdgeCases:
    def test_empty_string_passthrough(self):
        anon = Anonymizer()
        assert anon.tokenize("") == ""

    def test_none_field_not_tokenized(self):
        anon = Anonymizer()
        record = {"account_number": None, "settlement_batch_id": "B1"}
        safe = anon.anonymize_record(record)
        assert safe["account_number"] is None

    def test_missing_field_not_added(self):
        anon = Anonymizer()
        record = {"settlement_batch_id": "B1"}
        safe = anon.anonymize_record(record)
        assert "account_number" not in safe


# ═══════════════════════════════════════════════════════════════════════════
# 17-18. Tolerance extremes
# ═══════════════════════════════════════════════════════════════════════════

class TestToleranceExtremes:
    def test_high_tolerance_resolves_everything(self):
        ledger = _ledger(("O1", "B1", 1000.0, "payment"))
        settlements = _settlements(("B1", 500.0))
        result = run_pipeline(
            ledger, settlements, _fee_schedule(), tolerance=99999.0,
        )
        assert len(result["unresolved"]) == 0
        assert len(result["explanations"]) == 0

    def test_zero_tolerance_strict(self):
        # Net = 980, payout = 980.01 → mismatch at tolerance 0
        ledger = _ledger(("O1", "B1", 1000.0, "payment"))
        settlements = _settlements(("B1", 980.01))
        results = match_batches(ledger, settlements, _fee_schedule(), tolerance=0.0)
        assert results[0].status == MatchStatus.MISMATCHED


# ═══════════════════════════════════════════════════════════════════════════
# 19. Unknown fee category
# ═══════════════════════════════════════════════════════════════════════════

class TestUnknownFeeInPipeline:
    def test_unknown_fee_zero_fee_applied(self):
        ledger = _ledger(("O1", "B1", 1000.0, "mystery_category"))
        settlements = _settlements(("B1", 1000.0))
        result = run_pipeline(ledger, settlements, _fee_schedule())
        # No fee deducted → net = 1000, payout = 1000 → matched
        assert len(result["resolved"]) == 1


# ═══════════════════════════════════════════════════════════════════════════
# 20. Confidence fallback
# ═══════════════════════════════════════════════════════════════════════════

class TestConfidenceFallback:
    def test_bad_llm_response_gives_0_5(self):
        anon = Anonymizer()
        record = {
            "settlement_batch_id": "B1",
            "ledger_total": 1000.0, "total_fees": 20.0,
            "expected_net": 980.0, "payout_total": 500.0,
            "delta": 480.0, "fee_breakdown": {},
        }

        def bad_llm(prompt):
            return "I don't know what confidence means"

        result = explain_mismatch(record, llm_callable=bad_llm)
        assert result["confidence"] == 0.5
