from collections import Counter

import pytest

from smart_complaint_triage.text import (
    clean_narrative,
    count_letters,
    duplicate_key,
    mask_pii,
    normalize_whitespace,
    replace_amounts,
    replace_redactions,
    strip_tokens,
)


def test_normalize_whitespace():
    assert normalize_whitespace("  I   called\n\nthe\tbank  ") == "I called the bank"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I paid {$120.00} twice", "I paid [AMOUNT:120.00] twice"),
        ("{$1,200.50}", "[AMOUNT:1200.50]"),
        ("{$.99}", "[AMOUNT:.99]"),
        ("{$XXXX}", "[AMOUNT:REDACTED]"),
        ("$120 without braces", "$120 without braces"),
    ],
)
def test_replace_amounts(text, expected):
    assert replace_amounts(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("On XX/XX/XXXX I called", "On [REDACTED_DATE] I called"),
        ("On XX/XX/2026 I called", "On [REDACTED_DATE] I called"),
        ("since XX/XX", "since [REDACTED_DATE]"),
        ("I called XXXX XXXX", "I called [REDACTED] [REDACTED]"),
        ("account XXXXXXXX", "account [REDACTED]"),
        ("ref XXXX-XXXX", "ref [REDACTED]"),
        ("size XXL from Xerox", "size XXL from Xerox"),  # real words are kept
        ("on 05/15/2026", "on 05/15/2026"),  # unredacted dates are kept
    ],
)
def test_replace_redactions(text, expected):
    assert replace_redactions(text) == expected


@pytest.mark.parametrize(
    ("text", "expected", "label"),
    [
        ("mail me at john.doe@mail.com now", "mail me at [EMAIL] now", "EMAIL"),
        ("call 555-123-4567", "call [PHONE]", "PHONE"),
        ("call (555) 123-4567", "call [PHONE]", "PHONE"),
        ("call +1 555 123 4567", "call [PHONE]", "PHONE"),
        ("card 4111 1111 1111 1111 was", "card [ACCOUNT_NUMBER] was", "ACCOUNT_NUMBER"),
        ("account 123456789", "account [ACCOUNT_NUMBER]", "ACCOUNT_NUMBER"),
        ("tracking 9589 0710 5270 2570", "tracking [ACCOUNT_NUMBER]", "ACCOUNT_NUMBER"),
    ],
)
def test_mask_pii(text, expected, label):
    counts = Counter()
    assert mask_pii(text, counts) == expected
    assert counts == {label: 1}


@pytest.mark.parametrize(
    "text",
    [
        "on 2026-05-15",  # ISO date
        "under 15 U.S.C. 1681",  # legal citation
        "reference 12345678",  # 8 digits in a row is too short
        "Act 15 U.S.C. 6801-6809",  # law section range
        "under 15 U.S.C. 16921692",  # law section written without a dash
        "violates FCRA 616-617 15",
        "hold 3-5 to 14-30-45-90 days",
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


def test_strip_tokens():
    assert strip_tokens("I paid [AMOUNT:5.00] to [REDACTED] today") == "I paid to today"


def test_count_letters():
    assert count_letters("ok 123 [AMOUNT:5.00] é") == 3 + len("AMOUNT")


def test_duplicate_key_ignores_case_and_spacing():
    assert duplicate_key("I  was CHARGED twice") == duplicate_key("i was charged twice")
