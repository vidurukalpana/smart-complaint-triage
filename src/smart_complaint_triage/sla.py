"""Central Bank complaint deadlines, counted on a Sri Lankan working-day calendar."""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path

import holidays

from smart_complaint_triage.config import (
    PROJECT_ROOT,
    CalendarConfig,
    Deadline,
    SlaConfig,
    load_sla_config,
)


class HolidayDataMissingError(LookupError):
    """No holiday data exists for a year, so working days cannot be counted safely."""


class WorkingDayCalendar:
    """Weekends and holidays for the years that have holiday data."""

    def __init__(
        self,
        holiday_dates: Mapping[date, str],
        weekend_days: Iterable[int],
        covered_years: Iterable[int],
    ) -> None:
        self.holidays = dict(holiday_dates)
        self.weekend_days = frozenset(weekend_days)
        self.covered_years = frozenset(covered_years)

    @classmethod
    def from_config(cls, config: CalendarConfig, root: Path = PROJECT_ROOT) -> WorkingDayCalendar:
        """Combine the `holidays` package with the CSV, which adds years and extra holidays."""
        package = holidays.country_holidays(config.country, categories=config.holiday_categories)
        package_years = range(package.start_year, package.end_year + 1)
        holiday_dates = dict(
            holidays.country_holidays(
                config.country, years=package_years, categories=config.holiday_categories
            )
        )
        csv_dates = read_holiday_csv(root / config.fallback_csv)
        holiday_dates.update(csv_dates)
        return cls(
            holiday_dates,
            weekend_days=config.weekend_numbers,
            covered_years=set(package_years) | {day.year for day in csv_dates},
        )

    def is_holiday(self, day: date) -> bool:
        self._check_covered(day)
        return day in self.holidays

    def is_working_day(self, day: date) -> bool:
        self._check_covered(day)
        return day.weekday() not in self.weekend_days and day not in self.holidays

    def add_working_days(self, start: date, days: int) -> date:
        """Return the date ``days`` working days after ``start`` (``start`` itself is day 0)."""
        current = start
        counted = 0
        while counted < days:
            current += timedelta(days=1)
            if self.is_working_day(current):
                counted += 1
        return current

    def _check_covered(self, day: date) -> None:
        if day.year not in self.covered_years:
            raise HolidayDataMissingError(
                f"No holiday data for {day.year}; add that year's holidays to the CSV"
            )


def read_holiday_csv(path: Path) -> dict[date, str]:
    with path.open(encoding="utf-8", newline="") as f:
        return {date.fromisoformat(row["date"]): row["name"] for row in csv.DictReader(f)}


class SlaStatus(StrEnum):
    ON_TRACK = "on track"
    DUE_SOON = "due soon"
    OVERDUE = "overdue"  # a legal deadline has passed
    PAST_TARGET = "past recommended time"  # a recommended target has passed


@dataclass(frozen=True)
class DeadlineStatus:
    due_date: date
    days_remaining: int  # calendar days; negative once overdue
    status: SlaStatus


@dataclass(frozen=True)
class ComplaintSla:
    received: date
    as_of: date
    acknowledgement: DeadlineStatus
    resolution: DeadlineStatus

    @property
    def status(self) -> SlaStatus:
        """Overall status, taken from the 21-day resolution deadline.

        The data does not record when a complaint was acknowledged, so the
        acknowledgement status is reported separately instead of being combined here.
        """
        return self.resolution.status


class SlaCalculator:
    """Due dates, days remaining and status for the acknowledgement and resolution deadlines."""

    def __init__(self, config: SlaConfig, calendar: WorkingDayCalendar) -> None:
        self.config = config
        self.calendar = calendar

    @classmethod
    def from_config(cls, config: SlaConfig | None = None) -> SlaCalculator:
        config = config or load_sla_config()
        return cls(config, WorkingDayCalendar.from_config(config.calendar))

    def due_date(self, received: date, deadline: Deadline) -> date:
        if deadline.day_type == "working":
            return self.calendar.add_working_days(received, deadline.days)
        return received + timedelta(days=deadline.days)

    def evaluate(self, received: date, as_of: date) -> ComplaintSla:
        """SLA position on ``as_of`` of a complaint received on ``received``."""
        if as_of < received:
            raise ValueError(f"as_of {as_of} is before received {received}")
        deadlines = self.config.deadlines
        return ComplaintSla(
            received=received,
            as_of=as_of,
            acknowledgement=self._deadline_status(received, as_of, deadlines.acknowledgement),
            resolution=self._deadline_status(received, as_of, deadlines.resolution),
        )

    def _deadline_status(self, received: date, as_of: date, deadline: Deadline) -> DeadlineStatus:
        due = self.due_date(received, deadline)
        remaining = (due - as_of).days
        if remaining < 0:
            status = SlaStatus.OVERDUE if deadline.binding else SlaStatus.PAST_TARGET
        elif remaining <= deadline.due_soon_days:
            status = SlaStatus.DUE_SOON
        else:
            status = SlaStatus.ON_TRACK
        return DeadlineStatus(due_date=due, days_remaining=remaining, status=status)
