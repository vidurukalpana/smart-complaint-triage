"""Load and validate the YAML settings in ``configs/``."""

from __future__ import annotations

import os
from datetime import date, timedelta
from functools import lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR_ENV = "SCT_CONFIG_DIR"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DateRange(_Model):
    """An inclusive date range."""

    start: date
    end: date

    @model_validator(mode="after")
    def _check_order(self) -> DateRange:
        if self.start > self.end:
            raise ValueError(f"start {self.start} is after end {self.end}")
        return self

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


SplitName = Literal["train", "validation", "test"]


class Splits(_Model):
    """Train, validation and test ranges that follow each other with no gaps or overlaps."""

    train: DateRange
    validation: DateRange
    test: DateRange

    @model_validator(mode="after")
    def _check_contiguous(self) -> Splits:
        ranges = [("train", self.train), ("validation", self.validation), ("test", self.test)]
        for (prev_name, prev), (name, cur) in pairwise(ranges):
            if cur.start != prev.end + timedelta(days=1):
                raise ValueError(
                    f"{name} must start the day after {prev_name} ends "
                    f"({prev.end + timedelta(days=1)}), got {cur.start}"
                )
        return self

    @property
    def span(self) -> DateRange:
        return DateRange(start=self.train.start, end=self.test.end)

    def split_for(self, day: date) -> SplitName | None:
        """Return the split a complaint received on ``day`` belongs to, or None."""
        for name in ("train", "validation", "test"):
            if getattr(self, name).contains(day):
                return name
        return None


class EscalationSplits(Splits):
    label_cutoff: date

    @model_validator(mode="after")
    def _check_cutoff(self) -> EscalationSplits:
        if self.test.end > self.label_cutoff:
            raise ValueError(
                f"escalation test ends {self.test.end}, after label_cutoff {self.label_cutoff}"
            )
        return self


class AllSplits(_Model):
    routing: Splits
    escalation: EscalationSplits


class Paths(_Model):
    data_dir: Path
    raw_dir: Path
    processed_dir: Path
    duckdb_file: Path
    models_dir: Path
    reports_dir: Path
    mlruns_dir: Path

    def resolve(self, root: Path) -> Paths:
        """Return a copy with every relative path made absolute under ``root``."""
        return Paths(**{name: root / value for name, value in self})


class Settings(_Model):
    random_seed: int
    paths: Paths
    data_window: DateRange
    splits: AllSplits
    forbidden_features: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_splits_in_window(self) -> Settings:
        for task in ("routing", "escalation"):
            span = getattr(self.splits, task).span
            if span.start < self.data_window.start or span.end > self.data_window.end:
                raise ValueError(f"{task} splits {span.start}..{span.end} fall outside data_window")
        return self


class RoutingMetrics(_Model):
    primary_metric: str
    auto_route_min_precision: float = Field(gt=0, le=1)
    llm_sample_size: int = Field(gt=0)


class EscalationMetrics(_Model):
    primary_metric: str
    calibration_bins: int = Field(gt=1)
    top_k: tuple[int, ...] = Field(min_length=1)


class EmergingIssueMetrics(_Model):
    baseline_weeks: int = Field(gt=0)


class SummaryMetrics(_Model):
    labelled_sample_size: int = Field(gt=0)


class MetricsConfig(_Model):
    routing: RoutingMetrics
    escalation: EscalationMetrics
    emerging_issues: EmergingIssueMetrics
    summaries: SummaryMetrics


def config_dir() -> Path:
    """Directory holding the YAML files; override with the SCT_CONFIG_DIR env var."""
    return Path(os.environ.get(CONFIG_DIR_ENV, PROJECT_ROOT / "configs"))


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


@lru_cache
def load_settings(path: Path | None = None) -> Settings:
    return Settings.model_validate(_read_yaml(path or config_dir() / "settings.yaml"))


@lru_cache
def load_metrics(path: Path | None = None) -> MetricsConfig:
    return MetricsConfig.model_validate(_read_yaml(path or config_dir() / "metrics.yaml"))


def check_no_forbidden_features(columns: list[str], settings: Settings | None = None) -> None:
    """Raise if any model input column is a forbidden (leaky) field."""
    forbidden = set((settings or load_settings()).forbidden_features)
    leaked = sorted(forbidden.intersection(columns))
    if leaked:
        raise ValueError(f"Forbidden fields used as model inputs: {leaked}")
