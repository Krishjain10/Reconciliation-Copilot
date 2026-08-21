"""
ingestion — Data Ingestion & Format Adapter Layer

Reads settlement files from bank/payment platforms and ledger files from
the merchant's accounting system. Converts various bank and file formats
(CSV, Excel, etc.) into a single, normalised internal representation so
that downstream components never need to know which bank or format the
data originally came from.

Key responsibilities:
    • Parse settlement files (dates, amounts, UTRs, batch payout totals).
    • Parse merchant ledger files (order IDs, amounts, expected fees).
    • Validate and clean raw data (missing fields, type coercion).
    • Emit a unified DataFrame/dict structure for the matching engine.
"""
