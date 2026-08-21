"""
Tests for matching.engine — batch matching & deterministic resolution.

Covers:
    1. Exact match (delta == 0)
    2. Tolerance match (0 < |delta| <= tolerance)
    3. Mismatch (|delta| > tolerance)
    4. Multiple batches in one run (mixed outcomes)
    5. Unknown fee category defaults to zero fee
    6. Missing settlement entry treated as mismatch
    7. Fee-schedule loader validation
"""

from __future__ import annotations

import textwrap
import pathlib

import pandas as pd
import pytest

from matching.engine import (
    BatchResult,
    MatchStatus,
    compute_fee,
    load_fee_schedule,
    match_batches,
    resolved,
    unresolved,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fee_schedule() -> pd.DataFrame:
    """In-memory fee schedule (percentage 2 % for 'payment', flat 5 for 'refund')."""
    df = pd.DataFrame([
        {"fee_category": "payment", "fee_type": "percentage", "fee_value": 2.0},
        {"fee_category": "refund",  "fee_type": "flat",       "fee_value": 5.0},
    ])
    return df.set_index("fee_category")


def _ledger(*rows) -> pd.DataFrame:
    """Helper: build a ledger DataFrame from (batch_id, amount, fee_category) tuples."""
    return pd.DataFrame(rows, columns=["settlement_batch_id", "amount", "fee_category"])


def _settlements(*rows) -> pd.DataFrame:
    """Helper: build a settlements DataFrame from (batch_id, payout_total) tuples."""
    return pd.DataFrame(rows, columns=["settlement_batch_id", "payout_total"])


# ---------------------------------------------------------------------------
# compute_fee unit tests
# ---------------------------------------------------------------------------

class TestComputeFee:
    def test_percentage_fee(self):
        assert compute_fee(1000.0, "percentage", 2.0) == 20.0

    def test_flat_fee(self):
        assert compute_fee(1000.0, "flat", 5.0) == 5.0

    def test_unknown_fee_type_raises(self):
        with pytest.raises(ValueError, match="Unknown fee_type"):
            compute_fee(100.0, "unknown", 10.0)


# ---------------------------------------------------------------------------
# Exact-match tests
# ---------------------------------------------------------------------------

class TestExactMatch:
    """Payout exactly equals ledger total minus fees → MATCHED."""

    def test_single_payment_row(self, fee_schedule):
        # 1000 - 2% fee = 980
        ledger = _ledger(("B1", 1000.0, "payment"))
        settlements = _settlements(("B1", 980.0))
        results = match_batches(ledger, settlements, fee_schedule)

        assert len(results) == 1
        r = results[0]
        assert r.status == MatchStatus.MATCHED
        assert r.ledger_total == 1000.0
        assert r.total_fees == 20.0
        assert r.expected_net == 980.0
        assert r.payout_total == 980.0
        assert r.delta == 0.0

    def test_multiple_rows_same_batch(self, fee_schedule):
        # Two payments: 500 + 300 = 800, fees 2%: 10 + 6 = 16, net = 784
        ledger = _ledger(
            ("B1", 500.0, "payment"),
            ("B1", 300.0, "payment"),
        )
        settlements = _settlements(("B1", 784.0))
        results = match_batches(ledger, settlements, fee_schedule)

        assert len(results) == 1
        assert results[0].status == MatchStatus.MATCHED
        assert results[0].expected_net == 784.0

    def test_mixed_fee_categories(self, fee_schedule):
        # payment 1000 → fee 20; refund 200 → flat fee 5; net = 1200 - 25 = 1175
        ledger = _ledger(
            ("B1", 1000.0, "payment"),
            ("B1", 200.0, "refund"),
        )
        settlements = _settlements(("B1", 1175.0))
        results = match_batches(ledger, settlements, fee_schedule)

        assert results[0].status == MatchStatus.MATCHED
        assert results[0].total_fees == 25.0
        assert results[0].fee_breakdown == {"payment": 20.0, "refund": 5.0}


# ---------------------------------------------------------------------------
# Tolerance-match tests
# ---------------------------------------------------------------------------

class TestToleranceMatch:
    """Payout is within tolerance but not exact → TOLERANCE_MATCHED."""

    def test_within_tolerance(self, fee_schedule):
        # Expected net = 980, payout = 979.50, delta = 0.50, tolerance = 1.0
        ledger = _ledger(("B1", 1000.0, "payment"))
        settlements = _settlements(("B1", 979.50))
        results = match_batches(ledger, settlements, fee_schedule, tolerance=1.0)

        assert results[0].status == MatchStatus.TOLERANCE_MATCHED
        assert results[0].delta == 0.50

    def test_at_tolerance_boundary(self, fee_schedule):
        # delta == tolerance exactly → still within tolerance
        ledger = _ledger(("B1", 1000.0, "payment"))
        settlements = _settlements(("B1", 978.0))
        results = match_batches(ledger, settlements, fee_schedule, tolerance=2.0)

        assert results[0].status == MatchStatus.TOLERANCE_MATCHED
        assert results[0].delta == 2.0

    def test_negative_delta_within_tolerance(self, fee_schedule):
        # Payout is slightly MORE than expected (overpayment)
        # Expected net = 980, payout = 980.80, delta = -0.80
        ledger = _ledger(("B1", 1000.0, "payment"))
        settlements = _settlements(("B1", 980.80))
        results = match_batches(ledger, settlements, fee_schedule, tolerance=1.0)

        assert results[0].status == MatchStatus.TOLERANCE_MATCHED
        assert results[0].delta == -0.80


# ---------------------------------------------------------------------------
# Mismatch tests
# ---------------------------------------------------------------------------

class TestMismatch:
    """Payout differs beyond tolerance → MISMATCHED."""

    def test_clear_mismatch_no_tolerance(self, fee_schedule):
        # Expected 980, payout 950
        ledger = _ledger(("B1", 1000.0, "payment"))
        settlements = _settlements(("B1", 950.0))
        results = match_batches(ledger, settlements, fee_schedule)

        assert results[0].status == MatchStatus.MISMATCHED
        assert results[0].delta == 30.0

    def test_just_outside_tolerance(self, fee_schedule):
        # Expected 980, payout 977.99, delta = 2.01, tolerance = 2.0
        ledger = _ledger(("B1", 1000.0, "payment"))
        settlements = _settlements(("B1", 977.99))
        results = match_batches(ledger, settlements, fee_schedule, tolerance=2.0)

        assert results[0].status == MatchStatus.MISMATCHED
        assert results[0].delta == 2.01

    def test_missing_settlement_entry(self, fee_schedule):
        # No settlement row for B1 → payout defaults to 0 → mismatch
        ledger = _ledger(("B1", 1000.0, "payment"))
        settlements = _settlements()  # empty
        results = match_batches(ledger, settlements, fee_schedule)

        assert results[0].status == MatchStatus.MISMATCHED
        assert results[0].payout_total == 0.0


# ---------------------------------------------------------------------------
# Multi-batch & edge-case tests
# ---------------------------------------------------------------------------

class TestMultiBatch:
    """Multiple batches processed in one call, mixed outcomes."""

    def test_mixed_outcomes(self, fee_schedule):
        ledger = _ledger(
            ("B1", 1000.0, "payment"),  # net 980
            ("B2", 500.0,  "payment"),  # net 490
            ("B3", 200.0,  "refund"),   # net 195
        )
        settlements = _settlements(
            ("B1", 980.0),   # exact match
            ("B2", 489.0),   # delta = 1.0
            ("B3", 100.0),   # big mismatch
        )
        results = match_batches(ledger, settlements, fee_schedule, tolerance=1.0)

        by_id = {r.settlement_batch_id: r for r in results}
        assert by_id["B1"].status == MatchStatus.MATCHED
        assert by_id["B2"].status == MatchStatus.TOLERANCE_MATCHED
        assert by_id["B3"].status == MatchStatus.MISMATCHED

        assert len(resolved(results)) == 2
        assert len(unresolved(results)) == 1


class TestUnknownFeeCategory:
    """Ledger rows with a fee category not in the schedule → zero fee."""

    def test_unknown_category_zero_fee(self, fee_schedule):
        ledger = _ledger(("B1", 1000.0, "mystery"))
        settlements = _settlements(("B1", 1000.0))
        results = match_batches(ledger, settlements, fee_schedule)

        assert results[0].total_fees == 0.0
        assert results[0].status == MatchStatus.MATCHED


# ---------------------------------------------------------------------------
# Fee schedule loader tests
# ---------------------------------------------------------------------------

class TestLoadFeeSchedule:
    def test_loads_valid_csv(self, tmp_path):
        csv = tmp_path / "fees.csv"
        csv.write_text("fee_category,fee_type,fee_value\npayment,percentage,2.0\n")
        df = load_fee_schedule(csv)
        assert "payment" in df.index
        assert df.loc["payment", "fee_value"] == 2.0

    def test_rejects_missing_columns(self, tmp_path):
        csv = tmp_path / "bad.csv"
        csv.write_text("category,type,value\na,b,1\n")
        with pytest.raises(ValueError, match="missing columns"):
            load_fee_schedule(csv)
