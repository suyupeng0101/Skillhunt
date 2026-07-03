# Repository Guidelines

## Project Structure & Module Organization

This repository is a lightweight GitHub Skill / Agent radar pipeline.

- `src/main.py` contains the collection, analysis, scoring, export, and CLI entry point.
- `config/queries.yaml`, `config/seeds.yaml`, and `config/taxonomy.yaml` define search inputs, guaranteed repositories, categories, and install signals.
- `docs/index.html` is the static frontend. It reads JSON from `docs/data/`.
- `data/` stores local run outputs and reports. `docs/data/` stores publishable frontend data.
- `tests/test_main.py` contains pytest coverage for query building, rate-limit handling, fallback analysis, scoring, and exports.
- `.github/workflows/radar.yml` runs the scheduled GitHub Actions sync.

## Build, Test, and Development Commands

Install dependencies:

```bash
pip install -r requirements.txt
```

Run tests:

```bash
pytest
```

Collect GitHub candidates only:

```bash
python src/main.py collect-only
```

Run the full pipeline and export frontend data:

```bash
python src/main.py sync
```

Preview the static site locally:

```bash
python -m http.server 8000 --directory docs
```

Then open `http://127.0.0.1:8000/`.

## Coding Style & Naming Conventions

Use Python 3 style with 4-space indentation, type hints where practical, and small helper functions for parsing, scoring, filtering, and export logic. Keep CLI modes stable: `collect-only` and `sync`.

Use snake_case for Python functions and variables. Tests should use descriptive names such as `test_search_repos_waits_and_retries_on_rate_limit`.

For frontend changes, keep `docs/index.html` dependency-free and static. Do not introduce build tooling unless there is a clear project need.

## Testing Guidelines

Use `pytest`. Add or update tests in `tests/test_main.py` when changing query construction, GitHub API behavior, filtering rules, model fallback logic, scoring, or export formats.

Prefer deterministic tests with monkeypatches and fake responses. Avoid real network calls in tests.

## Commit & Pull Request Guidelines

This checkout has no readable Git history, so use clear, conventional commit messages such as:

```text
feat: add trending repo filtering
fix: handle GitHub rate limit retries
docs: update configuration guide
```

Pull requests should include a short summary, affected files or behavior, test results, and screenshots for frontend changes.

## Security & Configuration Tips

Never commit `.env`, tokens, API keys, cookies, or private repository data. Keep secrets such as `PERSONAL_ACCESS_TOKENS` and `MODEL_API_KEY` in local `.env` or GitHub Actions Secrets. Public GitHub Pages output should only include safe static files under `docs/`.
