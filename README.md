# smart-complaint-triage

An NLP system that helps a bank's complaints team handle customer complaints faster and in the
right order. It routes each complaint to the right team, ranks complaints by escalation risk,
detects emerging issues early and writes short summaries for staff.

The system supports staff decisions. It does not reply to customers or decide refunds.

See [docs/development_guide.md](docs/development_guide.md) for the full problem statement, data
and development plan.

## Project structure

```
configs/                    YAML settings
data/                       local data (not committed)
src/smart_complaint_triage/ Python package
tests/                      pytest tests
notebooks/                  analysis notebooks
dashboard/                  Streamlit dashboard
docs/                       documentation
```

## Getting started

Requires Python 3.11 or 3.12.

```bash
make setup   # create .venv, install dev tools, install pre-commit hooks
make lint    # ruff check + format check
make test    # run pytest
```

Optional dependency groups (`data`, `ml`, `llm`, `pipeline`, `api`, `dashboard`) are installed
as needed, for example `pip install -e ".[data,ml]"`, or everything with `".[all]"`.

## License

MIT, see [LICENSE](LICENSE).
