import pytest
import yaml
from pydantic import ValidationError

from smart_complaint_triage.config import (
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


@pytest.mark.parametrize(
    ("product", "team_id"),
    [
        ("Mortgage", "housing_loans"),
        ("Credit reporting or other personal consumer reports", "recoveries_crib"),
    ],
)
def test_product_maps_to_team(product, team_id):
    assert load_taxonomy().team_for_product(product).id == team_id


def test_excluded_product_has_no_team():
    assert load_taxonomy().team_for_product("Debt or credit management") is None


def test_unknown_product_raises():
    with pytest.raises(UnknownProductError):
        load_taxonomy().team_for_product("Brand new CFPB product")


def test_product_mapped_twice_rejected(raw_taxonomy):
    raw_taxonomy["teams"][1]["cfpb_products"].append("Mortgage")
    with pytest.raises(ValidationError, match="'Mortgage' is mapped to both"):
        Taxonomy.model_validate(raw_taxonomy)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("My Credit Report is wrong.", "My CRIB report is wrong."),
        ("The ACH transfer bounced.", "The SLIPS bounced."),
        ("I want to achieve a refund.", "I want to achieve a refund."),  # whole words only
    ],
)
def test_localize(text, expected):
    assert load_glossary().localize(text) == expected
