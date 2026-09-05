"""
ui.app — Reconciliation Copilot Dashboard (Streamlit)

Connects the full pipeline:
    ingestion → matching → anonymization → LangGraph agent

and presents results in a premium dashboard with:
    • Summary metric cards
    • Resolved transactions table
    • Unresolved mismatches with AI explanations & confidence
    • Full audit log of every LLM prompt

Run with:
    streamlit run ui/app.py
"""

from __future__ import annotations

import pathlib
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
from matching.engine import (
    BatchResult,
    MatchStatus,
    find_orphan_settlements,
    load_fee_schedule,
    match_batches,
    resolved,
    unresolved,
)
from ingestion.loader import load_ledger, load_settlements
from ui.mock_llm import create_fallback_llm
from ui.styles import inject_css
from ui.components import (
    render_header,
    render_stat_cards,
    render_resolved_section,
    render_unresolved_section,
    render_orphan_section,
    render_audit_section,
    render_detoken_section,
    render_empty_state,
)


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
    llm = llm_callable or create_fallback_llm()
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
# SIDEBAR
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
                ledger_source = ledger_files
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

def main():
    st.set_page_config(
        page_title="Reconciliation Copilot",
        page_icon="🏦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_css()
    render_header()

    config = _render_sidebar()

    if "pipeline_result" not in st.session_state:
        st.session_state["pipeline_result"] = None

    if config is not None:
        with st.spinner("Running reconciliation…"):
            try:
                src = config["ledger_source"]
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
        render_empty_state()
        return

    render_stat_cards(result)

    # Determine tab count based on orphans
    orphans = result.get("orphan_settlements", [])
    if orphans:
        tab1, tab2, tab3, tab4 = st.tabs(
            ["RESOLVED", "UNRESOLVED", f"ORPHANS ({len(orphans)})", "AUDIT LOG"])
    else:
        tab1, tab2, tab3, tab4 = st.tabs(
            ["RESOLVED", "UNRESOLVED", "ORPHANS", "AUDIT LOG"])

    with tab1:
        render_resolved_section(result)
    with tab2:
        render_unresolved_section(result)
    with tab3:
        render_orphan_section(result)
    with tab4:
        render_audit_section(result)
        render_detoken_section(result)


if __name__ == "__main__":
    main()
