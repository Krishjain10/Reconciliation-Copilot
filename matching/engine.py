"""
matching.engine — Batch Matching & Deterministic Resolution Engine

Groups ledger entries by settlement batch, applies fee deductions from
a fee schedule, and compares the net total to the settlement payout.
Batches that reconcile (within tolerance) are marked resolved; the rest
are emitted as unresolved mismatches with structured evidence.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import pandas as pd


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

class MatchStatus(Enum):
    """Outcome of comparing one settlement batch."""
    MATCHED = "matched"
    TOLERANCE_MATCHED = "tolerance_matched"
    MISMATCHED = "mismatched"


@dataclass
class BatchResult:
    """Evidence record produced for every settlement batch."""
    settlement_batch_id: str
    ledger_total: float
    total_fees: float
    expected_net: float          # ledger_total - total_fees
    payout_total: float          # from the settlement file
    delta: float                 # expected_net - payout_total
    status: MatchStatus
    fee_breakdown: dict = field(default_factory=dict)  # {category: fee_amount}


# ---------------------------------------------------------------------------
# Fee schedule loader
# ---------------------------------------------------------------------------

def load_fee_schedule(path: str | pathlib.Path) -> pd.DataFrame:
    """Load a fee schedule CSV.

    Expected columns:
        fee_category   – label that matches ledger rows (e.g. "payment", "refund")
        fee_type       – "percentage" or "flat"
        fee_value      – numeric value (percentage as 0-100 scale, flat in currency)

    Optional column:
        effective_from – date string (YYYY-MM-DD) from which this rate applies.
                         When present, the engine picks the fee row whose
                         effective_from is <= the transaction date.

    Returns a DataFrame indexed by *fee_category*.  If ``effective_from`` is
    present it is parsed but the index is still *fee_category* (may contain
    duplicate categories for different date ranges).
    """
    df = pd.read_csv(path)
    required = {"fee_category", "fee_type", "fee_value"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Fee schedule is missing columns: {missing}")
    df["fee_value"] = pd.to_numeric(df["fee_value"], errors="coerce")

    # Parse optional effective_from for date-aware fee lookup
    if "effective_from" in df.columns:
        df["effective_from"] = pd.to_datetime(
            df["effective_from"], errors="coerce",
        )
        df = df.sort_values(["fee_category", "effective_from"])

    return df.set_index("fee_category")


# ---------------------------------------------------------------------------
# Core matching logic
# ---------------------------------------------------------------------------

def compute_fee(amount: float, fee_type: str, fee_value: float) -> float:
    """Compute the fee for a single ledger row."""
    if fee_type == "percentage":
        return round(amount * fee_value / 100.0, 2)
    elif fee_type == "flat":
        return round(fee_value, 2)
    else:
        raise ValueError(f"Unknown fee_type: {fee_type!r}")


def _lookup_fee(
    fee_schedule: pd.DataFrame,
    category: str,
    txn_date: object = None,
) -> tuple:
    """Look up (fee_type, fee_value) for a category, optionally by date.

    If the fee schedule has an ``effective_from`` column and *txn_date* is
    provided, the row with the latest ``effective_from <= txn_date`` is used.
    Otherwise the first (or only) row for that category is returned.

    Returns (fee_type, fee_value) or (None, None) if not found.
    """
    if category not in fee_schedule.index:
        return None, None

    rows = fee_schedule.loc[[category]]

    has_date_col = "effective_from" in rows.columns
    if has_date_col and txn_date is not None:
        txn_dt = pd.Timestamp(txn_date)
        applicable = rows[rows["effective_from"] <= txn_dt]
        if not applicable.empty:
            best = applicable.iloc[-1]  # latest effective_from <= txn_date
            return best["fee_type"], float(best["fee_value"])
        # No applicable date — fall through to static lookup

    # Static (non-date) lookup
    if isinstance(rows, pd.DataFrame):
        row = rows.iloc[0]
    else:
        row = rows
    return row["fee_type"], float(row["fee_value"])


def match_batches(
    ledger: pd.DataFrame,
    settlements: pd.DataFrame,
    fee_schedule: pd.DataFrame,
    tolerance: float = 0.0,
) -> List[BatchResult]:
    """Run the deterministic batch-matching engine.

    Parameters
    ----------
    ledger : DataFrame
        Must contain columns: ``settlement_batch_id``, ``amount``,
        ``fee_category``.
    settlements : DataFrame
        Must contain columns: ``settlement_batch_id``, ``payout_total``.
    fee_schedule : DataFrame
        As returned by :func:`load_fee_schedule` (indexed by
        *fee_category*).
    tolerance : float, default 0.0
        Maximum absolute difference (in currency units) that is still
        considered a match.

    Returns
    -------
    list[BatchResult]
        One result per settlement batch, ordered by batch id.
    """
    # ---- validate inputs ---------------------------------------------------
    for col in ("settlement_batch_id", "amount", "fee_category"):
        if col not in ledger.columns:
            raise ValueError(f"Ledger is missing column: {col!r}")
    for col in ("settlement_batch_id", "payout_total"):
        if col not in settlements.columns:
            raise ValueError(f"Settlements is missing column: {col!r}")

    results: list[BatchResult] = []

    # De-duplicate settlement rows so we have one payout_total per batch
    settlement_map: dict[str, float] = (
        settlements.drop_duplicates(subset="settlement_batch_id")
        .set_index("settlement_batch_id")["payout_total"]
        .to_dict()
    )

    # ---- per-batch processing ----------------------------------------------
    for batch_id, group in ledger.groupby("settlement_batch_id"):
        batch_id_str = str(batch_id)
        ledger_total = round(float(group["amount"].sum()), 2)

        # Compute fees row-by-row
        total_fees = 0.0
        fee_breakdown: dict[str, float] = {}

        has_date = "date" in group.columns

        for _, row in group.iterrows():
            cat = row["fee_category"]
            amount = float(row["amount"])
            txn_date = row.get("date") if has_date else None

            ft, fv = _lookup_fee(fee_schedule, cat, txn_date)
            if ft is not None:
                fee = compute_fee(amount, ft, fv)
            else:
                fee = 0.0

            total_fees += fee
            fee_breakdown[cat] = round(fee_breakdown.get(cat, 0.0) + fee, 2)

        total_fees = round(total_fees, 2)
        expected_net = round(ledger_total - total_fees, 2)

        # Look up the actual payout
        payout_total = settlement_map.get(batch_id_str)
        if payout_total is None:
            # No settlement entry for this batch — treat as mismatch
            payout_total = 0.0

        payout_total = round(float(payout_total), 2)
        delta = round(expected_net - payout_total, 2)

        # Classify
        if delta == 0.0:
            status = MatchStatus.MATCHED
        elif abs(delta) <= tolerance:
            status = MatchStatus.TOLERANCE_MATCHED
        else:
            status = MatchStatus.MISMATCHED

        results.append(BatchResult(
            settlement_batch_id=batch_id_str,
            ledger_total=ledger_total,
            total_fees=total_fees,
            expected_net=expected_net,
            payout_total=payout_total,
            delta=delta,
            status=status,
            fee_breakdown=fee_breakdown,
        ))

    return sorted(results, key=lambda r: r.settlement_batch_id)


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def resolved(results: List[BatchResult]) -> List[BatchResult]:
    """Return only the resolved (matched or tolerance-matched) batches."""
    return [r for r in results if r.status in (
        MatchStatus.MATCHED, MatchStatus.TOLERANCE_MATCHED
    )]


def unresolved(results: List[BatchResult]) -> List[BatchResult]:
    """Return only the unresolved (mismatched) batches."""
    return [r for r in results if r.status == MatchStatus.MISMATCHED]


# ---------------------------------------------------------------------------
# Orphan settlement detection
# ---------------------------------------------------------------------------

@dataclass
class OrphanSettlement:
    """A settlement entry with no corresponding ledger batch."""
    settlement_batch_id: str
    payout_total: float
    extra_fields: dict = field(default_factory=dict)


def find_orphan_settlements(
    ledger: pd.DataFrame,
    settlements: pd.DataFrame,
) -> List[OrphanSettlement]:
    """Return settlement batches that have no matching ledger entries.

    These are settlements the bank paid out but the merchant has no
    record of in their ledger — they were previously silently skipped.
    """
    ledger_batch_ids = set(ledger["settlement_batch_id"].astype(str).unique())
    orphans: list[OrphanSettlement] = []

    for _, row in settlements.iterrows():
        bid = str(row["settlement_batch_id"])
        if bid not in ledger_batch_ids:
            extra = {
                k: row[k] for k in row.index
                if k not in ("settlement_batch_id", "payout_total")
                and pd.notna(row[k])
            }
            orphans.append(OrphanSettlement(
                settlement_batch_id=bid,
                payout_total=float(row["payout_total"]),
                extra_fields=extra,
            ))

    return orphans

