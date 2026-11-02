"""Build ``complaints_clean`` from ``complaints_raw``.

Run with ``python -m smart_complaint_triage.clean`` (or ``make clean-data``).

Steps:
1. Remove complaints about the three US credit bureaus.
2. Map each CFPB product to its Sri Lankan bank team; drop excluded products.
3. Clean the narrative: whitespace, amounts, CFPB redactions, remaining PII.
4. Drop narratives with no usable text, then keep English complaints only.
5. Mark duplicate narratives.
6. Assign routing and escalation splits.
7. Save as ``complaints_clean`` in DuckDB and as Parquet.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd
from langdetect import DetectorFactory, LangDetectException, detect_langs

from smart_complaint_triage.config import (
    PROJECT_ROOT,
    CleaningConfig,
    LanguageConfig,
    Settings,
    Taxonomy,
    load_cleaning_config,
    load_settings,
    load_taxonomy,
)
from smart_complaint_triage.text import (
    clean_narrative,
    count_letters,
    duplicate_key,
    strip_tokens,
)


def detect_language(text: str, max_chars: int) -> tuple[str, float]:
    """Most likely language (ISO 639-1 code) and its probability, or ("unknown", 0)."""
    sample = strip_tokens(text)[:max_chars]
    try:
        best = detect_langs(sample)[0]
    except LangDetectException:  # no letters to detect from
        return "unknown", 0.0
    return best.lang, best.prob


def is_kept_language(lang: str, prob: float, letters: int, config: LanguageConfig) -> bool:
    """False only for text that is confidently, and with enough letters, not ``keep``."""
    confident = prob >= config.min_confidence and letters >= config.min_letters
    return lang == config.keep or not confident


def mark_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``narrative_duplicate_count`` and ``is_duplicate_narrative``.

    The earliest complaint (by date received, then ID) with a given narrative is the
    original; later ones are marked as duplicates. Rows are kept, not removed.
    """
    df = df.sort_values(["date_received", "complaint_id"]).reset_index(drop=True)
    key = df["narrative"].map(duplicate_key)
    df["narrative_duplicate_count"] = key.map(key.value_counts())
    df["is_duplicate_narrative"] = key.duplicated(keep="first")
    return df


def assign_splits(df: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    splits = settings.splits
    received = pd.to_datetime(df["date_received"]).dt.date
    df["routing_split"] = received.map(splits.routing.split_for)
    df["escalation_split"] = received.map(splits.escalation.split_for)
    return df


def clean(
    raw: pd.DataFrame, settings: Settings, taxonomy: Taxonomy, config: CleaningConfig
) -> tuple[pd.DataFrame, dict]:
    """Return the cleaned complaints and a report of row and mask counts."""
    DetectorFactory.seed = settings.random_seed  # langdetect is random without a seed
    report: dict = {"rows_in": len(raw)}

    df = raw[~raw["company"].isin(config.excluded_companies)].copy()
    report["removed_credit_bureaus"] = len(raw) - len(df)

    teams = df["product"].map(taxonomy.team_for_product)  # raises on unknown products
    report["removed_excluded_products"] = int(teams.isna().sum())
    df = df[teams.notna()].copy()
    teams = teams[teams.notna()]
    df["team_id"] = teams.map(lambda team: team.id)
    df["team_name"] = teams.map(lambda team: team.name)

    masks: Counter[str] = Counter()
    df["narrative"] = df["narrative"].map(lambda text: clean_narrative(text, masks))
    report["pii_masked"] = dict(sorted(masks.items()))

    letters = df["narrative"].map(lambda text: count_letters(strip_tokens(text)))
    usable = letters >= config.min_text_letters
    report["removed_no_usable_text"] = int((~usable).sum())
    df, letters = df[usable].copy(), letters[usable]

    detected = df["narrative"].map(lambda text: detect_language(text, config.language.max_chars))
    df["language"] = detected.map(lambda d: d[0])
    df["language_confidence"] = detected.map(lambda d: round(d[1], 3))
    kept = [
        is_kept_language(lang, prob, n, config.language)
        for (lang, prob), n in zip(detected, letters, strict=True)
    ]
    kept = pd.Series(kept, index=df.index)
    report["removed_non_english"] = df.loc[~kept, "language"].value_counts().to_dict()
    df = df[kept].copy()

    df = mark_duplicates(df)
    report["duplicate_narratives_marked"] = int(df["is_duplicate_narrative"].sum())

    df = assign_splits(df, settings)
    report["rows_out"] = len(df)
    report["rows_per_team"] = df["team_id"].value_counts().to_dict()
    for task in ("routing", "escalation"):
        counts = df[f"{task}_split"].value_counts(dropna=False)
        report[f"{task}_split_rows"] = {str(k): int(v) for k, v in counts.items()}
    return df, report


def run(root: Path = PROJECT_ROOT) -> dict:
    settings = load_settings()
    config = load_cleaning_config()
    duckdb_file = root / settings.paths.duckdb_file

    with duckdb.connect(str(duckdb_file)) as con:
        raw = con.execute(f'SELECT * FROM "{config.input_table}"').df()
        print(f"Cleaning {len(raw):,} complaints (language detection takes a few minutes)...")
        df, report = clean(raw, settings, load_taxonomy(), config)

        con.register("clean_df", df)
        con.execute(f'CREATE OR REPLACE TABLE "{config.output_table}" AS SELECT * FROM clean_df')
        con.unregister("clean_df")
        parquet = root / config.parquet_file
        parquet.parent.mkdir(parents=True, exist_ok=True)
        con.execute(f"COPY \"{config.output_table}\" TO '{parquet}' (FORMAT parquet)")

    report_path = root / config.report_file
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    run()
