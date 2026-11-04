"""Text cleaning for complaint narratives: CFPB redactions, amounts and remaining PII.

CFPB already removes personal information before publishing, writing it as ``XXXX``.
These functions turn CFPB's markers into clear tokens and mask anything it missed.
"""

from __future__ import annotations

import re
from collections import Counter

# Tokens produced by this module, e.g. "[REDACTED]" or "[AMOUNT:120.00]".
TOKEN = re.compile(r"\[[A-Z_]+(?::[^\]]*)?\]")

WHITESPACE = re.compile(r"\s+")

# CFPB amounts: "{$120.00}"; "{$XXXX}" when the amount itself was redacted.
AMOUNT = re.compile(r"\{\$([\d,]*\.?\d*|X+)\}")

# CFPB redacted dates: "XX/XX/XXXX", "XX/XX/2026", "XX/XX". At least one part is X's.
REDACTED_DATE = re.compile(
    r"\b(?=[\d/]*X)(?:XX|\d{1,2})/(?:XX|\d{1,2})(?:/(?:XXXX|XX|\d{2}|\d{4}))?\b"
)

# Any other token built from runs of X (2 or more), e.g. "XXXX", "XXXXXXXX", "XXXX-XXXX".
REDACTED = re.compile(r"\b(?=[X\d/-]*XX)[X\d]+(?:[/-][X\d]+)*\b")

EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")

# US phone numbers: 555-123-4567, (555) 123-4567, 555.123.4567, +1 555 123 4567.
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\d{3}[\s.-])\d{3}[\s.-]\d{4}(?!\d)")

# Account-like numbers: 9+ digits in a row, or 12+ digits in groups split by spaces or dashes.
NUMBER_RUN = re.compile(r"(?<![\d.])\d(?:[ -]?\d)+(?![\d.])")
MIN_DIGITS_IN_A_ROW = 9
MIN_DIGITS_IN_GROUPS = 12

LETTER = re.compile(r"[^\W\d_]")


def normalize_whitespace(text: str) -> str:
    return WHITESPACE.sub(" ", text).strip()


def replace_amounts(text: str) -> str:
    """``{$1,200.50}`` -> ``[AMOUNT:1200.50]``; ``{$XXXX}`` -> ``[AMOUNT:REDACTED]``."""

    def repl(match: re.Match[str]) -> str:
        value = match.group(1)
        if value.startswith("X"):
            return "[AMOUNT:REDACTED]"
        return f"[AMOUNT:{value.replace(',', '')}]"

    return AMOUNT.sub(repl, text)


def replace_redactions(text: str) -> str:
    """CFPB ``XX/XX/XXXX`` -> ``[REDACTED_DATE]``; other ``XXXX`` tokens -> ``[REDACTED]``."""
    text = REDACTED_DATE.sub("[REDACTED_DATE]", text)
    return REDACTED.sub("[REDACTED]", text)


def mask_pii(text: str, counts: Counter[str] | None = None) -> str:
    """Mask emails, phone numbers and account-like numbers outside existing tokens."""
    parts = TOKEN.split(text)
    tokens = TOKEN.findall(text)
    masked = [_mask_segment(part, counts) for part in parts]
    out = [masked[0]]
    for token, part in zip(tokens, masked[1:], strict=True):
        out += [token, part]
    return "".join(out)


def _mask_segment(segment: str, counts: Counter[str] | None) -> str:
    def sub(pattern: re.Pattern[str], label: str, text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            if label == "ACCOUNT_NUMBER" and not _is_account_like(match.group(0)):
                return match.group(0)
            if counts is not None:
                counts[label] += 1
            return f"[{label}]"

        return pattern.sub(repl, text)

    segment = sub(EMAIL, "EMAIL", segment)
    segment = sub(PHONE, "PHONE", segment)
    return sub(NUMBER_RUN, "ACCOUNT_NUMBER", segment)


def _is_account_like(number: str) -> bool:
    digits = sum(ch.isdigit() for ch in number)
    if number.isdigit():
        return digits >= MIN_DIGITS_IN_A_ROW
    return digits >= MIN_DIGITS_IN_GROUPS


def clean_narrative(text: str, counts: Counter[str] | None = None) -> str:
    """Full cleaning: whitespace, amounts, CFPB redactions, then remaining PII."""
    text = normalize_whitespace(text)
    text = replace_amounts(text)
    text = replace_redactions(text)
    return mask_pii(text, counts)


def strip_tokens(text: str) -> str:
    """Text without tokens, e.g. for language detection."""
    return normalize_whitespace(TOKEN.sub(" ", text))


def count_letters(text: str) -> int:
    return len(LETTER.findall(text))


def duplicate_key(text: str) -> str:
    """Key under which narratives count as duplicates: case and spacing are ignored."""
    return normalize_whitespace(text).lower()
