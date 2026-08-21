# 🏦 Reconciliation Copilot

AI-powered settlement reconciliation that detects, explains, and helps resolve mismatches between bank settlement payouts and merchant ledgers — in seconds instead of hours.

---

## The Problem

Payment processors settle thousands of transactions daily. Each settlement batch groups multiple orders, deducts fees, and issues a net payout. When the payout doesn't match the merchant's records, operations teams manually investigate — sifting through spreadsheets, cross-referencing fee schedules, and chasing down ₹50 discrepancies across ₹50 lakh batches.

**Reconciliation Copilot** automates this:
1. **Deterministic matching** — rule-based math that's auditable and exact
2. **AI-powered explanations** — a LangGraph agent that explains *why* each mismatch happened
3. **Zero PII exposure** — sensitive data (account numbers, names, IFSC codes) is HMAC-tokenized before reaching the LLM

---

## Architecture

```
┌────────────┐    ┌────────────────┐    ┌──────────────┐    ┌──────────────┐
│  Ingestion │───▶│  Batch Matcher │───▶│  Anonymizer  │───▶│  LangGraph   │
│  (CSV I/O) │    │  (Rule-based)  │    │  (HMAC-256)  │    │  Agent       │
└────────────┘    └────────────────┘    └──────────────┘    └──────────────┘
                         │                                         │
                         │ Resolved batches                        │ Explanation +
                         ▼                                         ▼ confidence
                  ┌──────────────────────────────────────────────────────┐
                  │              Streamlit Dashboard                     │
                  │  • Metric cards  • Resolved table  • Explanations   │
                  │  • Confidence scores  • Fee breakdown  • Audit log  │
                  └──────────────────────────────────────────────────────┘
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Matching is **deterministic** (no ML) | Financial math must be auditable and reproducible |
| AI explanations are **advisory only** | No ledger correction happens automatically from an AI output |
| PII is **tokenized before** reaching the agent | HMAC-SHA-256 with a per-session secret; the PII guard is a second regex layer that blocks raw account numbers and IFSC codes |
| LLM is **injectable** via `llm_callable` | Swap between the built-in rule-based engine and a real LLM with a single parameter |

---

## Project Structure

```
├── ingestion/
│   └── loader.py              # CSV loading, validation, NaN/empty-file guards
├── matching/
│   └── engine.py              # Batch grouping, fee calculation, delta classification
├── agent/
│   ├── anonymize.py           # HMAC-SHA-256 field tokenizer
│   ├── pii_guard.py           # Regex pre-send safety net
│   └── explain.py             # 3-node LangGraph agent
├── ui/
│   └── app.py                 # Streamlit dashboard + run_pipeline()
├── eval/
│   ├── golden_set.py          # 8-batch golden evaluation suite
│   └── edge_cases/            # 3 malformed CSVs for quarantine testing
├── tests/
│   ├── test_matching_engine.py    # 16 unit tests
│   ├── test_agent_explain.py      # 15 unit tests
│   └── test_integration.py        # 30 integration tests
└── data/
    ├── fee_schedule.csv
    ├── sample_ledger.csv
    └── sample_settlements.csv
```

---

## Setup

### Prerequisites

- Python 3.10+
- pip

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Clone & Navigate

```bash
git clone <repo-url>
cd Rzorpay_Hackathon
```

---

## Running the Demo

### 1. Launch the Dashboard

```bash
streamlit run ui/app.py
```

Open `http://localhost:8501` in your browser. Check **"Use sample data"** in the sidebar and click **🚀 Run Reconciliation**.

The dashboard shows:
- **Metric cards** — Total Batches, Matched, Tolerance-Matched, Mismatched
- **Resolved tab** — all reconciled batches with fee breakdowns
- **Unresolved tab** — AI-generated explanations with confidence scores
- **Audit Log tab** — every LLM prompt logged, PII guard verification

### 2. Run Tests

```bash
# Full test suite (61 tests)
python -m pytest tests/ -v

# Just the golden evaluation
python eval/golden_set.py
```

### 3. Custom Data

Upload your own CSVs via the sidebar. Required columns:

**Ledger CSV:** `order_id`, `settlement_batch_id`, `amount`, `fee_category`

**Settlement CSV:** `settlement_batch_id`, `payout_total`

**Fee Schedule CSV:** `fee_category`, `fee_type`, `fee_value`

---

## Evaluation Accuracy

All numbers below are from `python eval/golden_set.py` run against the 8-batch golden dataset and verified stable across two consecutive runs.

### Golden Evaluation — 17/17 (100%)

| Metric | Score |
|--------|-------|
| Classification Accuracy (matched / tolerance / mismatch) | 8/8 (100%) |
| Explanation Relevance (expected keywords found) | 4/4 (100%) |
| Confidence Calibration (score within expected range) | 4/4 (100%) |
| PII Safety (zero leaks across all LLM payloads) | PASS (8 payloads checked) |
| **Overall** | **17/17 (100%)** |

### Test Suite — 61/61 Passed

| Suite | Tests |
|-------|-------|
| `test_agent_explain.py` — PII guard, anonymizer, LangGraph agent | 15 |
| `test_matching_engine.py` — fee calculation, batch matching | 16 |
| `test_integration.py` — end-to-end pipeline, edge cases, PII paths | 30 |
| **Total** | **61** |

### Edge-Case Quarantine — 3/3

| Malformed File | Error Produced |
|----------------|----------------|
| Missing required columns | `"Ledger file is missing required columns: {'settlement_batch_id'}"` |
| Non-numeric amounts | `"Ledger file has 2 non-numeric amount value(s) in row(s) [0, 1]"` |
| Empty file | `"Ledger file is empty — no data or column headers were found"` |

---

## Known Limitations

1. **Advisory-only AI** — explanations describe likely causes; no automatic ledger corrections
2. **Rule-based demo LLM** — ships with a deterministic fallback; swap in a real LLM via `llm_callable`
3. **Single currency (INR)** — cross-currency settlements need a conversion layer
4. **Static fee schedule** — time-varying rates (mid-month changes) not yet supported
5. **PII guard scope** — covers account numbers (9–18 digits) and IFSC codes; other PII types (email, PAN) can be added
6. **Orphan settlements** — settlement entries with no matching ledger batch are silently skipped
7. **Single file pair** — each run processes one ledger + one settlement CSV

---

## License

Built for the Razorpay Hackathon.
