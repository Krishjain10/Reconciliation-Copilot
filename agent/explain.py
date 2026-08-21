"""
agent.explain — LangGraph Explanation Agent

A three-node workflow that takes an **anonymised** mismatch record and
produces a plain-language explanation with a confidence score.

Nodes
-----
1. **gather_evidence** – assembles a structured text summary from the
   mismatch dict (no LLM call).
2. **generate_explanation** – sends the evidence to the LLM and obtains
   a human-readable explanation.
3. **score_confidence** – asks the LLM to self-rate its confidence on a
   0.0–1.0 scale.

Every outgoing LLM payload passes through :func:`agent.pii_guard.pii_guard`
before being transmitted.  If the guard detects an account-number or
IFSC-code pattern it raises :class:`agent.pii_guard.PIILeakError` and the
call is aborted.
"""

from __future__ import annotations

import operator
from typing import Annotated, Callable, List, TypedDict

from langgraph.graph import END, START, StateGraph

from agent.pii_guard import pii_guard as default_pii_guard


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------

class ExplanationState(TypedDict, total=False):
    """State that flows through the explanation graph."""

    mismatch: dict
    """Anonymised mismatch record (sensitive fields already tokenised)."""

    evidence: str
    """Structured evidence text assembled by the first node."""

    explanation: str
    """LLM-generated plain-language explanation."""

    confidence: float
    """LLM self-rated confidence score (0.0 – 1.0)."""

    llm_payloads: Annotated[List[str], operator.add]
    """Audit trail: every prompt string sent to the LLM."""


# ---------------------------------------------------------------------------
# Node factories — each returns a closure that captures llm / guard deps
# ---------------------------------------------------------------------------

def _make_gather_evidence():
    """Build the *gather_evidence* node (pure logic, no LLM call)."""

    def gather_evidence(state: ExplanationState) -> dict:
        m = state["mismatch"]

        lines = [
            "=== Reconciliation Mismatch Evidence ===",
            f"Batch ID        : {m.get('settlement_batch_id', 'N/A')}",
            f"Ledger Total    : {m.get('ledger_total', 'N/A')}",
            f"Total Fees      : {m.get('total_fees', 'N/A')}",
            f"Expected Net    : {m.get('expected_net', 'N/A')}",
            f"Payout Total    : {m.get('payout_total', 'N/A')}",
            f"Delta           : {m.get('delta', 'N/A')}",
        ]

        if m.get("fee_breakdown"):
            lines.append("Fee Breakdown   :")
            for cat, amt in m["fee_breakdown"].items():
                lines.append(f"  - {cat}: {amt}")

        # Append any extra (already-anonymised) fields
        _skip = {
            "settlement_batch_id", "ledger_total", "total_fees",
            "expected_net", "payout_total", "delta", "fee_breakdown",
            "status",
        }
        for k, v in m.items():
            if k not in _skip:
                lines.append(f"{k:16s}: {v}")

        return {"evidence": "\n".join(lines)}

    return gather_evidence


def _make_generate_explanation(
    llm_callable: Callable[[str], str],
    guard_fn: Callable[[str], None],
):
    """Build the *generate_explanation* node (LLM call)."""

    def generate_explanation(state: ExplanationState) -> dict:
        prompt = (
            "You are a financial reconciliation assistant. A mismatch was "
            "found between a settlement payout and the merchant's internal "
            "ledger. Based on the evidence below, explain the most likely "
            "cause of the mismatch in plain language that a finance team "
            "member can understand.\n\n"
            f"{state['evidence']}\n\n"
            "Provide a clear, concise explanation."
        )
        guard_fn(prompt)                       # raises PIILeakError on leak
        response = llm_callable(prompt)
        return {"explanation": response, "llm_payloads": [prompt]}

    return generate_explanation


def _make_score_confidence(
    llm_callable: Callable[[str], str],
    guard_fn: Callable[[str], None],
):
    """Build the *score_confidence* node (LLM call)."""

    def score_confidence(state: ExplanationState) -> dict:
        prompt = (
            "You are a financial reconciliation assistant. You previously "
            "generated the following explanation for a settlement mismatch:"
            f"\n\nExplanation: {state['explanation']}\n\n"
            f"Evidence:\n{state['evidence']}\n\n"
            "Rate your confidence in this explanation on a scale from 0.0 "
            "(no confidence) to 1.0 (fully confident). Reply with ONLY a "
            "decimal number between 0.0 and 1.0."
        )
        guard_fn(prompt)                       # raises PIILeakError on leak
        response = llm_callable(prompt)

        try:
            confidence = float(response.strip())
            confidence = max(0.0, min(1.0, confidence))
        except (ValueError, TypeError):
            confidence = 0.5                   # safe fallback

        return {"confidence": confidence, "llm_payloads": [prompt]}

    return score_confidence


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_explanation_graph(
    llm_callable: Callable[[str], str],
    guard_fn: Callable[[str], None] = default_pii_guard,
):
    """Construct and compile the three-node explanation graph.

    Parameters
    ----------
    llm_callable
        ``(prompt: str) -> str`` — calls the LLM and returns its text.
    guard_fn
        ``(payload: str) -> None`` — raises on PII leak.
        Defaults to :func:`agent.pii_guard.pii_guard`.

    Returns
    -------
    CompiledStateGraph
        Invoke with ``{"mismatch": <dict>, "llm_payloads": []}``.
    """
    builder: StateGraph = StateGraph(ExplanationState)

    builder.add_node("gather_evidence", _make_gather_evidence())
    builder.add_node(
        "generate_explanation",
        _make_generate_explanation(llm_callable, guard_fn),
    )
    builder.add_node(
        "score_confidence",
        _make_score_confidence(llm_callable, guard_fn),
    )

    builder.add_edge(START, "gather_evidence")
    builder.add_edge("gather_evidence", "generate_explanation")
    builder.add_edge("generate_explanation", "score_confidence")
    builder.add_edge("score_confidence", END)

    return builder.compile()


# ---------------------------------------------------------------------------
# Convenience entry-point
# ---------------------------------------------------------------------------

def explain_mismatch(
    mismatch: dict,
    llm_callable: Callable[[str], str],
    guard_fn: Callable[[str], None] = default_pii_guard,
) -> dict:
    """Run the full explanation pipeline on one **anonymised** mismatch.

    Returns
    -------
    dict
        ``{"explanation": str, "confidence": float, "llm_payloads": list[str]}``
    """
    graph = build_explanation_graph(llm_callable, guard_fn)
    result = graph.invoke({"mismatch": mismatch, "llm_payloads": []})
    return {
        "explanation": result["explanation"],
        "confidence": result["confidence"],
        "llm_payloads": result["llm_payloads"],
    }
