"""
ui.app — Reconciliation Copilot Dashboard (Streamlit)

Connects the full pipeline:
    ingestion → matching → anonymization → LangGraph agent

and presents results in a premium dark-themed dashboard with:
    • Summary metric cards
    • Resolved transactions table
    • Unresolved mismatches with AI explanations & confidence
    • Full audit log of every LLM prompt

Run with:
    streamlit run ui/app.py
"""

from __future__ import annotations

import pathlib
import re
import sys
from datetime import datetime
from typing import Callable, List

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Ensure project root is importable
# ---------------------------------------------------------------------------
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agent.anonymize import SENSITIVE_FIELDS, Anonymizer
from agent.explain import explain_mismatch
from agent.pii_guard import pii_guard
from matching.engine import (
    BatchResult,
    MatchStatus,
    OrphanSettlement,
    find_orphan_settlements,
    load_fee_schedule,
    match_batches,
    resolved,
    unresolved,
)
from ingestion.loader import load_ledger, load_settlements


# ═══════════════════════════════════════════════════════════════════════════
# FALLBACK LLM  (rule-based, no API key required for demo)
# ═══════════════════════════════════════════════════════════════════════════

def _create_fallback_llm() -> Callable[[str], str]:
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


# ═══════════════════════════════════════════════════════════════════════════
# PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

def run_pipeline(
    ledger_df: pd.DataFrame,
    settlement_df: pd.DataFrame,
    fee_schedule_df: pd.DataFrame,
    tolerance: float = 1.0,
    llm_callable: Callable[[str], str] | None = None,
) -> dict:
    """Run the full reconciliation pipeline end-to-end.

    Returns a dict with keys:
        all_results, resolved, tolerance_matched, unresolved,
        explanations, audit_log, orphan_settlements, anonymizer
    """
    llm = llm_callable or _create_fallback_llm()
    anonymizer = Anonymizer()

    # 1. Batch matching ─────────────────────────────────────────────────
    results = match_batches(ledger_df, settlement_df, fee_schedule_df, tolerance)
    resolved_list = resolved(results)
    unresolved_list = unresolved(results)

    # Separate tolerance-matched for display
    tolerance_list = [
        r for r in results if r.status == MatchStatus.TOLERANCE_MATCHED
    ]

    # 1b. Detect orphan settlements ────────────────────────────────────
    orphans = find_orphan_settlements(ledger_df, settlement_df)

    # 2. Build settlement info lookup (for PII fields) ─────────────────
    settlement_info: dict[str, dict] = {}
    sensitive_in_settlements = [
        c for c in settlement_df.columns if c in SENSITIVE_FIELDS
    ]
    for _, row in settlement_df.iterrows():
        bid = str(row["settlement_batch_id"])
        settlement_info[bid] = {
            c: str(row[c]) for c in sensitive_in_settlements if pd.notna(row[c])
        }

    # 3. Anonymize & explain unresolved ────────────────────────────────
    explanations: list[dict] = []
    audit_log: list[dict] = []

    for batch in unresolved_list:
        record: dict = {
            "settlement_batch_id": batch.settlement_batch_id,
            "ledger_total": batch.ledger_total,
            "total_fees": batch.total_fees,
            "expected_net": batch.expected_net,
            "payout_total": batch.payout_total,
            "delta": batch.delta,
            "fee_breakdown": batch.fee_breakdown,
        }
        # Merge sensitive settlement fields
        if batch.settlement_batch_id in settlement_info:
            record.update(settlement_info[batch.settlement_batch_id])

        # Anonymize
        safe_record = anonymizer.anonymize_record(record)

        # Explain via LangGraph agent
        result = explain_mismatch(safe_record, llm_callable=llm)

        explanations.append({
            "settlement_batch_id": batch.settlement_batch_id,
            "ledger_total": batch.ledger_total,
            "total_fees": batch.total_fees,
            "expected_net": batch.expected_net,
            "payout_total": batch.payout_total,
            "delta": batch.delta,
            "explanation": result["explanation"],
            "confidence": result["confidence"],
            "fee_breakdown": batch.fee_breakdown,
        })

        audit_log.append({
            "settlement_batch_id": batch.settlement_batch_id,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "pii_fields_anonymized": [
                k for k in record if k in SENSITIVE_FIELDS and record[k]
            ],
            "llm_payloads": result["llm_payloads"],
            "explanation": result["explanation"],
            "confidence": result["confidence"],
        })

    return {
        "all_results": results,
        "resolved": resolved_list,
        "tolerance_matched": tolerance_list,
        "unresolved": unresolved_list,
        "explanations": explanations,
        "audit_log": audit_log,
        "orphan_settlements": orphans,
        "anonymizer": anonymizer,
    }




# ═══════════════════════════════════════════════════════════════════════════
# STREAMLIT UI — Matches reference mockup
# ═══════════════════════════════════════════════════════════════════════════

def _inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap');

    /* ── Base ─────────────────────────────────────────────── */
    html, body, [class*="st-"] {
        font-family: 'Inter', sans-serif;
    }
    .stApp { background: #F5F4F0; }
    .block-container {
        max-width: 1060px;
        padding: 1.5rem 2rem 4rem;
    }
    p, span, label, div, li, td, th {
        color: #14181F !important;
    }

    /* ── Sidebar ──────────────────────────────────────────── */
    section[data-testid="stSidebar"] {
        background: #EDECEA;
        border-right: 1px solid #DDD9D1;
    }
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {
        font-family: 'Source Serif 4', 'Georgia', serif !important;
        color: #14181F !important;
    }
    /* Sidebar section labels */
    .sb-lbl {
        font-family: 'Inter', sans-serif;
        font-size: 0.62rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #6B6558 !important;
        margin: 16px 0 5px;
    }
    .sb-file {
        background: #FFFFFF;
        border: 1px solid #DDD9D1;
        border-radius: 4px;
        padding: 7px 10px;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.78rem;
        color: #14181F !important;
        margin-bottom: 2px;
    }

    /* ── Letterhead ───────────────────────────────────────── */
    .lh {
        padding: 20px 0 16px;
        margin-bottom: 20px;
    }
    .lh-title {
        font-family: 'Source Serif 4', 'Georgia', serif;
        font-size: 1.65rem;
        font-weight: 700;
        color: #14181F !important;
        letter-spacing: -0.01em;
        margin: 0;
        line-height: 1.2;
    }
    .lh-sub {
        font-family: 'Inter', sans-serif;
        font-size: 0.82rem;
        color: #6B6558 !important;
        margin-top: 3px;
    }

    /* ── Stats row — plain text, no borders ───────────────── */
    .stats {
        display: flex;
        gap: 0;
        margin-bottom: 20px;
        padding-bottom: 16px;
        border-bottom: 1px solid #E3E0D8;
    }
    .stats-cell {
        flex: 1;
    }
    .stats-label {
        font-family: 'Inter', sans-serif;
        font-size: 0.6rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #6B6558 !important;
        margin-bottom: 2px;
    }
    .stats-num {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 1.5rem;
        font-weight: 600;
        color: #14181F !important;
        line-height: 1.2;
    }

    /* ── Tabs ─────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        background: transparent;
        border-bottom: 1px solid #E3E0D8;
        padding: 0;
        border-radius: 0;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 0;
        padding: 8px 18px 10px;
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #6B6558 !important;
        border-bottom: 3px solid transparent;
    }
    .stTabs [aria-selected="true"] {
        background: transparent !important;
        color: #0E5C4A !important;
        border-bottom: 3px solid #0E5C4A !important;
        box-shadow: none;
    }

    /* ── Mismatch card ────────────────────────────────────── */
    .mx {
        background: #FFFFFF;
        border: 1px solid #E3E0D8;
        border-radius: 4px;
        padding: 24px 28px;
        margin-bottom: 16px;
    }

    /* Card top: batch ID + tags */
    .mx-head {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        margin-bottom: 20px;
        flex-wrap: wrap;
        gap: 8px;
    }
    .mx-bid {
        font-family: 'IBM Plex Mono', monospace;
        font-weight: 700;
        font-size: 1.05rem;
        color: #14181F !important;
    }
    .mx-tags { display: flex; gap: 8px; flex-wrap: wrap; align-items: baseline; }

    /* Tags — minimal, rectangular */
    .tag {
        font-family: 'Inter', sans-serif;
        font-size: 0.62rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        padding: 2px 8px;
        border-radius: 2px;
        white-space: nowrap;
    }
    .tag-delta  { color: #0E5C4A !important; background: #E8F3EE; }
    .tag-review { color: #6B6558 !important; background: #F0EFEC; border: 1px solid #E3E0D8; }
    .tag-conf   { color: #6B6558 !important; background: transparent; }

    /* Metrics row — plain text, 4 columns */
    .mx-metrics {
        display: grid;
        grid-template-columns: 1fr 1fr 1fr 1.2fr;
        gap: 0;
        margin-bottom: 20px;
    }
    .mx-m-lbl {
        font-family: 'Inter', sans-serif;
        font-size: 0.58rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #6B6558 !important;
        margin-bottom: 2px;
    }
    .mx-m-val {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.92rem;
        font-weight: 500;
        color: #14181F !important;
    }

    /* Inline confidence with bar */
    .conf-inline {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .conf-pct {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.92rem;
        font-weight: 500;
        color: #14181F !important;
        white-space: nowrap;
    }
    .conf-track {
        flex: 1;
        background: #E3E0D8;
        border-radius: 2px;
        height: 5px;
        overflow: hidden;
        min-width: 60px;
    }
    .conf-fill {
        height: 100%;
        border-radius: 2px;
    }

    /* Explanation block */
    .mx-expl {
        background: #F7FAF8;
        border-left: 4px solid #0E5C4A;
        border-radius: 0 4px 4px 0;
        padding: 14px 18px;
        font-family: 'Inter', sans-serif;
        font-size: 0.82rem;
        line-height: 1.6;
        color: #2A2A2A !important;
    }

    /* Fee sub-table */
    .mx-fees {
        margin-top: 14px;
        padding-top: 10px;
        border-top: 1px solid #E3E0D8;
    }
    .mx-fees-lbl {
        font-family: 'Inter', sans-serif;
        font-size: 0.58rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: #6B6558 !important;
        margin-bottom: 4px;
    }

    /* ── Resolved / Ledger table ──────────────────────────── */
    .ltbl {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.82rem;
    }
    .ltbl thead th {
        text-align: left;
        padding: 8px 12px;
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        font-size: 0.62rem;
        color: #6B6558 !important;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        border-bottom: 2px solid #C8C4BA;
    }
    .ltbl thead th.r { text-align: right; }
    .ltbl tbody td {
        padding: 9px 12px;
        color: #14181F !important;
        border-bottom: 1px solid #E3E0D8;
        font-family: 'Inter', sans-serif;
    }
    .ltbl tbody tr:last-child td { border-bottom: none; }
    .ltbl tbody td.m {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.8rem;
        text-align: right;
        font-weight: 500;
    }
    .ltbl tbody td.ml {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.8rem;
        font-weight: 500;
    }

    /* ── Status pills (for resolved table) ────────────────── */
    .st-pill {
        display: inline-block;
        padding: 2px 7px;
        border-radius: 2px;
        font-family: 'Inter', sans-serif;
        font-size: 0.6rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .st-pill-green { background: #E4F2E8; color: #1B7A43 !important; }
    .st-pill-amber { background: #FDF2E0; color: #B5650D !important; }
    .st-pill-red   { background: #FBEAE9; color: #B3261E !important; }

    /* ── Section labels ───────────────────────────────────── */
    .sec-lbl {
        font-family: 'Inter', sans-serif;
        font-size: 0.6rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: #6B6558 !important;
        margin-bottom: 6px;
    }
    .sec-title {
        font-family: 'Source Serif 4', serif;
        font-size: 1.05rem;
        font-weight: 600;
        color: #14181F !important;
        margin-bottom: 2px;
    }
    .sec-desc {
        font-family: 'Inter', sans-serif;
        font-size: 0.76rem;
        color: #6B6558 !important;
        margin-bottom: 14px;
    }

    /* ── Empty state ──────────────────────────────────────── */
    .empty {
        text-align: center;
        padding: 50px 24px;
        background: #FFFFFF;
        border: 1px solid #E3E0D8;
        border-radius: 4px;
    }
    .empty-title {
        font-family: 'Source Serif 4', serif;
        font-size: 1.1rem;
        font-weight: 600;
        color: #14181F !important;
        margin-bottom: 6px;
    }
    .empty-desc {
        font-family: 'Inter', sans-serif;
        font-size: 0.82rem;
        color: #6B6558 !important;
        max-width: 420px;
        margin: 0 auto;
        line-height: 1.5;
    }

    /* ── How-it-works strip ───────────────────────────────── */
    .hiw {
        display: flex;
        gap: 1px;
        background: #E3E0D8;
        border: 1px solid #E3E0D8;
        border-radius: 4px;
        overflow: hidden;
        margin-top: 14px;
    }
    .hiw-s {
        flex: 1;
        background: #FFFFFF;
        padding: 12px 14px;
        text-align: center;
    }
    .hiw-n {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.6rem;
        font-weight: 600;
        color: #6B6558 !important;
        margin-bottom: 1px;
    }
    .hiw-l {
        font-family: 'Inter', sans-serif;
        font-size: 0.72rem;
        font-weight: 600;
        color: #14181F !important;
    }

    /* ── Buttons ──────────────────────────────────────────── */
    .stButton > button {
        background: #0E5C4A;
        color: #FFFFFF !important;
        border: none;
        border-radius: 4px;
        padding: 0.6rem 1.4rem;
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        font-size: 0.85rem;
        transition: background 0.15s;
        width: 100%;
    }
    .stButton > button:hover { background: #0A4A3B; }

    /* ── Expanders ────────────────────────────────────────── */
    details[data-testid="stExpander"] {
        background: #FAFAF8;
        border: 1px solid #E3E0D8;
        border-radius: 4px;
        margin-bottom: 8px;
    }

    /* ── Inputs ───────────────────────────────────────────── */
    .stTextInput > div > div > input {
        background: #FFFFFF;
        border: 1px solid #DDD9D1;
        border-radius: 4px;
        padding: 7px 12px;
        font-family: 'Inter', sans-serif;
        font-size: 0.82rem;
        color: #14181F;
    }
    .stTextInput > div > div > input:focus {
        border-color: #0E5C4A;
        box-shadow: 0 0 0 2px rgba(14,92,74,0.1);
    }
    [data-testid="stFileUploader"] {
        background: #FFFFFF;
        border-radius: 4px;
        border: 1px dashed #C8C4BA;
        padding: 8px;
    }
    .stCheckbox label span { color: #14181F !important; }
    .stSlider [data-baseweb="slider"] [role="slider"] { background: #0E5C4A; }

    /* ── Misc ─────────────────────────────────────────────── */
    hr { border: none; border-top: 1px solid #E3E0D8; margin: 0.8rem 0; }
    .stDataFrame { border-radius: 4px; overflow: hidden; }

    /* ── Hide Streamlit chrome (Deploy, Options, header bar, footer) ── */
    #MainMenu { visibility: hidden; }
    header[data-testid="stHeader"] { display: none !important; }
    footer { visibility: hidden; }
    .stDeployButton { display: none !important; }
    .stAppDeployButton { display: none !important; }

    /* ── Remove the colored top bar ──────────────────────── */
    .stApp > header { display: none !important; }
    div[data-testid="stDecoration"] { display: none !important; }
    div[data-testid="stStatusWidget"] { display: none !important; }

    /* ── Sidebar alignment — flush top-left ──────────────── */
    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 1.5rem;
        padding-left: 1.2rem;
        padding-right: 1.2rem;
    }
    section[data-testid="stSidebar"] .block-container {
        padding: 0;
    }
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        padding-top: 1.5rem;
        padding-left: 1.2rem;
        padding-right: 1.2rem;
    }
    /* Remove default top gap in main content area */
    .stApp .main .block-container {
        padding-top: 1.5rem;
    }
    </style>
    """, unsafe_allow_html=True)


# ───────────────────────────────────────────────────────────────────────────

def _render_header():
    st.markdown(
        '<div class="lh">'
        '<p class="lh-title">Reconciliation Copilot</p>'
        '<p class="lh-sub">'
        'Settlement reconciliation — match batches, explain mismatches, '
        'verify PII safety'
        '</p>'
        '</div>',
        unsafe_allow_html=True,
    )


def _conf_color(c: float) -> str:
    if c >= 0.80: return "#1B7A43"
    if c >= 0.60: return "#B5650D"
    return "#B3261E"


def _render_stat_cards(res: dict):
    total = len(res["all_results"])
    ok = len([r for r in res["all_results"]
              if r.status in (MatchStatus.MATCHED, MatchStatus.TOLERANCE_MATCHED)])
    bad = len(res["unresolved"])
    pct = f"{100*ok//total}%" if total else "—"

    st.markdown(f'''
    <div class="stats">
        <div class="stats-cell">
            <div class="stats-label">Total Batches</div>
            <div class="stats-num">{total}</div>
        </div>
        <div class="stats-cell">
            <div class="stats-label">Resolved</div>
            <div class="stats-num">{ok}</div>
        </div>
        <div class="stats-cell">
            <div class="stats-label">Unresolved</div>
            <div class="stats-num">{bad}</div>
        </div>
        <div class="stats-cell">
            <div class="stats-label">Match Rate</div>
            <div class="stats-num">{pct}</div>
        </div>
    </div>
    ''', unsafe_allow_html=True)


def _render_resolved_section(res: dict):
    matched = [r for r in res["all_results"]
               if r.status in (MatchStatus.MATCHED, MatchStatus.TOLERANCE_MATCHED)]

    if not matched:
        st.markdown(
            '<div class="empty">'
            '<div class="empty-title">No resolved batches</div>'
            '<div class="empty-desc">All batches exceeded the tolerance '
            'threshold.</div></div>',
            unsafe_allow_html=True)
        return

    rows = ""
    for r in matched:
        pill = ('<span class="st-pill st-pill-green">Matched</span>'
                if r.status == MatchStatus.MATCHED
                else '<span class="st-pill st-pill-amber">Tolerance</span>')
        rows += (
            f'<tr>'
            f'<td class="ml">{r.settlement_batch_id}</td>'
            f'<td>{pill}</td>'
            f'<td class="m">₹{r.ledger_total:,.2f}</td>'
            f'<td class="m">₹{r.total_fees:,.2f}</td>'
            f'<td class="m">₹{r.expected_net:,.2f}</td>'
            f'<td class="m">₹{r.payout_total:,.2f}</td>'
            f'<td class="m">₹{r.delta:,.2f}</td>'
            f'</tr>'
        )

    st.markdown(f'''
    <div style="background:#FFF;border:1px solid #E3E0D8;border-radius:4px;overflow:hidden;">
        <table class="ltbl">
            <thead><tr>
                <th>Batch</th><th>Status</th>
                <th class="r">Ledger</th><th class="r">Fees</th>
                <th class="r">Expected</th><th class="r">Payout</th>
                <th class="r">Delta</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    ''', unsafe_allow_html=True)


def _render_unresolved_section(res: dict):
    explanations = res["explanations"]
    audit_log = res["audit_log"]

    if not explanations:
        st.markdown(
            '<div class="empty">'
            '<div class="empty-title">All batches reconciled</div>'
            '<div class="empty-desc">No mismatches found.</div></div>',
            unsafe_allow_html=True)
        return

    search = st.text_input(
        "Filter by Batch ID",
        placeholder="e.g. BATCH_004",
        key="batch_filter",
    )
    items = explanations
    if search:
        items = [e for e in explanations
                 if search.upper() in e["settlement_batch_id"].upper()]
    if not items:
        st.caption("No batches match your filter.")
        return

    audit_by_id = {a["settlement_batch_id"]: a for a in audit_log}

    for item in items:
        d = item["delta"]
        d_abs = f"₹{abs(d):,.2f}"
        direction = "UNDER" if d > 0 else "OVER"
        conf = item["confidence"]
        c_pct_num = f"{conf:.0%}"
        c_color = _conf_color(conf)

        # Build fee breakdown HTML if present
        fee_html = ""
        if item.get("fee_breakdown"):
            fee_rows = "".join(
                f'<tr><td>{cat}</td><td class="m">₹{amt:,.2f}</td></tr>'
                for cat, amt in item["fee_breakdown"].items()
            )
            fee_html = (
                f'<div class="mx-fees">'
                f'<div class="mx-fees-lbl">Fee Breakdown</div>'
                f'<table class="ltbl" style="max-width:300px;">'
                f'<thead><tr><th>Category</th><th class="r">Amount</th></tr></thead>'
                f'<tbody>{fee_rows}</tbody>'
                f'</table></div>'
            )

        # Render entire card in one st.markdown call (no blank lines — Streamlit treats them as paragraph breaks)
        card_html = (
            f'<div class="mx">'
            f'<div class="mx-head">'
            f'<span class="mx-bid">{item["settlement_batch_id"]}</span>'
            f'<div class="mx-tags">'
            f'<span class="tag tag-delta">Δ {d_abs} {direction}</span>'
            f'<span class="tag tag-review">NEEDS REVIEW</span>'
            f'<span class="tag tag-conf">{c_pct_num} CONF.</span>'
            f'</div></div>'
            f'<div class="mx-metrics">'
            f'<div><div class="mx-m-lbl">Expected</div>'
            f'<div class="mx-m-val">₹{item["expected_net"]:,.2f}</div></div>'
            f'<div><div class="mx-m-lbl">Payout</div>'
            f'<div class="mx-m-val">₹{item["payout_total"]:,.2f}</div></div>'
            f'<div><div class="mx-m-lbl">Delta</div>'
            f'<div class="mx-m-val">₹{d:,.2f}</div></div>'
            f'<div><div class="mx-m-lbl">Confidence</div>'
            f'<div class="conf-inline">'
            f'<span class="conf-pct">{c_pct_num}</span>'
            f'<div class="conf-track">'
            f'<div class="conf-fill" style="width:{conf*100:.0f}%;background:{c_color};"></div>'
            f'</div></div></div>'
            f'</div>'
            f'<div class="mx-expl">{item["explanation"]}</div>'
            f'{fee_html}'
            f'</div>'
        )
        st.markdown(card_html, unsafe_allow_html=True)



        # Audit evidence expander
        ae = audit_by_id.get(item["settlement_batch_id"])
        if ae:
            with st.expander(
                f"AUDIT EVIDENCE — {item['settlement_batch_id']}"
            ):
                if ae["pii_fields_anonymized"]:
                    pills = "  ".join(
                        f'<span class="st-pill" style="background:#F0EFEC;color:#6B6558 !important;">{f}</span>'
                        for f in ae["pii_fields_anonymized"]
                    )
                    st.markdown(
                        f"**Anonymized PII Fields** &nbsp; {pills}",
                        unsafe_allow_html=True)
                else:
                    st.caption("No PII fields detected.")

                st.markdown("---")
                st.markdown(f"**Timestamp:** `{ae['timestamp']}`")
                st.markdown(f"**Confidence:** `{ae['confidence']}`")
                st.markdown("---")
                st.markdown(
                    f"**LLM Prompts** ({len(ae['llm_payloads'])} total)")
                for i, payload in enumerate(ae["llm_payloads"]):
                    lbl = "Explanation Prompt" if i == 0 else "Confidence Prompt"
                    st.markdown(f"*{lbl}:*")
                    st.code(payload, language="text")

                clean = True
                for payload in ae["llm_payloads"]:
                    try:
                        pii_guard(payload)
                    except Exception:
                        clean = False
                        break
                if clean:
                    st.success("PII guard verified — no sensitive data in any payload")
                else:
                    st.error("PII leak detected")


def _render_audit_section(res: dict):
    audit = res["audit_log"]

    if not audit:
        st.markdown(
            '<div class="empty">'
            '<div class="empty-title">No audit entries</div>'
            '<div class="empty-desc">No mismatches were processed.</div></div>',
            unsafe_allow_html=True)
        return

    for entry in audit:
        with st.expander(
            f"**{entry['settlement_batch_id']}** — {entry['timestamp']}"
        ):
            if entry["pii_fields_anonymized"]:
                pills = "  ".join(
                    f'<span class="st-pill" style="background:#F0EFEC;color:#6B6558 !important;">{f}</span>'
                    for f in entry["pii_fields_anonymized"]
                )
                st.markdown(
                    f"**Anonymized PII Fields** &nbsp; {pills}",
                    unsafe_allow_html=True)
            else:
                st.caption("No PII fields detected.")

            st.markdown("---")
            st.markdown(f"**Confidence:** `{entry['confidence']}`")
            st.markdown("**Explanation:**")
            st.markdown(f"> {entry['explanation']}")
            st.markdown("---")
            st.markdown(
                f"**LLM Prompts** ({len(entry['llm_payloads'])} total)")
            for i, payload in enumerate(entry["llm_payloads"]):
                label = "Explanation Prompt" if i == 0 else "Confidence Prompt"
                st.markdown(f"*{label}:*")
                st.code(payload, language="text")

            clean = True
            for payload in entry["llm_payloads"]:
                try:
                    pii_guard(payload)
                except Exception:
                    clean = False
                    break
            if clean:
                st.success("PII guard verified — no sensitive data in any payload")
            else:
                st.error("PII leak detected")


# ═══════════════════════════════════════════════════════════════════════════
# SIDEBAR — matches reference mockup with labeled file sections
# ═══════════════════════════════════════════════════════════════════════════

def _render_sidebar() -> dict | None:
    with st.sidebar:
        st.markdown("## Configuration")

        use_sample = st.checkbox("Use sample data", value=True)

        ledger_source = None
        settlement_source = None
        fee_source = None

        if use_sample:
            data_dir = _PROJECT_ROOT / "data"
            ledger_source = data_dir / "sample_ledger.csv"
            settlement_source = data_dir / "sample_settlements.csv"
            fee_source = data_dir / "fee_schedule.csv"

            st.markdown('<div class="sb-lbl">Ledger File</div>', unsafe_allow_html=True)
            st.markdown('<div class="sb-file">sample_ledger.csv</div>', unsafe_allow_html=True)
            st.markdown('<div class="sb-lbl">Settlements File</div>', unsafe_allow_html=True)
            st.markdown('<div class="sb-file">sample_settlements.csv</div>', unsafe_allow_html=True)
            st.markdown('<div class="sb-lbl">Fee Schedule</div>', unsafe_allow_html=True)
            st.markdown('<div class="sb-file">fee_schedule.csv</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="sb-lbl">Ledger Files</div>', unsafe_allow_html=True)
            ledger_files = st.file_uploader(
                "Upload Ledger CSV(s)", type=["csv"], key="ledger",
                accept_multiple_files=True,
                label_visibility="collapsed")
            st.markdown('<div class="sb-lbl">Settlement Files</div>', unsafe_allow_html=True)
            settlement_files = st.file_uploader(
                "Upload Settlement CSV(s)", type=["csv"], key="settlement",
                accept_multiple_files=True,
                label_visibility="collapsed")
            st.markdown('<div class="sb-lbl">Fee Schedule</div>', unsafe_allow_html=True)
            fee_file = st.file_uploader(
                "Upload Fee Schedule CSV (optional)",
                type=["csv"], key="fee_schedule",
                label_visibility="collapsed")
            if ledger_files:
                ledger_source = ledger_files  # list of UploadedFile
            if settlement_files:
                settlement_source = settlement_files
            if fee_file:
                fee_source = fee_file
            else:
                fee_source = _PROJECT_ROOT / "data" / "fee_schedule.csv"

        st.markdown("---")

        tolerance = st.slider(
            "Match Tolerance  ₹",
            min_value=0.0, max_value=50.0, value=1.0, step=0.5,
            help="Maximum absolute delta to still consider a match.",
        )

        st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
        run = st.button("Run Reconciliation", use_container_width=True)

        if run and ledger_source and settlement_source and fee_source:
            return {
                "ledger_source": ledger_source,
                "settlement_source": settlement_source,
                "fee_source": fee_source,
                "tolerance": tolerance,
            }
        elif run:
            st.error("Please upload both Ledger and Settlement CSV files.")

    return None


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def _render_orphan_section(res: dict):
    """Render the orphan settlements tab."""
    orphans = res.get("orphan_settlements", [])

    if not orphans:
        st.markdown(
            '<div class="empty">'
            '<div class="empty-title">No orphan settlements</div>'
            '<div class="empty-desc">Every settlement batch has a matching '
            'ledger entry.</div></div>',
            unsafe_allow_html=True)
        return

    st.markdown(
        '<div class="sec-lbl">⚠ ORPHAN SETTLEMENTS</div>'
        '<div class="sec-desc">These settlement entries have no matching '
        'ledger batch — the bank paid out but no corresponding merchant '
        'record was found.</div>',
        unsafe_allow_html=True)

    rows = ""
    for o in orphans:
        extra_cols = ""
        for k, v in o.extra_fields.items():
            extra_cols += f'<td class="ml">{v}</td>'
        rows += (
            f'<tr>'
            f'<td class="ml">{o.settlement_batch_id}</td>'
            f'<td class="m">₹{o.payout_total:,.2f}</td>'
            f'<td><span class="st-pill st-pill-red">ORPHAN</span></td>'
            f'{extra_cols}'
            f'</tr>'
        )

    # Build extra headers from first orphan's extra_fields
    extra_headers = ""
    if orphans:
        for k in orphans[0].extra_fields:
            extra_headers += f'<th>{k}</th>'

    st.markdown(f'''
    <div style="background:#FFF;border:1px solid #E3E0D8;border-radius:4px;overflow:hidden;">
        <table class="ltbl">
            <thead><tr>
                <th>Batch</th><th class="r">Payout</th>
                <th>Status</th>{extra_headers}
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    ''', unsafe_allow_html=True)


def _render_detoken_section(res: dict):
    """Render de-tokenization controls in the audit log."""
    anonymizer = res.get("anonymizer")
    if not anonymizer or not anonymizer._lookup:
        return

    st.markdown("---")
    st.markdown(
        '<div class="sec-lbl">🔓 DE-TOKENIZATION (Authorized Users Only)</div>',
        unsafe_allow_html=True)

    passphrase = st.text_input(
        "Enter audit passphrase to reveal original values",
        type="password",
        key="detoken_pass",
    )

    # Simple passphrase check — in production this would be a proper auth flow
    if passphrase == "recon-audit-2024":
        st.success("✓ Authorized — showing de-tokenized values")
        token_map = anonymizer._lookup
        rows = ""
        for token, original in token_map.items():
            rows += f'<tr><td class="ml">{token}</td><td class="ml">{original}</td></tr>'
        st.markdown(f'''
        <div style="background:#FFF;border:1px solid #E3E0D8;border-radius:4px;
                    overflow:hidden;max-width:600px;">
            <table class="ltbl">
                <thead><tr>
                    <th>Token</th><th>Original Value</th>
                </tr></thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
        ''', unsafe_allow_html=True)
    elif passphrase:
        st.error("Incorrect passphrase.")


def main():
    st.set_page_config(
        page_title="Reconciliation Copilot",
        page_icon="🏦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_css()
    _render_header()

    config = _render_sidebar()

    if "pipeline_result" not in st.session_state:
        st.session_state["pipeline_result"] = None

    if config is not None:
        with st.spinner("Running reconciliation…"):
            try:
                src = config["ledger_source"]
                # Multi-file support: concatenate if list
                if isinstance(src, list):
                    ledger_df = pd.concat(
                        [load_ledger(f) for f in src], ignore_index=True)
                else:
                    ledger_df = load_ledger(src)

                src = config["settlement_source"]
                if isinstance(src, list):
                    settlement_df = pd.concat(
                        [load_settlements(f) for f in src], ignore_index=True)
                else:
                    settlement_df = load_settlements(src)

                fee_schedule_df = load_fee_schedule(config["fee_source"])
                result = run_pipeline(
                    ledger_df, settlement_df, fee_schedule_df,
                    tolerance=config["tolerance"],
                )
                st.session_state["pipeline_result"] = result
            except Exception as exc:
                st.error(f"Pipeline error: {exc}")
                st.session_state["pipeline_result"] = None

    result = st.session_state["pipeline_result"]

    if result is None:
        st.markdown(
            '<div class="empty">'
            '<div class="empty-title">Ready to reconcile</div>'
            '<div class="empty-desc">'
            'Select <strong>Use sample data</strong> in the sidebar or upload '
            'your own files, then click <strong>Run Reconciliation</strong>.'
            '</div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="hiw">'
            '<div class="hiw-s"><div class="hiw-n">01</div><div class="hiw-l">Upload</div></div>'
            '<div class="hiw-s"><div class="hiw-n">02</div><div class="hiw-l">Match</div></div>'
            '<div class="hiw-s"><div class="hiw-n">03</div><div class="hiw-l">Explain</div></div>'
            '<div class="hiw-s"><div class="hiw-n">04</div><div class="hiw-l">Audit</div></div>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    _render_stat_cards(result)

    # Determine tab count based on orphans
    orphans = result.get("orphan_settlements", [])
    if orphans:
        tab1, tab2, tab3, tab4 = st.tabs(
            ["RESOLVED", "UNRESOLVED", f"ORPHANS ({len(orphans)})", "AUDIT LOG"])
    else:
        tab1, tab2, tab3, tab4 = st.tabs(
            ["RESOLVED", "UNRESOLVED", "ORPHANS", "AUDIT LOG"])

    with tab1:
        _render_resolved_section(result)
    with tab2:
        _render_unresolved_section(result)
    with tab3:
        _render_orphan_section(result)
    with tab4:
        _render_audit_section(result)
        _render_detoken_section(result)


if __name__ == "__main__":
    main()
