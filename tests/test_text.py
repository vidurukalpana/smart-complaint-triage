from collections import Counter

import pytest

from smart_complaint_triage.text import (
    clean_narrative,
    mask_pii,
    replace_amounts,
    replace_redactions,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("{$1,200.50}", "[AMOUNT:1200.50]"),
        ("{$XXXX}", "[AMOUNT:REDACTED]"),
    ],
)
def test_replace_amounts(text, expected):
    assert replace_amounts(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("On XX/XX/2026 I called", "On [REDACTED_DATE] I called"),
        ("I called XXXX XXXX", "I called [REDACTED] [REDACTED]"),
        ("size XXL from Xerox", "size XXL from Xerox"),  # real words are kept
    ],
)
def test_replace_redactions(text, expected):
    assert replace_redactions(text) == expected


@pytest.mark.parametrize(
    ("text", "expected", "label"),
    [
        ("mail me at john.doe@mail.com now", "mail me at [EMAIL] now", "EMAIL"),
        ("call 555-123-4567", "call [PHONE]", "PHONE"),
        ("card 4111 1111 1111 1111 was", "card [ACCOUNT_NUMBER] was", "ACCOUNT_NUMBER"),
        ("account 123456789", "account [ACCOUNT_NUMBER]", "ACCOUNT_NUMBER"),
    ],
)
def test_mask_pii(text, expected, label):
    counts = Counter()
    assert mask_pii(text, counts) == expected
    assert counts == {label: 1}


@pytest.mark.parametrize(
    "text",
    [
        "Act 15 U.S.C. 6801-6809",  # law section range
        "under 15 U.S.C. 16921692",  # law section written without a dash
        "[AMOUNT:12345678.00]",  # amounts are never masked
    ],
)
def test_mask_pii_leaves_non_pii(text):
    assert mask_pii(text) == text


def test_clean_narrative_full():
    text = "On XX/XX/2026  I sent {$500.00} to XXXX.\nCall 555-123-4567."
    assert clean_narrative(text) == (
        "On [REDACTED_DATE] I sent [AMOUNT:500.00] to [REDACTED]. Call [PHONE]."
    )
