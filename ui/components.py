"""
ui.components — Reusable rendering functions for the dashboard.

Each function corresponds to a visual section of the Reconciliation Copilot
UI.  They are called from app.py's main orchestration function.
"""

from __future__ import annotations

import re
from typing import List

import streamlit as st

from matching.engine import MatchStatus


# ── Helpers ──────────────────────────────────────────────────────────────

def _conf_color(c: float) -> str:
    if c >= 0.80:
        return "#1B7A43"
    if c >= 0.60:
        return "#B5650D"
    return "#B3261E"


def _md_bold(text: str) -> str:
    """Convert **markdown bold** to <strong> tags for HTML injection."""
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)


# ── Header ───────────────────────────────────────────────────────────────

def render_header() -> None:
    _HEADER_HTML = """
    <div class="lh">
      <div class="lh-text">
        <p class="lh-title">🏦 Reconciliation Copilot</p>
        <p class="lh-sub">
          Settlement reconciliation — match batches, explain mismatches,
          verify PII safety
        </p>
      </div>
    </div>
    """
    st.markdown(_HEADER_HTML, unsafe_allow_html=True)


# ── Stat cards ───────────────────────────────────────────────────────────

def render_stat_cards(res: dict) -> None:
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


# ── Resolved tab ─────────────────────────────────────────────────────────

def render_resolved_section(res: dict) -> None:
    matched = [r for r in res["all_results"]
               if r.status in (MatchStatus.MATCHED, MatchStatus.TOLERANCE_MATCHED)]

    if not matched:
        st.markdown(
            '<div class="empty">'
            '<span class="empty-icon">✅</span>'
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
    <div style="background:#FFF;border:1px solid #E4E2DA;border-radius:8px;overflow-x:auto;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
        <table class="ltbl" style="min-width:600px;">
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


# ── Unresolved tab ───────────────────────────────────────────────────────

def render_unresolved_section(res: dict) -> None:
    from agent.pii_guard import pii_guard

    explanations = res["explanations"]
    audit_log = res["audit_log"]

    if not explanations:
        st.markdown(
            '<div class="empty">'
            '<span class="empty-icon">✅</span>'
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
            f'<div class="mx-expl">{_md_bold(item["explanation"])}</div>'
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


# ── Orphans tab ──────────────────────────────────────────────────────────

def render_orphan_section(res: dict) -> None:
    orphans = res.get("orphan_settlements", [])

    if not orphans:
        st.markdown(
            '<div class="empty">'
            '<span class="empty-icon">📭</span>'
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

    extra_headers = ""
    if orphans:
        for k in orphans[0].extra_fields:
            extra_headers += f'<th>{k}</th>'

    st.markdown(f'''
    <div style="background:#FFF;border:1px solid #E4E2DA;border-radius:8px;overflow-x:auto;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
        <table class="ltbl" style="min-width:400px;">
            <thead><tr>
                <th>Batch</th><th class="r">Payout</th>
                <th>Status</th>{extra_headers}
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    ''', unsafe_allow_html=True)


# ── Audit Log tab ────────────────────────────────────────────────────────

def render_audit_section(res: dict) -> None:
    from agent.pii_guard import pii_guard

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


# ── De-tokenization section ──────────────────────────────────────────────

def render_detoken_section(res: dict) -> None:
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

    # DEMO-ONLY PLACEHOLDER: This is a demo passphrase, not production auth.
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


# ── Empty state / landing ────────────────────────────────────────────────

def render_empty_state() -> None:
    st.markdown(
        '<div class="empty">'
        '<span class="empty-icon">📂</span>'
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
