from datetime import date

import pytest
import yaml
from pydantic import ValidationError

from smart_complaint_triage.config import (
    Settings,
    check_no_forbidden_features,
    config_dir,
    load_metrics,
    load_settings,
)


@pytest.fixture
def raw_settings() -> dict:
    with (config_dir() / "settings.yaml").open() as f:
        return yaml.safe_load(f)


def test_data_window():
    window = load_settings().data_window
    assert window.start == date(2026, 5, 15)
    assert window.end == date(2026, 8, 14)


def test_routing_splits():
    routing = load_settings().splits.routing
    assert (routing.train.start, routing.train.end) == (date(2026, 5, 15), date(2026, 6, 28))
    assert (routing.validation.start, routing.validation.end) == (
        date(2026, 6, 29),
        date(2026, 7, 12),
    )
    assert (routing.test.start, routing.test.end) == (date(2026, 7, 13), date(2026, 8, 14))


def test_escalation_splits():
    escalation = load_settings().splits.escalation
    assert escalation.label_cutoff == date(2026, 7, 12)
    assert (escalation.train.start, escalation.train.end) == (date(2026, 5, 15), date(2026, 6, 21))
    assert (escalation.validation.start, escalation.validation.end) == (
        date(2026, 6, 22),
        date(2026, 6, 28),
    )
    assert (escalation.test.start, escalation.test.end) == (date(2026, 6, 29), date(2026, 7, 12))


@pytest.mark.parametrize(
    ("day", "routing", "escalation"),
    [
        (date(2026, 5, 15), "train", "train"),
        (date(2026, 6, 22), "train", "validation"),
        (date(2026, 6, 29), "validation", "test"),
        (date(2026, 7, 12), "validation", "test"),
        (date(2026, 7, 13), "test", None),
        (date(2026, 8, 14), "test", None),
        (date(2026, 8, 15), None, None),
        (date(2026, 5, 14), None, None),
    ],
)
def test_split_for(day, routing, escalation):
    splits = load_settings().splits
    assert splits.routing.split_for(day) == routing
    assert splits.escalation.split_for(day) == escalation


def test_forbidden_features():
    assert set(load_settings().forbidden_features) == {
        "company_response",
        "timely_response",
        "company_public_response",
        "date_sent_to_company",
    }


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


def test_unknown_key_rejected(raw_settings):
    raw_settings["unexpected"] = 1
    with pytest.raises(ValidationError):
        Settings.model_validate(raw_settings)


def test_paths_resolve(tmp_path):
    paths = load_settings().paths.resolve(tmp_path)
    assert paths.duckdb_file == tmp_path / "data" / "complaints.duckdb"


def test_metrics_config():
    metrics = load_metrics()
    assert metrics.routing.auto_route_min_precision == 0.95
    assert metrics.escalation.primary_metric == "pr_auc"
    assert metrics.emerging_issues.baseline_weeks == 4
