import csv
import zipfile
from datetime import date

import pytest

from smart_complaint_triage.config import (
    DateRange,
    IngestConfig,
    load_ingest_config,
    load_settings,
)
from smart_complaint_triage.ingest import extract_csv, load_duckdb

pyspark = pytest.importorskip("pyspark")

from smart_complaint_triage.ingest import (  # noqa: E402
    filter_and_dedupe,
    read_complaints,
    spark_session,
    write_parquet,
)

WINDOW = DateRange(start=date(2026, 5, 15), end=date(2026, 8, 14))


def row(config: IngestConfig, **values) -> dict:
    """A CSV row with every CFPB header; ``values`` are given by our column names."""
    by_name = {name: "" for name in config.columns.values()}
    by_name.update(values)
    return {header: by_name[name] for header, name in config.columns.items()}


@pytest.fixture(scope="module")
def config() -> IngestConfig:
    return load_ingest_config()


@pytest.fixture(scope="module")
def spark(config):
    session = spark_session(
        config.model_copy(update={"spark": config.spark.model_copy(update={"master": "local[1]"})})
    )
    yield session
    session.stop()


@pytest.fixture(scope="module")
def sample_csv(tmp_path_factory, config):
    narrative = 'I sent $500.\nThe bank said "processing", then nothing,\nfor weeks.'
    rows = [
        row(config, complaint_id="1", date_received="2026-05-15", narrative=narrative),
        row(config, complaint_id="2", date_received="2026-08-14", narrative="Card fee."),
        row(config, complaint_id="3", date_received="2026-05-14", narrative="Too early."),
        row(config, complaint_id="4", date_received="2026-08-15", narrative="Too late."),
        row(config, complaint_id="5", date_received="2026-06-01", narrative=""),
        row(config, complaint_id="6", date_received="2026-06-01", narrative="   "),
        # exact duplicate of complaint 2
        row(config, complaint_id="2", date_received="2026-08-14", narrative="Card fee."),
        # same ID as complaint 7 below, but a different company response
        row(config, complaint_id="7", date_received="2026-07-01", narrative="Loan.",
            company_response="Closed with explanation"),
        row(config, complaint_id="7", date_received="2026-07-01", narrative="Loan.",
            company_response="In progress"),
    ]  # fmt: skip
    path = tmp_path_factory.mktemp("csv") / "complaints.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(config.columns))
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture(scope="module")
def result(spark, sample_csv, config):
    kept, stats = filter_and_dedupe(read_complaints(spark, [sample_csv], config), WINDOW)
    return kept, stats


def test_multiline_narrative_with_quotes_read_intact(result):
    kept, _ = result
    narrative = kept.filter("complaint_id = 1").first()["narrative"]
    assert narrative == 'I sent $500.\nThe bank said "processing", then nothing,\nfor weeks.'


def test_keeps_window_with_narrative_one_row_per_id(result):
    kept, _ = result
    assert sorted(r["complaint_id"] for r in kept.collect()) == [1, 2, 7]


def test_stats(result):
    _, stats = result
    assert stats.rows_in_window == 7  # ids 3 and 4 are outside the window
    assert stats.rows_without_narrative == 2
    assert stats.exact_duplicates_removed == 1
    assert stats.conflicting_duplicates_removed == 1
    assert stats.rows_kept == 3


def test_types_and_column_names(result, config):
    kept, _ = result
    assert kept.columns == list(config.columns.values())
    types = dict(kept.dtypes)
    assert types["complaint_id"] == "bigint"
    assert types["date_received"] == "date"


def test_missing_csv_column_raises(spark, tmp_path, config):
    path = tmp_path / "bad.csv"
    path.write_text("Complaint ID,Date received\n1,2026-06-01\n")
    with pytest.raises(ValueError, match="missing expected columns"):
        read_complaints(spark, [path], config)


def test_parquet_to_duckdb(result, tmp_path):
    kept, stats = result
    parquet_dir = tmp_path / "complaints_raw.parquet"
    write_parquet(kept, parquet_dir)
    rows = load_duckdb(parquet_dir, tmp_path / "test.duckdb", "complaints_raw")
    assert rows == stats.rows_kept


def test_extract_csv(tmp_path):
    zip_path = tmp_path / "complaints.csv.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("complaints.csv", "a,b\n1,2\n")
    extract_csv(zip_path, tmp_path / "out.csv")
    assert (tmp_path / "out.csv").read_text() == "a,b\n1,2\n"


def test_forbidden_features_are_mapped_columns(config):
    assert set(load_settings().forbidden_features) <= set(config.columns.values())
