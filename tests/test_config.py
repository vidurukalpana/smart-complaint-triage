from datetime import date

import pytest
import yaml
from pydantic import ValidationError

from smart_complaint_triage.config import (
    Settings,
    check_no_forbidden_features,
    config_dir,
    load_settings,
)


@pytest.fixture
def raw_settings() -> dict:
    with (config_dir() / "settings.yaml").open() as f:
        return yaml.safe_load(f)


@pytest.mark.parametrize(
    ("day", "routing", "escalation"),
    [
        (date(2026, 5, 15), "train", "train"),
        (date(2026, 7, 12), "validation", "test"),
        (date(2026, 7, 13), "test", None),
        (date(2026, 8, 15), None, None),
    ],
)
def test_split_for(day, routing, escalation):
    splits = load_settings().splits
    assert splits.routing.split_for(day) == routing
    assert splits.escalation.split_for(day) == escalation


def test_check_no_forbidden_features():
    check_no_forbidden_features(["narrative", "product", "issue"])
    with pytest.raises(ValueError, match="timely_response"):
        check_no_forbidden_features(["narrative", "timely_response"])


def test_overlapping_splits_rejected(raw_settings):
    raw_settings["splits"]["routing"]["validation"]["start"] = date(2026, 6, 28)
    with pytest.raises(ValidationError, match="validation must start the day after train"):
        Settings.model_validate(raw_settings)


def test_gap_between_splits_rejected(raw_settings):
    raw_settings["splits"]["routing"]["test"]["start"] = date(2026, 7, 28)
    with pytest.raises(ValidationError, match="test must start the day after validation"):
        Settings.model_validate(raw_settings)


def test_escalation_test_after_cutoff_rejected(raw_settings):
    raw_settings["splits"]["escalation"]["test"]["end"] = date(2026, 7, 13)
    with pytest.raises(ValidationError, match="after label_cutoff"):
        Settings.model_validate(raw_settings)


def test_splits_outside_window_rejected(raw_settings):
    raw_settings["splits"]["routing"]["test"]["end"] = date(2026, 8, 20)
    with pytest.raises(ValidationError, match="outside data_window"):
        Settings.model_validate(raw_settings)
