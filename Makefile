PYTHON ?= python3.11
VENV := .venv
BIN := $(VENV)/bin

.PHONY: setup lint test ingest clean-data

setup:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev,data]"
	$(BIN)/pre-commit install

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

test:
	$(BIN)/pytest

# Download CFPB complaints and load the data window into DuckDB (needs Java 17+)
ingest:
	$(BIN)/python -m smart_complaint_triage.ingest

# Clean complaints_raw into complaints_clean (English only, PII masked, teams, splits)
clean-data:
	$(BIN)/python -m smart_complaint_triage.clean
