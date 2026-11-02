import pytest
import yaml
from pydantic import ValidationError

from smart_complaint_triage.config import (
    Glossary,
    Taxonomy,
    UnknownProductError,
    config_dir,
    load_glossary,
    load_taxonomy,
)


@pytest.fixture
def raw_taxonomy() -> dict:
    with (config_dir() / "taxonomy.yaml").open() as f:
        return yaml.safe_load(f)


def test_eight_sri_lankan_teams():
    assert [team.name for team in load_taxonomy().teams] == [
        "Deposits & Savings",
        "Cards",
        "Housing Loans",
        "Personal Loans",
        "Leasing & Vehicle Loans",
        "Payments & Digital Banking",
        "Recoveries",
        "Credit Information (CRIB) Disputes",
    ]


@pytest.mark.parametrize(
    ("product", "team_id"),
    [
        ("Checking or savings account", "deposits_savings"),
        ("Credit card", "cards"),
        ("Prepaid card", "cards"),
        ("Mortgage", "housing_loans"),
        ("Payday loan, title loan, personal loan, or advance loan", "personal_loans"),
        ("Student loan", "personal_loans"),
        ("Vehicle loan or lease", "leasing_vehicle_loans"),
        ("Money transfer, virtual currency, or money service", "payments_digital"),
        ("Debt collection", "recoveries"),
        ("Credit reporting or other personal consumer reports", "crib_disputes"),
    ],
)
def test_product_maps_to_team(product, team_id):
    assert load_taxonomy().team_for_product(product).id == team_id


def test_excluded_product_has_no_team():
    assert load_taxonomy().team_for_product("Debt or credit management") is None


def test_unknown_product_raises():
    with pytest.raises(UnknownProductError):
        load_taxonomy().team_for_product("Brand new CFPB product")


def test_triage_queue_and_pawning_documented():
    taxonomy = load_taxonomy()
    assert taxonomy.triage_queue.id == "human_triage"
    assert "Pawning" in [service.name for service in taxonomy.not_covered]


def test_every_team_has_a_description():
    assert all(team.description.strip() for team in load_taxonomy().teams)


def test_product_mapped_twice_rejected(raw_taxonomy):
    raw_taxonomy["teams"][1]["cfpb_products"].append("Mortgage")
    with pytest.raises(ValidationError, match="'Mortgage' is mapped to both"):
        Taxonomy.model_validate(raw_taxonomy)


def test_product_mapped_and_excluded_rejected(raw_taxonomy):
    raw_taxonomy["excluded_cfpb_products"].append("Mortgage")
    with pytest.raises(ValidationError, match="both mapped and excluded"):
        Taxonomy.model_validate(raw_taxonomy)


def test_duplicate_team_id_rejected(raw_taxonomy):
    raw_taxonomy["teams"][1]["id"] = raw_taxonomy["teams"][0]["id"]
    with pytest.raises(ValidationError, match="must be unique"):
        Taxonomy.model_validate(raw_taxonomy)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The credit bureau has wrong data.", "The CRIB has wrong data."),
        ("Experian shows a late payment.", "CRIB shows a late payment."),
        ("My Credit Report is wrong.", "My CRIB report is wrong."),
        ("The ACH transfer bounced.", "The SLIPS bounced."),
        ("I sent a wire transfer and a Zelle payment.", "I sent a CEFTS and a LankaPay payment."),
        ("My mortgage payment was lost.", "My housing loan payment was lost."),
        ("The debt collector keeps calling.", "The recoveries officer keeps calling."),
        ("I want to achieve a refund.", "I want to achieve a refund."),  # whole words only
    ],
)
def test_localize(text, expected):
    assert load_glossary().localize(text) == expected


def test_duplicate_us_term_rejected():
    with pytest.raises(ValidationError, match="more than once"):
        Glossary.model_validate(
            {
                "terms": [
                    {"us": ["Mortgage"], "sri_lanka": "housing loan"},
                    {"us": ["mortgage"], "sri_lanka": "home loan"},
                ]
            }
        )
