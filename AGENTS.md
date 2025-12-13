# Repository Guidelines

## Project Structure
- `src/mai/`: core Python package (FastAPI routes, ingestion pipeline, organizer, review, SQLite/SQLAlchemy layer).
- `src/mai_qt/`: Qt (PySide6) desktop UI.
- `db/schema.sql`: SQLite schema (includes FTS5 search tables).
- `scripts/`: helper scripts for local dev/demo data.
- `tests/`: pytest suite.
- `var/`, `tmp/`, `tmpdb/`: local runtime artifacts (do not commit).

## Build, Test, and Development Commands
- Install (editable): `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
- Initialize DB: `mai-init-db` (creates `var/data/mai.db` and applies `db/schema.sql`)
- Run API (dev): `mai-api` (FastAPI/Uvicorn; configure with `MAI_API_HOST`, `MAI_API_PORT`)
- Ingest/import: `mai-import <path>` (scan files); `mai-import --watch <path>` (watchdog mode)
- Organizer: `mai-organize preview --root <dest>` → `mai-organize apply <manifest_id>`; rollback with `mai-organize rollback <manifest_id>`
- Run desktop app: `mai-qt`
- Tests: `pytest -q`

## Coding Style & Naming Conventions
- Python 3.11+; prefer type hints and `pathlib.Path`.
- Keep modules cohesive and follow existing layout (`mai.ingest.*`, `mai.organizer.*`, `mai.api.routes.*`).
- Use `snake_case` for functions/vars, `PascalCase` for classes, `UPPER_CASE` for constants.
- If available in your environment, use `ruff` for lint/format: `ruff check .` and `ruff format .` (optional: `mypy`).

## Performance-First Guidelines
- MAI is local-first: keep “hot paths” fast (SQLite/FTS queries, hashing, organizer ops).
- Avoid N+1 DB access; prefer `selectinload` and batched queries.
- Network/provider calls must be optional, time-bounded, and must not block UI threads.
- When changing search/ingest/organizer code, include a brief perf note in the PR (expected latency/throughput impact).

## Testing Guidelines
- Framework: `pytest` (+ `pytest-asyncio` where needed).
- Naming: `tests/test_*.py`; add/adjust tests with new behavior and bug fixes.

## Commit & Pull Request Guidelines
- For new work, use **Conventional Commits**: `feat:`, `fix:`, `perf:`, `refactor:`, `test:`, `docs:`, `chore:` (example from history: “Harden repo hygiene”).
- PRs should include: summary, rationale, how to run (`pytest -q`, relevant CLI command), and any config/env changes.
- If UI changes are visible, add a screenshot/GIF; if behavior changes, link the related issue/task.
