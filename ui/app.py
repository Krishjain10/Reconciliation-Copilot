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
        explanations, audit_log
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
    }


# ═══════════════════════════════════════════════════════════════════════════
# STREAMLIT UI
# ═══════════════════════════════════════════════════════════════════════════

def _inject_css():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* ── Base ────────────────────────────────────────────────────── */
    html, body, [class*="st-"] { font-family: 'Inter', sans-serif; }
    .stApp {
        background: linear-gradient(145deg, #0a0a1a 0%, #1a1a2e 50%, #16213e 100%);
    }

    /* ── Sidebar ─────────────────────────────────────────────────── */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0e0e20 0%, #141428 100%);
        border-right: 1px solid rgba(99,102,241,0.15);
    }
    section[data-testid="stSidebar"] .stMarkdown h1,
    section[data-testid="stSidebar"] .stMarkdown h2,
    section[data-testid="stSidebar"] .stMarkdown h3 {
        color: #a5b4fc;
    }

    /* ── Header ──────────────────────────────────────────────────── */
    .hero-title {
        font-size: 2.6rem;
        font-weight: 800;
        background: linear-gradient(135deg, #a5b4fc, #818cf8, #c084fc);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -0.03em;
        margin-bottom: 0;
        line-height: 1.15;
    }
    .hero-sub {
        font-size: 1.05rem;
        color: #94a3b8;
        margin-top: 4px;
        font-weight: 400;
    }

    /* ── Metric cards ────────────────────────────────────────────── */
    div[data-testid="stMetric"] {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 14px;
        padding: 18px 20px;
        transition: transform 0.2s, border-color 0.2s;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        border-color: rgba(99,102,241,0.35);
    }
    div[data-testid="stMetric"] label {
        color: #94a3b8 !important;
        font-weight: 500;
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-weight: 700;
        font-size: 1.8rem;
    }

    /* ── Tabs ────────────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        background: rgba(255,255,255,0.03);
        border-radius: 12px;
        padding: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 10px;
        padding: 10px 20px;
        font-weight: 600;
        font-size: 0.88rem;
        color: #94a3b8;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, rgba(99,102,241,0.25), rgba(139,92,246,0.18)) !important;
        color: #e0e7ff !important;
    }

    /* ── Buttons ─────────────────────────────────────────────────── */
    .stButton > button {
        background: linear-gradient(135deg, #6366f1, #8b5cf6);
        color: #fff;
        border: none;
        border-radius: 10px;
        padding: 0.6rem 1.6rem;
        font-weight: 600;
        font-size: 0.92rem;
        transition: transform 0.15s, box-shadow 0.15s;
        width: 100%;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 24px rgba(99,102,241,0.35);
    }

    /* ── Expanders ───────────────────────────────────────────────── */
    details[data-testid="stExpander"] {
        background: rgba(255,255,255,0.03);
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 12px;
        margin-bottom: 10px;
    }

    /* ── Dataframe ───────────────────────────────────────────────── */
    .stDataFrame { border-radius: 12px; overflow: hidden; }

    /* ── Status badges ───────────────────────────────────────────── */
    .badge {
        display: inline-block;
        padding: 4px 14px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
        letter-spacing: 0.03em;
    }
    .badge-matched   { background: rgba(16,185,129,0.18); color: #34d399; }
    .badge-tolerance { background: rgba(245,158,11,0.18); color: #fbbf24; }
    .badge-mismatch  { background: rgba(239,68,68,0.18);  color: #f87171; }

    /* ── Dividers ────────────────────────────────────────────────── */
    hr {
        border: none;
        border-top: 1px solid rgba(255,255,255,0.06);
        margin: 1.2rem 0;
    }

    /* ── Confidence bar ──────────────────────────────────────────── */
    .conf-bar-bg {
        background: rgba(255,255,255,0.08);
        border-radius: 6px;
        height: 8px;
        width: 100%;
        overflow: hidden;
    }
    .conf-bar-fill {
        height: 100%;
        border-radius: 6px;
        transition: width 0.4s ease;
    }
    </style>
    """, unsafe_allow_html=True)


def _render_header():
    st.markdown(
        '<p class="hero-title">🏦 Reconciliation Copilot</p>'
        '<p class="hero-sub">'
        'AI-powered settlement reconciliation — detect, explain, and resolve '
        'mismatches in seconds'
        '</p>',
        unsafe_allow_html=True,
    )
    st.markdown("---")


def _confidence_color(conf: float) -> str:
    if conf >= 0.80:
        return "#10b981"
    if conf >= 0.60:
        return "#f59e0b"
    return "#ef4444"


def _render_metrics(pipeline_result: dict):
    total = len(pipeline_result["all_results"])
    matched = len([
        r for r in pipeline_result["all_results"]
        if r.status == MatchStatus.MATCHED
    ])
    tol = len(pipeline_result["tolerance_matched"])
    mis = len(pipeline_result["unresolved"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Batches", total)
    c2.metric("✅ Matched", matched)
    c3.metric("🟡 Tolerance", tol)
    c4.metric("🔴 Mismatched", mis)


def _render_resolved_tab(pipeline_result: dict):
    matched = [
        r for r in pipeline_result["all_results"]
        if r.status in (MatchStatus.MATCHED, MatchStatus.TOLERANCE_MATCHED)
    ]
    if not matched:
        st.info("No resolved batches.")
        return

    rows = []
    for r in matched:
        status_label = (
            "✅ Exact Match" if r.status == MatchStatus.MATCHED
            else "🟡 Tolerance Match"
        )
        rows.append({
            "Batch ID": r.settlement_batch_id,
            "Status": status_label,
            "Ledger Total (₹)": f"{r.ledger_total:,.2f}",
            "Fees (₹)": f"{r.total_fees:,.2f}",
            "Expected Net (₹)": f"{r.expected_net:,.2f}",
            "Payout (₹)": f"{r.payout_total:,.2f}",
            "Delta (₹)": f"{r.delta:,.2f}",
        })

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
    )


def _render_unresolved_tab(pipeline_result: dict):
    explanations = pipeline_result["explanations"]
    if not explanations:
        st.success("🎉 No unresolved mismatches — all batches reconciled!")
        return

    for item in explanations:
        delta_str = f"₹{abs(item['delta']):,.2f}"
        direction = "under" if item["delta"] > 0 else "over"
        conf = item["confidence"]
        conf_pct = f"{conf:.0%}"
        color = _confidence_color(conf)

        with st.expander(
            f"🔴  **{item['settlement_batch_id']}**  —  "
            f"Δ {delta_str} {direction}  |  "
            f"Confidence {conf_pct}",
            expanded=True,
        ):
            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("Expected Net", f"₹{item['expected_net']:,.2f}")
            mc2.metric("Actual Payout", f"₹{item['payout_total']:,.2f}")
            mc3.metric("Delta", f"₹{item['delta']:,.2f}")
            mc4.metric("Confidence", conf_pct)

            # Confidence bar
            st.markdown(
                f'<div class="conf-bar-bg">'
                f'<div class="conf-bar-fill" style="width:{conf*100:.0f}%;'
                f'background:{color};"></div></div>',
                unsafe_allow_html=True,
            )

            st.markdown("")
            st.markdown(f"**AI Explanation**")
            st.markdown(
                f"<div style='background:rgba(99,102,241,0.08);padding:16px 20px;"
                f"border-radius:10px;border-left:3px solid {color};'>"
                f"{item['explanation']}</div>",
                unsafe_allow_html=True,
            )

            if item.get("fee_breakdown"):
                st.markdown("")
                st.markdown("**Fee Breakdown**")
                fee_df = pd.DataFrame(
                    [{"Category": k, "Amount (₹)": f"{v:,.2f}"}
                     for k, v in item["fee_breakdown"].items()]
                )
                st.dataframe(fee_df, use_container_width=True, hide_index=True)


def _render_audit_tab(pipeline_result: dict):
    audit = pipeline_result["audit_log"]
    if not audit:
        st.info("No audit entries — no mismatches were processed by the AI agent.")
        return

    for entry in audit:
        conf = entry["confidence"]
        with st.expander(
            f"📋  **{entry['settlement_batch_id']}**  —  "
            f"{entry['timestamp']}"
        ):
            st.markdown("**Anonymized PII Fields**")
            if entry["pii_fields_anonymized"]:
                badges = "  ".join(
                    f"`{f}`" for f in entry["pii_fields_anonymized"]
                )
                st.markdown(badges)
            else:
                st.caption("No PII fields detected in this record.")

            st.markdown("---")
            st.markdown(f"**Confidence Score:** `{conf}`")
            st.markdown(f"**Generated Explanation:**")
            st.markdown(f"> {entry['explanation']}")

            st.markdown("---")
            st.markdown(
                f"**LLM Prompts Sent** ({len(entry['llm_payloads'])} total)"
            )
            for i, payload in enumerate(entry["llm_payloads"]):
                label = "Explanation Prompt" if i == 0 else "Confidence Prompt"
                st.markdown(f"*{label}:*")
                st.code(payload, language="text")

            # PII leak check confirmation
            all_clean = True
            for payload in entry["llm_payloads"]:
                try:
                    pii_guard(payload)
                except Exception:
                    all_clean = False
                    break

            if all_clean:
                st.success("✅ PII guard verified — no sensitive data in any payload")
            else:
                st.error("⚠️ PII leak detected!")


# ═══════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════════════

def _render_sidebar() -> dict | None:
    """Render sidebar controls; return config dict or None."""
    with st.sidebar:
        st.markdown("## ⚙️  Configuration")
        st.markdown("---")

        st.markdown("### 📂  Data Files")

        use_sample = st.checkbox("Use sample data", value=True)

        ledger_source = None
        settlement_source = None
        fee_source = None

        if use_sample:
            data_dir = _PROJECT_ROOT / "data"
            ledger_source = data_dir / "sample_ledger.csv"
            settlement_source = data_dir / "sample_settlements.csv"
            fee_source = data_dir / "fee_schedule.csv"
            st.caption(f"📄 Ledger: `sample_ledger.csv`")
            st.caption(f"📄 Settlements: `sample_settlements.csv`")
            st.caption(f"📄 Fee schedule: `fee_schedule.csv`")
        else:
            ledger_file = st.file_uploader(
                "Upload Ledger CSV",
                type=["csv"],
                key="ledger",
            )
            settlement_file = st.file_uploader(
                "Upload Settlement CSV",
                type=["csv"],
                key="settlement",
            )
            fee_file = st.file_uploader(
                "Upload Fee Schedule CSV (optional)",
                type=["csv"],
                key="fee_schedule",
            )
            if ledger_file:
                ledger_source = ledger_file
            if settlement_file:
                settlement_source = settlement_file
            if fee_file:
                fee_source = fee_file
            else:
                fee_source = _PROJECT_ROOT / "data" / "fee_schedule.csv"

        st.markdown("---")
        st.markdown("### 🎚️  Settings")
        tolerance = st.slider(
            "Matching Tolerance (₹)",
            min_value=0.0,
            max_value=50.0,
            value=1.0,
            step=0.5,
            help="Maximum absolute delta to still consider a match.",
        )

        st.markdown("---")
        run = st.button("🚀  Run Reconciliation", use_container_width=True)

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

    # Persistent result in session state
    if "pipeline_result" not in st.session_state:
        st.session_state["pipeline_result"] = None

    if config is not None:
        with st.spinner("Running reconciliation pipeline…"):
            try:
                ledger_df = load_ledger(config["ledger_source"])
                settlement_df = load_settlements(config["settlement_source"])
                fee_schedule_df = load_fee_schedule(config["fee_source"])
                result = run_pipeline(
                    ledger_df,
                    settlement_df,
                    fee_schedule_df,
                    tolerance=config["tolerance"],
                )
                st.session_state["pipeline_result"] = result
            except Exception as exc:
                st.error(f"Pipeline error: {exc}")
                st.session_state["pipeline_result"] = None

    result = st.session_state["pipeline_result"]

    if result is None:
        # Landing state
        st.markdown(
            "<div style='text-align:center;padding:80px 20px;'>"
            "<p style='font-size:3.5rem;margin-bottom:0;'>📊</p>"
            "<p style='color:#94a3b8;font-size:1.15rem;max-width:480px;"
            "margin:12px auto 0;'>"
            "Upload your settlement and ledger files, or check "
            "<b>\"Use sample data\"</b> in the sidebar, then click "
            "<b>Run Reconciliation</b> to start."
            "</p></div>",
            unsafe_allow_html=True,
        )
        return

    # ── Results ──────────────────────────────────────────────────────
    _render_metrics(result)
    st.markdown("")

    tab1, tab2, tab3 = st.tabs([
        "✅  Resolved",
        "🔴  Unresolved & Explanations",
        "📋  Audit Log",
    ])

    with tab1:
        _render_resolved_tab(result)

    with tab2:
        _render_unresolved_tab(result)

    with tab3:
        _render_audit_tab(result)


if __name__ == "__main__":
    main()
