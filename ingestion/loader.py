"""
ingestion.loader — CSV file loading and validation

Handles loading settlement and ledger CSV files from file paths or
file-like objects (e.g. Streamlit uploaded files).  Validates that
required columns are present, numeric fields are valid, and the file
is not empty.  Every failure produces a clear, descriptive error
message suitable for display in the UI.
"""

from __future__ import annotations

import pathlib
from typing import IO, List, Union

import pandas as pd


# ---------------------------------------------------------------------------
# Required column sets
# ---------------------------------------------------------------------------

REQUIRED_LEDGER_COLS: List[str] = [
    "order_id",
    "settlement_batch_id",
    "amount",
    "fee_category",
]

REQUIRED_SETTLEMENT_COLS: List[str] = [
    "settlement_batch_id",
    "payout_total",
]


# ---------------------------------------------------------------------------
# Generic loader
# ---------------------------------------------------------------------------

def load_csv(
    source: Union[str, pathlib.Path, IO],
    required_columns: List[str],
    label: str = "file",
) -> pd.DataFrame:
    """Read a CSV and validate that *required_columns* are present.

    Raises :class:`ValueError` with a descriptive message on:
        • empty / unreadable files
        • header-only files (no data rows)
        • missing required columns
    """
    # --- file-type guard ------------------------------------------------
    if isinstance(source, (str, pathlib.Path)):
        ext = pathlib.Path(source).suffix.lower()
        if ext and ext != ".csv":
            raise ValueError(
                f"{label} has an unsupported file type ({ext}). "
                f"Please upload a CSV file."
            )

    try:
        df = pd.read_csv(source)
    except pd.errors.EmptyDataError:
        raise ValueError(
            f"{label} is empty — no data or column headers were found. "
            f"Please upload a valid CSV."
        )
    except Exception as exc:
        raise ValueError(f"{label} could not be read: {exc}")

    if df.empty:
        raise ValueError(
            f"{label} contains column headers but no data rows. "
            f"Please check the file contents."
        )

    missing = set(required_columns) - set(df.columns)
    if missing:
        raise ValueError(
            f"{label} is missing required columns: {missing}. "
            f"Expected columns include: {required_columns}."
        )
    return df


# ---------------------------------------------------------------------------
# Typed loaders
# ---------------------------------------------------------------------------

def load_ledger(source: Union[str, pathlib.Path, IO]) -> pd.DataFrame:
    """Load and validate a merchant ledger CSV.

    Raises :class:`ValueError` if any ``amount`` value is non-numeric.
    """
    df = load_csv(source, REQUIRED_LEDGER_COLS, "Ledger file")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")

    nan_mask = df["amount"].isna()
    if nan_mask.any():
        bad_rows = df.index[nan_mask].tolist()
        raise ValueError(
            f"Ledger file has {nan_mask.sum()} non-numeric amount value(s) "
            f"in row(s) {bad_rows}. Every amount must be a valid number. "
            f"If your amounts contain currency symbols (₹, $) or commas, "
            f"please remove them before uploading."
        )
    return df


def load_settlements(source: Union[str, pathlib.Path, IO]) -> pd.DataFrame:
    """Load and validate a bank settlement CSV.

    Raises :class:`ValueError` if any ``payout_total`` value is non-numeric.
    """
    df = load_csv(source, REQUIRED_SETTLEMENT_COLS, "Settlement file")
    df["payout_total"] = pd.to_numeric(df["payout_total"], errors="coerce")

    nan_mask = df["payout_total"].isna()
    if nan_mask.any():
        bad_rows = df.index[nan_mask].tolist()
        raise ValueError(
            f"Settlement file has {nan_mask.sum()} non-numeric payout_total "
            f"value(s) in row(s) {bad_rows}. Every payout must be a valid number. "
            f"If your values contain currency symbols (₹, $) or commas, "
            f"please remove them before uploading."
        )
    return df
