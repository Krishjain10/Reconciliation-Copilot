"""
eval — Evaluation & Accuracy Measurement

Measures system accuracy against a curated "golden" evaluation set of
mismatches with known correct explanations. Also verifies that no
sensitive data leaks into outgoing AI requests.

Key responsibilities:
    • Load the golden evaluation dataset.
    • Run the full pipeline (ingestion → matching → agent) on eval data.
    • Compare generated explanations to ground-truth labels.
    • Compute accuracy, precision, and confidence-calibration metrics.
    • Run a PII-leak audit: confirm no raw account numbers, names, or
      IFSC codes appear in any LLM prompt sent during the eval run.
    • Produce a summary report suitable for demo / judging.
"""
