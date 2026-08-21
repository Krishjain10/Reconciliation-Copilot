"""
matching — Batch Matching & Deterministic Resolution Engine

Groups individual ledger entries against bulk settlement payouts and
checks whether the totals line up (exact match or within a configurable
tolerance). Mismatches that survive this deterministic check are the only
ones forwarded to the AI explanation layer.

Key responsibilities:
    • Group ledger rows by settlement batch / UTR.
    • Sum and compare amounts, applying fee-schedule adjustments.
    • Mark matched batches as resolved (no AI needed).
    • Emit unresolved mismatch records with structured evidence
      (expected vs. actual, delta, possible fee discrepancy, etc.).
"""
