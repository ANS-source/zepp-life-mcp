# Contributing

Thanks for contributing.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Before opening a change

- keep exported data, local config, and SQLite files out of git
- never commit real Zepp tokens
- keep changes focused and update README when CLI behavior changes

## Checks

```bash
ruff check src tests
pytest
python -m build
```
