"""Load and validate the YAML settings in ``configs/``."""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from functools import cached_property, lru_cache
from itertools import pairwise
from pathlib import Path
from typing import Literal, get_args

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


class Team(_Model):
    id: str
    name: str
    description: str
    cfpb_products: tuple[str, ...] = Field(min_length=1)


class Queue(_Model):
    id: str
    name: str


class NotCoveredService(_Model):
    name: str
    reason: str


class UnknownProductError(KeyError):
    """A CFPB product that is neither mapped to a team nor explicitly excluded."""


class Taxonomy(_Model):
    teams: tuple[Team, ...] = Field(min_length=1)
    triage_queue: Queue
    excluded_cfpb_products: tuple[str, ...] = ()
    not_covered: tuple[NotCoveredService, ...] = ()

    @model_validator(mode="after")
    def _check_unique(self) -> Taxonomy:
        ids = [team.id for team in self.teams] + [self.triage_queue.id]
        if len(ids) != len(set(ids)):
            raise ValueError(f"team and queue ids must be unique: {ids}")
        seen: dict[str, str] = {}
        for team in self.teams:
            for product in team.cfpb_products:
                if product in seen:
                    raise ValueError(f"{product!r} is mapped to both {seen[product]} and {team.id}")
                seen[product] = team.id
        both = sorted(set(seen).intersection(self.excluded_cfpb_products))
        if both:
            raise ValueError(f"products both mapped and excluded: {both}")
        return self

    @cached_property
    def _product_to_team(self) -> dict[str, Team]:
        return {product: team for team in self.teams for product in team.cfpb_products}

    @property
    def team_ids(self) -> tuple[str, ...]:
        return tuple(team.id for team in self.teams)

    def team(self, team_id: str) -> Team:
        for team in self.teams:
            if team.id == team_id:
                return team
        raise KeyError(team_id)

    def team_for_product(self, product: str) -> Team | None:
        """Return the team for a CFPB product, or None if the product is excluded.

        Raises UnknownProductError for products that are in neither list, so new
        CFPB product names are noticed instead of silently dropped.
        """
        if product in self._product_to_team:
            return self._product_to_team[product]
        if product in self.excluded_cfpb_products:
            return None
        raise UnknownProductError(product)


Weekday = Literal["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAYS: tuple[Weekday, ...] = get_args(Weekday)


class Deadline(_Model):
    days: int = Field(gt=0)
    day_type: Literal["working", "calendar"]
    due_soon_days: int = Field(ge=0)
    # True for a legal limit, False for a recommended target.
    binding: bool
    regulation: str


class Deadlines(_Model):
    acknowledgement: Deadline
    resolution: Deadline


class CalendarConfig(_Model):
    country: str
    weekend_days: tuple[Weekday, ...]
    holiday_categories: tuple[str, ...] = Field(min_length=1)
    fallback_csv: Path

    @property
    def weekend_numbers(self) -> frozenset[int]:
        """Weekend days as ``date.weekday()`` numbers (Monday = 0)."""
        return frozenset(WEEKDAYS.index(day) for day in self.weekend_days)


class SlaConfig(_Model):
    deadlines: Deadlines
    calendar: CalendarConfig


class GlossaryTerm(_Model):
    us: tuple[str, ...] = Field(min_length=1)
    sri_lanka: str


class Glossary(_Model):
    terms: tuple[GlossaryTerm, ...]

    @model_validator(mode="after")
    def _check_unique(self) -> Glossary:
        us_terms = [us.lower() for term in self.terms for us in term.us]
        duplicates = sorted({us for us in us_terms if us_terms.count(us) > 1})
        if duplicates:
            raise ValueError(f"US terms listed more than once: {duplicates}")
        return self

    @cached_property
    def _lookup(self) -> dict[str, str]:
        return {us.lower(): term.sri_lanka for term in self.terms for us in term.us}

    @cached_property
    def _pattern(self) -> re.Pattern[str]:
        # Longest first, so "ACH transfer" is matched before "ACH".
        alternatives = sorted(self._lookup, key=len, reverse=True)
        return re.compile(r"\b(?:" + "|".join(map(re.escape, alternatives)) + r")\b", re.IGNORECASE)

    def localize(self, text: str) -> str:
        """Replace US banking terms in ``text`` with their Sri Lankan equivalents."""
        if not self.terms:
            return text
        return self._pattern.sub(lambda m: self._lookup[m.group(0).lower()], text)


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


@lru_cache
def load_taxonomy(path: Path | None = None) -> Taxonomy:
    return Taxonomy.model_validate(_read_yaml(path or config_dir() / "taxonomy.yaml"))


@lru_cache
def load_sla_config(path: Path | None = None) -> SlaConfig:
    return SlaConfig.model_validate(_read_yaml(path or config_dir() / "sla.yaml"))


@lru_cache
def load_glossary(path: Path | None = None) -> Glossary:
    return Glossary.model_validate(_read_yaml(path or config_dir() / "glossary.yaml"))


def check_no_forbidden_features(columns: list[str], settings: Settings | None = None) -> None:
    """Raise if any model input column is a forbidden (leaky) field."""
    forbidden = set((settings or load_settings()).forbidden_features)
    leaked = sorted(forbidden.intersection(columns))
    if leaked:
        raise ValueError(f"Forbidden fields used as model inputs: {leaked}")
