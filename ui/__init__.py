"""
ui — User Interface (Streamlit Dashboard)

Provides a web-based dashboard where finance users can:
    • Upload settlement and ledger files.
    • View auto-detected mismatches with status indicators.
    • Read AI-generated plain-language explanations.
    • Ask follow-up questions via an inline chat interface.
    • Review the full audit trail for any explanation.

Key responsibilities:
    • Render the mismatch list with filters and sorting.
    • Display confidence scores and flag low-confidence items.
    • Provide file-upload and data-preview widgets.
    • Wire up the chat interface to the Explanation Agent.
"""
