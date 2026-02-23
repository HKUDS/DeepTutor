# Repository Guidelines

## Project Structure & Module Organization
- `src/`: Python backend and core logic (agents, services, knowledge base, tools, logging).
- `src/api/`: FastAPI server and routers; `src/agents/` for module-specific agent workflows.
- `web/`: Next.js 16 + React 19 frontend (App Router, components, hooks, lib utilities).
- `config/`: YAML configuration (`main.yaml`, `agents.yaml`) for runtime behavior.
- `data/`: Runtime outputs (knowledge bases, user artifacts, logs); avoid committing generated data.
- `tests/`: Python tests (pytest). `docs/`, `assets/`, and `scripts/` hold documentation, static assets, and helper scripts.

## Build, Test, and Development Commands
- `pip install -r requirements.txt`: install backend dependencies (Python 3.10+).
- `npm install --prefix web`: install frontend dependencies.
- `python scripts/start_web.py`: start backend + frontend together.
- `python src/api/run_server.py`: start backend only.
- `npm run dev --prefix web`: start frontend dev server.
- `pytest tests -q`: run Python tests (tests folder only).
- `docker compose up --build -d`: build and run with Docker.

## Coding Style & Naming Conventions
- Python: Ruff lint/format via `pyproject.toml` (line length 100, 4-space indent).
- Frontend: Prettier in `web/.prettierrc.json` (2-space indent, single quotes, no semicolons) + ESLint (`npm run lint`).
- Naming: React components use `PascalCase` (e.g., `Sidebar.tsx`), hooks/utilities use `camelCase` with `use*` for hooks.

## Testing Guidelines
- Framework: pytest; tests live under `tests/` with `test_*.py` naming.
- Run a single test file: `pytest tests/agents/solve/utils/test_json_utils.py`.
- No explicit coverage thresholds are documented.

## Commit & Pull Request Guidelines
- Recent history mostly uses Conventional Commit prefixes (`feat:`, `fix:`, `docs:`, `chore:`) with occasional `exp:` or plain `update`/`fix lint`; follow Conventional Commits unless a workflow says otherwise.
- Branch from `dev` and open PRs targeting `dev`.
- Run `pre-commit run --all-files` before opening a PR.
- PRs should include a concise summary, testing notes, linked issues, and screenshots for UI changes when applicable.

## Configuration & Secrets
- Copy `.env.example` to `.env` and set API keys/ports; for frontend, set `web/.env.local` with `NEXT_PUBLIC_*` values.
- Keep secrets out of git; prefer environment files and `config/` overrides.
