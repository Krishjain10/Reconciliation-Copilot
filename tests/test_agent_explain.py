"""
Tests for agent.explain — LangGraph Explanation Agent + PII safety.

Covers:
    1. PII guard blocks raw account numbers
    2. PII guard blocks raw IFSC codes
    3. PII guard allows clean (tokenised) payloads
    4. End-to-end agent run with anonymised data — no raw PII in any
       LLM payload
    5. Agent raises PIILeakError if un-anonymised data reaches the LLM
    6. Confidence score is parsed correctly
    7. Confidence fallback on malformed LLM response
    8. Anonymizer tokenises and de-tokenises correctly
"""

from __future__ import annotations

import pytest

from agent.anonymize import Anonymizer, SENSITIVE_FIELDS
from agent.pii_guard import PIILeakError, pii_guard
from agent.explain import build_explanation_graph, explain_mismatch


# ---------------------------------------------------------------------------
# Shared test constants — realistic raw PII
# ---------------------------------------------------------------------------

RAW_ACCOUNT_NUMBER = "920010012345678"      # 15-digit bank account
RAW_IFSC_CODE = "HDFC0001234"               # valid IFSC pattern
RAW_NAME = "Rajesh Kumar"                   # beneficiary name


def _make_raw_mismatch(**overrides) -> dict:
    """Return a mismatch record that contains raw PII."""
    base = {
        "settlement_batch_id": "B42",
        "ledger_total": 15000.0,
        "total_fees": 300.0,
        "expected_net": 14700.0,
        "payout_total": 14500.0,
        "delta": 200.0,
        "fee_breakdown": {"payment": 300.0},
        "account_number": RAW_ACCOUNT_NUMBER,
        "ifsc_code": RAW_IFSC_CODE,
        "beneficiary_name": RAW_NAME,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Mock LLM — records every prompt it receives
# ---------------------------------------------------------------------------

class MockLLM:
    """Callable that records prompts and returns canned responses."""

    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if "Rate your confidence" in prompt:
            return "0.85"
        return (
            "The mismatch is most likely caused by an unexpected "
            "fee deduction that differs from the standard fee schedule."
        )


# ---------------------------------------------------------------------------
# PII Guard unit tests
# ---------------------------------------------------------------------------

class TestPIIGuard:
    def test_blocks_account_number(self):
        with pytest.raises(PIILeakError, match="account-number"):
            pii_guard(f"Account: {RAW_ACCOUNT_NUMBER}")

    def test_blocks_ifsc_code(self):
        with pytest.raises(PIILeakError, match="IFSC"):
            pii_guard(f"IFSC: {RAW_IFSC_CODE}")

    def test_allows_clean_payload(self):
        # Tokenised values and normal text should pass
        pii_guard("Batch B42: TOK_A1B2C3D4E5F6G7H8 has a delta of 200.0")

    def test_allows_short_numbers(self):
        # Numbers shorter than 9 digits are fine (amounts, IDs)
        pii_guard("Amount: 14500.00, delta: 200.0, batch: 42")


# ---------------------------------------------------------------------------
# Anonymizer unit tests
# ---------------------------------------------------------------------------

class TestAnonymizer:
    def test_tokenize_produces_tok_prefix(self):
        anon = Anonymizer()
        token = anon.tokenize("920010012345678")
        assert token.startswith("TOK_")
        assert "920010012345678" not in token

    def test_detokenize_round_trip(self):
        anon = Anonymizer()
        token = anon.tokenize("HDFC0001234")
        assert anon.detokenize(token) == "HDFC0001234"

    def test_anonymize_record_replaces_sensitive_fields(self):
        anon = Anonymizer()
        record = _make_raw_mismatch()
        safe = anon.anonymize_record(record)

        assert safe["account_number"].startswith("TOK_")
        assert safe["ifsc_code"].startswith("TOK_")
        assert safe["beneficiary_name"].startswith("TOK_")
        # Non-sensitive fields are untouched
        assert safe["settlement_batch_id"] == "B42"
        assert safe["ledger_total"] == 15000.0

    def test_deanonymize_record_restores_values(self):
        anon = Anonymizer()
        record = _make_raw_mismatch()
        safe = anon.anonymize_record(record)
        restored = anon.deanonymize_record(safe)

        assert restored["account_number"] == RAW_ACCOUNT_NUMBER
        assert restored["ifsc_code"] == RAW_IFSC_CODE
        assert restored["beneficiary_name"] == RAW_NAME

    def test_deterministic_tokens(self):
        anon = Anonymizer()
        t1 = anon.tokenize("920010012345678")
        t2 = anon.tokenize("920010012345678")
        assert t1 == t2


# ---------------------------------------------------------------------------
# End-to-end agent tests (with mock LLM)
# ---------------------------------------------------------------------------

class TestExplainMismatchNoPII:
    """The critical test: no raw PII must ever appear in any LLM payload."""

    def test_no_raw_pii_in_llm_payloads(self):
        # 1. Start with a record that has real PII
        raw = _make_raw_mismatch()

        # 2. Anonymise it (as the real pipeline would)
        anon = Anonymizer()
        safe = anon.anonymize_record(raw)

        # 3. Run through the agent with a mock LLM
        mock = MockLLM()
        result = explain_mismatch(safe, llm_callable=mock)

        # 4. Assert no raw PII in ANY payload that was sent to the LLM
        all_payloads = result["llm_payloads"]
        assert len(all_payloads) == 2, "Expected 2 LLM calls (explain + confidence)"

        for i, payload in enumerate(all_payloads):
            assert RAW_ACCOUNT_NUMBER not in payload, (
                f"Raw account number leaked in payload #{i}"
            )
            assert RAW_IFSC_CODE not in payload, (
                f"Raw IFSC code leaked in payload #{i}"
            )
            assert RAW_NAME not in payload, (
                f"Raw beneficiary name leaked in payload #{i}"
            )

        # 5. Tokens SHOULD be present (proves the data made it through)
        combined = " ".join(all_payloads)
        assert "TOK_" in combined, "Tokenised values should appear in the payload"

    def test_guard_fires_on_raw_pii(self):
        """If someone accidentally passes un-anonymised data, the guard
        must raise before anything reaches the LLM."""
        raw = _make_raw_mismatch()    # NOT anonymised!
        mock = MockLLM()

        with pytest.raises(PIILeakError):
            explain_mismatch(raw, llm_callable=mock)

        # The mock LLM must never have been called
        assert len(mock.prompts) == 0, (
            "LLM should NOT have been called — guard should have blocked first"
        )


class TestConfidenceScoring:
    def test_confidence_parsed_correctly(self):
        anon = Anonymizer()
        safe = anon.anonymize_record(_make_raw_mismatch())
        mock = MockLLM()                       # returns "0.85" for confidence
        result = explain_mismatch(safe, llm_callable=mock)

        assert result["confidence"] == 0.85

    def test_confidence_fallback_on_bad_response(self):
        anon = Anonymizer()
        safe = anon.anonymize_record(_make_raw_mismatch())

        def bad_llm(prompt: str) -> str:
            if "Rate your confidence" in prompt:
                return "I'm not sure, maybe medium?"   # not a float
            return "Some explanation."

        result = explain_mismatch(safe, llm_callable=bad_llm)
        assert result["confidence"] == 0.5     # fallback value


class TestGraphStructure:
    """Verify the graph executes all three nodes in order."""

    def test_all_state_keys_populated(self):
        anon = Anonymizer()
        safe = anon.anonymize_record(_make_raw_mismatch())
        mock = MockLLM()
        result = explain_mismatch(safe, llm_callable=mock)

        assert "explanation" in result
        assert "confidence" in result
        assert "llm_payloads" in result
        assert isinstance(result["explanation"], str)
        assert len(result["explanation"]) > 0

    def test_llm_called_exactly_twice(self):
        anon = Anonymizer()
        safe = anon.anonymize_record(_make_raw_mismatch())
        mock = MockLLM()
        explain_mismatch(safe, llm_callable=mock)

        assert len(mock.prompts) == 2, (
            "LLM should be called once for explanation and once for confidence"
        )
