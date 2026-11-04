"""Exploratory data analysis of the complaints, as SQL queries on DuckDB.

Run with ``python -m smart_complaint_triage.eda`` (or ``make eda``). Each query's result is
saved as a CSV in ``reports/eda/``. The findings are written up in ``docs/eda_summary.md``.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from smart_complaint_triage.config import (
    PROJECT_ROOT,
    Taxonomy,
    UnknownProductError,
    load_cleaning_config,
    load_ingest_config,
    load_settings,
    load_taxonomy,
)

RELIEF = "company_response = 'Closed with monetary relief'"
LATE = "timely_response = 'No'"
IN_PROGRESS = "company_response = 'In progress'"

# Weeks start on Monday. Rates are percentages.
QUERIES = {
    "weekly_volume_per_team": """
        SELECT date_trunc('week', date_received)::DATE AS week, team_name, count(*) AS complaints
        FROM complaints_clean
        GROUP BY ALL
        ORDER BY week, complaints DESC
    """,
    "daily_volume": """
        SELECT date_received::DATE AS day, dayname(date_received) AS weekday,
               count(*) AS complaints
        FROM complaints_clean
        GROUP BY ALL
        ORDER BY day
    """,
    "top_issues": f"""
        SELECT team_name, issue, complaints, rank_in_team, relief_pct, late_pct
        FROM (
            SELECT team_name, issue, count(*) AS complaints,
                   round(100.0 * avg(({RELIEF})::INT), 1) AS relief_pct,
                   round(100.0 * avg(({LATE})::INT), 1) AS late_pct,
                   row_number() OVER (PARTITION BY team_name ORDER BY count(*) DESC, issue)
                       AS rank_in_team
            FROM complaints_clean
            GROUP BY team_name, issue
        )
        WHERE rank_in_team <= 5
        ORDER BY team_name, rank_in_team
    """,
    "outcomes_per_team": f"""
        SELECT team_name, count(*) AS complaints,
               round(100.0 * avg(({RELIEF})::INT), 1) AS relief_pct,
               round(100.0 * avg(({LATE})::INT), 1) AS late_pct
        FROM complaints_clean
        GROUP BY ALL
        ORDER BY complaints DESC
    """,
    "weekly_outcomes": f"""
        SELECT date_trunc('week', date_received)::DATE AS week, count(*) AS complaints,
               round(100.0 * avg(({RELIEF})::INT), 1) AS relief_pct,
               round(100.0 * avg(({LATE})::INT), 1) AS late_pct,
               sum(({IN_PROGRESS})::INT) AS in_progress,
               round(100.0 * avg(({IN_PROGRESS})::INT), 2) AS in_progress_pct
        FROM complaints_clean
        GROUP BY ALL
        ORDER BY week
    """,
    "late_by_company": f"""
        SELECT company, team_name, count(*) AS complaints, sum(({LATE})::INT) AS late,
               round(100.0 * avg(({LATE})::INT), 1) AS late_pct
        FROM complaints_clean
        GROUP BY ALL
        ORDER BY late DESC
        LIMIT 15
    """,
    "narrative_lengths": """
        SELECT team_name, count(*) AS complaints,
               quantile_cont(words, 0.5) AS median_words,
               quantile_cont(words, 0.9) AS p90_words,
               max(words) AS max_words,
               round(100.0 * avg((words > 512)::INT), 1) AS over_512_words_pct
        FROM (
            SELECT team_name, len(string_split(narrative, ' ')) AS words
            FROM complaints_clean
        )
        GROUP BY ALL
        ORDER BY complaints DESC
    """,
    "routing_split_teams": """
        SELECT routing_split, team_name, count(*) AS complaints,
               sum((NOT is_duplicate_narrative)::INT) AS without_duplicates
        FROM complaints_clean
        GROUP BY ALL
        ORDER BY routing_split, complaints DESC
    """,
    "escalation_splits": f"""
        SELECT escalation_split, count(*) AS complaints,
               sum((NOT is_duplicate_narrative)::INT) AS without_duplicates,
               sum(({RELIEF})::INT) AS relief, round(100.0 * avg(({RELIEF})::INT), 1) AS relief_pct,
               sum(({LATE})::INT) AS late, round(100.0 * avg(({LATE})::INT), 1) AS late_pct
        FROM complaints_clean
        GROUP BY ALL
        ORDER BY escalation_split
    """,
    "duplicate_narratives": """
        SELECT team_name, count(*) AS complaints,
               sum(is_duplicate_narrative::INT) AS duplicates,
               round(100.0 * avg(is_duplicate_narrative::INT), 1) AS duplicates_pct,
               max(narrative_duplicate_count) AS largest_group
        FROM complaints_clean
        GROUP BY ALL
        ORDER BY duplicates DESC
    """,
    "submission_channels": """
        SELECT submitted_via, count(*) AS complaints
        FROM complaints_clean
        GROUP BY ALL
        ORDER BY complaints DESC
    """,
}


def unmapped_products(con: duckdb.DuckDBPyConnection, table: str, taxonomy: Taxonomy) -> list[str]:
    """CFPB products in ``table`` that are neither mapped to a team nor excluded."""
    products = [row[0] for row in con.execute(f'SELECT DISTINCT product FROM "{table}"').fetchall()]
    unmapped = []
    for product in products:
        try:
            taxonomy.team_for_product(product)
        except UnknownProductError:
            unmapped.append(product)
    return sorted(unmapped)


def small_teams(con: duckdb.DuckDBPyConnection, minimum: int) -> dict[str, int]:
    """Teams in ``complaints_clean`` with fewer than ``minimum`` complaints."""
    rows = con.execute(
        "SELECT team_name, count(*) FROM complaints_clean GROUP BY ALL HAVING count(*) < ?",
        [minimum],
    ).fetchall()
    return dict(rows)


def run(root: Path = PROJECT_ROOT) -> None:
    settings = load_settings()
    taxonomy = load_taxonomy()
    out_dir = root / settings.paths.reports_dir / "eda"
    out_dir.mkdir(parents=True, exist_ok=True)

    with duckdb.connect(str(root / settings.paths.duckdb_file), read_only=True) as con:
        for name, sql in QUERIES.items():
            result = con.execute(sql).df()
            result.to_csv(out_dir / f"{name}.csv", index=False)
            print(f"\n== {name} ==\n{result.head(15).to_string(index=False)}")

        unmapped = unmapped_products(con, load_ingest_config().duckdb_table, taxonomy)
        small = small_teams(con, taxonomy.min_team_complaints)

    print(f"\nProducts not mapped to a team: {unmapped or 'none'}")
    print(f"Teams under {taxonomy.min_team_complaints} complaints: {small or 'none'}")
    print(f"\nSaved to {out_dir}; cleaned table: {load_cleaning_config().output_table}")
    if unmapped:
        raise SystemExit(f"Add these products to configs/taxonomy.yaml: {unmapped}")


if __name__ == "__main__":
    run()
