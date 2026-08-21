"""
agent.anonymize — HMAC-based field tokenization

Replaces sensitive identifiers (account numbers, names, IFSC codes)
with deterministic, non-reversible tokens before any data leaves the
secure boundary.  A local reverse-lookup table allows de-tokenization
for display to authorised users only.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Dict, List, Optional


# Default field names that should always be anonymised
SENSITIVE_FIELDS: List[str] = [
    "account_number",
    "beneficiary_name",
    "ifsc_code",
    "counterparty_name",
    "payer_name",
    "payee_name",
]

_DEFAULT_SECRET = b"recon-copilot-hmac-key-v1"


class Anonymizer:
    """HMAC-SHA-256 tokenizer for sensitive record fields."""

    def __init__(self, secret: bytes = _DEFAULT_SECRET):
        self._secret = secret
        self._lookup: Dict[str, str] = {}   # token → original value

    # ------------------------------------------------------------------
    # Core token operations
    # ------------------------------------------------------------------

    def tokenize(self, value: str) -> str:
        """Replace a single raw value with an HMAC-derived token."""
        if not value:
            return value
        digest = hmac.new(
            self._secret, value.encode("utf-8"), hashlib.sha256,
        ).hexdigest()
        token = f"TOK_{digest[:16].upper()}"
        self._lookup[token] = value
        return token

    def detokenize(self, token: str) -> str:
        """Restore the original value from a token (local-only)."""
        return self._lookup.get(token, token)

    # ------------------------------------------------------------------
    # Record-level helpers
    # ------------------------------------------------------------------

    def anonymize_record(
        self,
        record: dict,
        sensitive_fields: Optional[List[str]] = None,
    ) -> dict:
        """Return a shallow copy of *record* with sensitive fields tokenized."""
        fields = sensitive_fields or SENSITIVE_FIELDS
        out = dict(record)
        for key in fields:
            if key in out and out[key]:
                out[key] = self.tokenize(str(out[key]))
        return out

    def deanonymize_record(
        self,
        record: dict,
        sensitive_fields: Optional[List[str]] = None,
    ) -> dict:
        """Return a shallow copy of *record* with tokens replaced by originals."""
        fields = sensitive_fields or SENSITIVE_FIELDS
        out = dict(record)
        for key in fields:
            if key in out:
                out[key] = self.detokenize(out[key])
        return out
