"""Download the CFPB narratives archive, keep the data window, and load it into DuckDB.

Run with ``python -m smart_complaint_triage.ingest`` (or ``make ingest``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

from smart_complaint_triage.config import (
    PROJECT_ROOT,
    DateRange,
    IngestConfig,
    load_ingest_config,
    load_settings,
)

if TYPE_CHECKING:
    from pyspark.sql import DataFrame, SparkSession

CHUNK_SIZE = 1024 * 1024


def download(url: str, zip_path: Path) -> dict:
    """Download ``url`` to ``zip_path``; return its manifest entry (size and checksum)."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    partial = zip_path.with_suffix(zip_path.suffix + ".part")
    sha256 = hashlib.sha256()
    with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as out:
        headers = dict(response.headers)
        total = int(headers.get("Content-Length", 0))
        done = 0
        while chunk := response.read(CHUNK_SIZE):
            out.write(chunk)
            sha256.update(chunk)
            done += len(chunk)
            if total:
                print(f"\r{zip_path.name}: {done / 1e6:,.0f} / {total / 1e6:,.0f} MB", end="")
    print()
    partial.replace(zip_path)
    return {
        "url": url,
        "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "last_modified": headers.get("Last-Modified"),
        "bytes": done,
        "sha256": sha256.hexdigest(),
    }


def extract_csv(zip_path: Path, csv_path: Path) -> None:
    """Unzip the single CSV inside ``zip_path`` to ``csv_path``."""
    with zipfile.ZipFile(zip_path) as archive:
        members = [m for m in archive.namelist() if m.endswith(".csv")]
        if len(members) != 1:
            raise ValueError(f"expected one CSV in {zip_path}, found {members}")
        with archive.open(members[0]) as src, csv_path.open("wb") as dst:
            shutil.copyfileobj(src, dst, CHUNK_SIZE)


def spark_session(config: IngestConfig) -> SparkSession:
    from pyspark.sql import SparkSession

    spark = (
        SparkSession.builder.master(config.spark.master)
        .appName("smart-complaint-triage-ingest")
        .config("spark.driver.memory", config.spark.driver_memory)
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    return spark


def read_complaints(spark: SparkSession, csv_paths: list[Path], config: IngestConfig) -> DataFrame:
    """Read the CFPB CSVs, keep and rename the mapped columns, and parse types."""
    from pyspark.sql import functions as F

    raw = (
        spark.read.option("header", True)
        .option("multiLine", True)  # narratives contain line breaks
        .option("quote", '"')
        .option("escape", '"')  # quotes inside narratives are doubled ("")
        .option("inferSchema", False)
        .csv([str(p) for p in csv_paths])
    )
    missing = sorted(set(config.columns) - set(raw.columns))
    if missing:
        raise ValueError(f"CSV is missing expected columns: {missing}")

    df = raw.select([F.col(f"`{header}`").alias(name) for header, name in config.columns.items()])
    for name in config.date_columns:
        df = df.withColumn(name, F.to_date(name, config.date_format))
    return df.withColumn("complaint_id", F.col("complaint_id").cast("long"))


@dataclass
class IngestStats:
    rows_in_window: int = 0
    rows_without_narrative: int = 0
    exact_duplicates_removed: int = 0
    conflicting_duplicates_removed: int = 0
    rows_kept: int = 0


def filter_and_dedupe(df: DataFrame, window: DateRange) -> tuple[DataFrame, IngestStats]:
    """Keep complaints in ``window`` with a narrative, one row per complaint ID."""
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    stats = IngestStats()
    in_window = df.filter(F.col("date_received").between(window.start, window.end)).persist()
    stats.rows_in_window = in_window.count()

    has_narrative = F.col("narrative").isNotNull() & (F.trim("narrative") != "")
    with_narrative = in_window.filter(has_narrative)
    narrative_rows = with_narrative.count()
    stats.rows_without_narrative = stats.rows_in_window - narrative_rows

    distinct = with_narrative.dropDuplicates()
    distinct_rows = distinct.count()
    stats.exact_duplicates_removed = narrative_rows - distinct_rows

    # Rows sharing an ID but differing in some field: keep one, chosen deterministically.
    order = [F.col(c).asc_nulls_last() for c in sorted(distinct.columns)]
    ranked = distinct.withColumn(
        "_rank", F.row_number().over(Window.partitionBy("complaint_id").orderBy(*order))
    )
    kept = ranked.filter(F.col("_rank") == 1).drop("_rank").persist()
    stats.rows_kept = kept.count()
    stats.conflicting_duplicates_removed = distinct_rows - stats.rows_kept

    in_window.unpersist()
    return kept, stats


def write_parquet(df: DataFrame, parquet_dir: Path) -> None:
    df.orderBy("date_received", "complaint_id").coalesce(1).write.mode("overwrite").parquet(
        str(parquet_dir)
    )


def load_duckdb(parquet_dir: Path, duckdb_file: Path, table: str) -> int:
    """Replace ``table`` in ``duckdb_file`` with the Parquet data; return its row count."""
    duckdb_file.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(duckdb_file)) as con:
        con.execute(
            f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM read_parquet(?)',
            [str(parquet_dir / "*.parquet")],
        )
        return con.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]


def run(force_download: bool = False, root: Path = PROJECT_ROOT) -> IngestStats:
    settings = load_settings()
    config = load_ingest_config()
    raw_dir = root / config.raw_dir
    manifest_path = root / config.manifest_file
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}

    csv_paths = []
    for name in config.files:
        zip_path = raw_dir / name
        if force_download or not zip_path.exists():
            manifest[name] = download(config.base_url + name, zip_path)
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        else:
            print(f"Using existing {zip_path.name}")
        csv_path = zip_path.with_suffix(".csv")
        if not csv_path.exists():
            print(f"Unzipping {zip_path.name}...")
            extract_csv(zip_path, csv_path)
        csv_paths.append(csv_path)

    print("Reading and filtering with Spark...")
    spark = spark_session(config)
    try:
        df = read_complaints(spark, csv_paths, config)
        kept, stats = filter_and_dedupe(df, settings.data_window)
        write_parquet(kept, root / config.parquet_dir)
    finally:
        spark.stop()

    rows = load_duckdb(
        root / config.parquet_dir, root / settings.paths.duckdb_file, config.duckdb_table
    )
    if rows != stats.rows_kept:
        raise RuntimeError(f"DuckDB has {rows} rows, expected {stats.rows_kept}")

    report = {
        "data_window": settings.data_window.model_dump(mode="json"),
        "source_files": manifest,
        **asdict(stats),
    }
    report_path = root / config.report_file
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")

    if config.delete_downloads:
        for name in config.files:
            (raw_dir / name).unlink(missing_ok=True)
            (raw_dir / name).with_suffix(".csv").unlink(missing_ok=True)
        print("Deleted the downloaded ZIPs and CSVs; only the data window is kept.")

    print(json.dumps(asdict(stats), indent=2))
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--force-download", action="store_true", help="download again even if the ZIPs exist"
    )
    args = parser.parse_args()
    run(force_download=args.force_download)


if __name__ == "__main__":
    main()
