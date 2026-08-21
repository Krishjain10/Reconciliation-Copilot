"""
ingestion.loader — CSV file loading and validation

Handles loading settlement and ledger CSV files from file paths or
file-like objects (e.g. Streamlit uploaded files).  Validates that
required columns are present and coerces numeric types.
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
    """Read a CSV and validate that *required_columns* are present."""
    df = pd.read_csv(source)
    missing = set(required_columns) - set(df.columns)
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")
    return df


# ---------------------------------------------------------------------------
# Typed loaders
# ---------------------------------------------------------------------------

def load_ledger(source: Union[str, pathlib.Path, IO]) -> pd.DataFrame:
    """Load and validate a merchant ledger CSV."""
    df = load_csv(source, REQUIRED_LEDGER_COLS, "Ledger file")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    return df


def load_settlements(source: Union[str, pathlib.Path, IO]) -> pd.DataFrame:
    """Load and validate a bank settlement CSV."""
    df = load_csv(source, REQUIRED_SETTLEMENT_COLS, "Settlement file")
    df["payout_total"] = pd.to_numeric(df["payout_total"], errors="coerce")
    return df
