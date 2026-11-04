from datetime import date

import pytest

from smart_complaint_triage.config import load_sla_config
from smart_complaint_triage.sla import (
    HolidayDataMissingError,
    SlaCalculator,
    SlaStatus,
    WorkingDayCalendar,
)


@pytest.fixture(scope="module")
def calculator() -> SlaCalculator:
    return SlaCalculator.from_config()


@pytest.fixture(scope="module")
def calendar(calculator) -> WorkingDayCalendar:
    return calculator.calendar


@pytest.mark.parametrize(
    ("received", "ack_due"),
    [
        # Mon, ordinary week: Tue-Fri + Mon
        (date(2026, 6, 1), date(2026, 6, 8)),
        # Sat: counting starts on Monday
        (date(2026, 6, 6), date(2026, 6, 12)),
        # Fri before Poson Poya (Mon 29 Jun): skips the weekend and the holiday
        (date(2026, 6, 26), date(2026, 7, 6)),
        # Received on a holiday (Esala Poya)
        (date(2026, 7, 29), date(2026, 8, 5)),
        # Two holidays in a row (26 and 27 Aug)
        (date(2026, 8, 25), date(2026, 9, 3)),
    ],
)
def test_acknowledgement_due_date(calculator, received, ack_due):
    assert calculator.evaluate(received, as_of=received).acknowledgement.due_date == ack_due


def test_resolution_due_date_is_21_calendar_days(calculator):
    # 21 calendar days ignore weekends and holidays (Esala Poya on 29 Jul).
    sla = calculator.evaluate(date(2026, 7, 27), as_of=date(2026, 7, 27))
    assert sla.resolution.due_date == date(2026, 8, 17)


@pytest.mark.parametrize(
    ("as_of", "days_remaining", "status"),
    [
        (date(2026, 7, 16), 6, SlaStatus.ON_TRACK),
        (date(2026, 7, 17), 5, SlaStatus.DUE_SOON),
        (date(2026, 7, 22), 0, SlaStatus.DUE_SOON),  # due today
        (date(2026, 7, 23), -1, SlaStatus.OVERDUE),
    ],
)
def test_resolution_status(calculator, as_of, days_remaining, status):
    sla = calculator.evaluate(date(2026, 7, 1), as_of=as_of)
    assert sla.resolution.due_date == date(2026, 7, 22)
    assert sla.resolution.days_remaining == days_remaining
    assert sla.resolution.status == status
    assert sla.status == status


def test_acknowledgement_past_target_is_not_overdue(calculator):
    sla = calculator.evaluate(date(2026, 7, 1), as_of=date(2026, 7, 9))
    assert sla.acknowledgement.due_date == date(2026, 7, 8)
    assert sla.acknowledgement.status == SlaStatus.PAST_TARGET


def test_year_without_holiday_data_raises(calculator):
    # Counting from 28 Dec 2026 runs into 2027, which has no holiday data yet.
    with pytest.raises(HolidayDataMissingError, match="2027"):
        calculator.evaluate(date(2026, 12, 28), as_of=date(2026, 12, 28))


def test_csv_adds_years_and_extra_holidays(tmp_path):
    csv_path = tmp_path / "holidays.csv"
    csv_path.write_text('date,name\n2027-01-22,"Duruthu Full Moon Poya Day"\n')
    config = load_sla_config().calendar.model_copy(update={"fallback_csv": csv_path})
    calendar = WorkingDayCalendar.from_config(config, root=tmp_path)
    assert 2027 in calendar.covered_years
    assert calendar.is_holiday(date(2027, 1, 22))
    assert calendar.is_holiday(date(2026, 7, 29))  # still from the package
