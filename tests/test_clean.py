from datetime import date

import pandas as pd
import pytest

pytest.importorskip("langdetect")

from smart_complaint_triage.clean import clean, detect_language, is_kept_language  # noqa: E402
from smart_complaint_triage.config import (  # noqa: E402
    UnknownProductError,
    load_cleaning_config,
    load_settings,
    load_taxonomy,
)

ENGLISH = "I was charged a fee on my checking account and the bank refused to refund it to me."
DUPLICATE = "My housing loan payment was applied to the wrong month and charged a late fee."
UPPER_COPY = DUPLICATE.upper()  # same text, different case
SPANISH = (
    "Me cobraron una comisión en mi cuenta de ahorros y el banco se negó a devolverme el dinero. "
    "Llamé varias veces al servicio al cliente y nadie me ayudó con el problema."
)
SHORT_CAPS = "KEEP HARRASING ME NON STOP. THREATING ME TO BE SUED."  # detected as "vi"
ONLY_REDACTED = "XXXX XXXX XXXX XXXX {$100.00} XX/XX/XXXX"


def complaint(complaint_id, **values) -> dict:
    row = {
        "complaint_id": complaint_id,
        "date_received": date(2026, 6, 1),
        "product": "Checking or savings account",
        "company": "SOME BANK",
        "narrative": ENGLISH,
    }
    row.update(values)
    return row


def run_clean(rows):
    return clean(pd.DataFrame(rows), load_settings(), load_taxonomy(), load_cleaning_config())


@pytest.fixture(scope="module")
def result():
    rows = [
        complaint(1, narrative=ENGLISH + " I paid {$25.00} on XX/XX/2026, call 555-123-4567."),
        complaint(2, company="EQUIFAX, INC."),
        complaint(3, product="Debt or credit management"),
        complaint(4, narrative=SPANISH),
        complaint(7, narrative=SHORT_CAPS),
        complaint(8, narrative=ONLY_REDACTED),
        complaint(5, date_received=date(2026, 5, 20), product="Mortgage", narrative=DUPLICATE),
        complaint(6, date_received=date(2026, 7, 30), product="Mortgage", narrative=UPPER_COPY),
    ]  # fmt: skip
    return run_clean(rows)


def test_rows_kept(result):
    df, report = result
    assert sorted(df["complaint_id"]) == [1, 5, 6, 7]
    assert report["rows_in"] == 8
    assert report["removed_credit_bureaus"] == 1
    assert report["removed_excluded_products"] == 1
    assert report["removed_no_usable_text"] == 1
    assert report["removed_non_english"] == {"es": 1}
    assert report["rows_out"] == 4


def test_narrative_cleaned_and_pii_counted(result):
    df, report = result
    narrative = df.set_index("complaint_id").loc[1, "narrative"]
    assert "[AMOUNT:25.00]" in narrative
    assert "[REDACTED_DATE]" in narrative
    assert "[PHONE]" in narrative
    assert report["pii_masked"] == {"PHONE": 1}


def test_team_mapping(result):
    df, _ = result
    teams = df.set_index("complaint_id")["team_id"].to_dict()
    assert teams == {
        1: "deposits_savings",
        5: "housing_loans",
        6: "housing_loans",
        7: "deposits_savings",
    }


def test_duplicates_marked_not_removed(result):
    df, report = result
    by_id = df.set_index("complaint_id")
    assert not by_id.loc[5, "is_duplicate_narrative"]  # earliest copy is the original
    assert by_id.loc[6, "is_duplicate_narrative"]
    assert by_id.loc[6, "narrative_duplicate_count"] == 2
    assert report["duplicate_narratives_marked"] == 1


def test_splits(result):
    df, _ = result
    by_id = df.set_index("complaint_id")
    assert by_id.loc[5, "routing_split"] == "train"
    assert by_id.loc[6, "routing_split"] == "test"
    assert pd.isna(by_id.loc[6, "escalation_split"])  # after the label cutoff


def test_unknown_product_raises():
    with pytest.raises(UnknownProductError):
        run_clean([complaint(1, product="Brand new CFPB product")])


def test_detect_language():
    assert detect_language(ENGLISH, max_chars=1000)[0] == "en"
    assert detect_language(SPANISH, max_chars=1000)[0] == "es"
    assert detect_language("[REDACTED] [AMOUNT:5.00]", max_chars=1000) == ("unknown", 0.0)


@pytest.mark.parametrize(
    ("lang", "prob", "letters", "kept"),
    [
        ("en", 0.5, 30, True),
        ("es", 0.99, 150, False),  # confident and long enough: dropped
        ("vi", 1.0, 41, True),  # too short to trust
        ("fr", 0.6, 240, True),  # not confident enough
    ],
)
def test_is_kept_language(lang, prob, letters, kept):
    assert is_kept_language(lang, prob, letters, load_cleaning_config().language) is kept
