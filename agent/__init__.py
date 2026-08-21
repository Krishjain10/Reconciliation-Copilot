"""
agent — AI Explanation Agent (LangGraph + LLM)

Takes unresolved mismatches from the matching engine, anonymises all
sensitive fields (HMAC-based tokenisation), and uses a structured
LangGraph workflow to produce plain-language explanations with
confidence scores.

Key responsibilities:
    • Anonymise sensitive identifiers before any LLM call.
    • Run a regex safety-net to block accidental PII leakage.
    • Build a structured prompt with mismatch evidence.
    • Call the LLM (Claude / similar) and parse the response.
    • Attach a confidence score to every explanation.
    • De-anonymise results locally for display to the user.
    • Log every prompt + response for the audit trail.
"""
