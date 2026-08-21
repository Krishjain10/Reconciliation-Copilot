"""
agent.pii_guard — Pre-send regex safety net

Scans any outgoing text payload for patterns that look like raw
account numbers or IFSC codes.  If a match is found the payload
is blocked and a :class:`PIILeakError` is raised, preventing
sensitive data from ever reaching an external LLM API.
"""

from __future__ import annotations

import re


class PIILeakError(Exception):
    """Raised when a PII pattern is detected in an outgoing LLM payload."""


# Indian bank account numbers: 9–18 consecutive digits.
# The negative lookahead excludes decimal amounts (e.g. 1234567890.00).
_ACCOUNT_NUMBER_RE = re.compile(r"\b\d{9,18}\b(?!\.\d)")

# IFSC code: 4 uppercase letters + literal zero + 6 alphanumeric chars
_IFSC_RE = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")


def pii_guard(payload: str) -> None:
    """Raise :class:`PIILeakError` if *payload* contains recognisable PII.

    Call this immediately before sending any text to an external LLM API.
    The check is intentionally aggressive — it is better to block a
    false-positive than to leak a real account number.
    """
    match = _ACCOUNT_NUMBER_RE.search(payload)
    if match:
        raise PIILeakError(
            f"Blocked: account-number pattern detected in outgoing payload "
            f"(matched {match.group()!r})"
        )

    match = _IFSC_RE.search(payload)
    if match:
        raise PIILeakError(
            f"Blocked: IFSC-code pattern detected in outgoing payload "
            f"(matched {match.group()!r})"
        )
