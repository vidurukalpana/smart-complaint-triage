from datetime import date

import duckdb
import pytest

from smart_complaint_triage.config import load_taxonomy
from smart_complaint_triage.eda import QUERIES, unmapped_products

COLUMNS = (
    "date_received DATE, team_name VARCHAR, issue VARCHAR, company VARCHAR, narrative VARCHAR, "
    "company_response VARCHAR, timely_response VARCHAR, submitted_via VARCHAR, "
    "is_duplicate_narrative BOOLEAN, narrative_duplicate_count BIGINT, "
    "routing_split VARCHAR, escalation_split VARCHAR, product VARCHAR"
)
RELIEF = "Closed with monetary relief"
EXPLANATION = "Closed with explanation"


def complaint(day, team, response=EXPLANATION, timely="Yes", duplicate=False, product="Mortgage"):
    return (
        day, team, "Fees", "A BANK", "one two three", response, timely, "Web",
        duplicate, 2 if duplicate else 1, "train", "train", product,
    )  # fmt: skip


@pytest.fixture
def con():
    connection = duckdb.connect()
    connection.execute(f"CREATE TABLE complaints_clean ({COLUMNS})")
    rows = [
        complaint(date(2026, 6, 1), "Cards", response=RELIEF),  # Monday
        complaint(date(2026, 6, 7), "Cards", timely="No"),  # Sunday of the same week
        complaint(date(2026, 6, 8), "Cards", response="In progress", duplicate=True),
        complaint(date(2026, 6, 8), "Housing Loans", product="Unknown product"),
    ]
    connection.executemany(f"INSERT INTO complaints_clean VALUES ({','.join('?' * 13)})", rows)
    yield connection
    connection.close()


@pytest.mark.parametrize("name", QUERIES)
def test_every_query_runs(con, name):
    assert con.execute(QUERIES[name]).fetchall()


def test_weekly_outcomes_group_monday_to_sunday(con):
    rows = con.execute(QUERIES["weekly_outcomes"]).fetchall()
    assert rows == [
        (date(2026, 6, 1), 2, 50.0, 50.0, 0, 0.0),
        (date(2026, 6, 8), 2, 0.0, 0.0, 1, 50.0),
    ]


def test_unmapped_products(con):
    assert unmapped_products(con, "complaints_clean", load_taxonomy()) == ["Unknown product"]
