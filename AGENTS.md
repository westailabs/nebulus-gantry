# AGENTS.md

## Project overview

Nebulus Gantry is the full-stack AI chat interface for the Nebulus Prime ecosystem. It provides a dark-themed conversational UI with streaming LLM responses, long-term memory, multi-user authentication, and an admin control plane for services, models, and users.

Version 2 is a React + FastAPI rewrite of the earlier Chainlit / vanilla-JS app. This repository is licensed under the MIT License; see [LICENSE](LICENSE).

Longer architectural notes live in `CONTEXT.md`. Operational rules for agents live in `AI_DIRECTIVES.md`. Development SOPs live in `WORKFLOW.md`. Record project-specific pitfalls in `docs/AI_INSIGHTS.md`.

## Setup and commands

Prerequisites: Docker and Docker Compose v2 (recommended), or Python 3.12+ and Node.js 20+ for local dev. A local LLM server that speaks the OpenAI-compatible `/v1/chat/completions` API is required for chat. Gantry's private ChromaDB (optional, for long-term memory) is expected at the URL in `NEBULUS_CHROMA_URL` and is **not** started by this compose file.

```bash
# Start / stop the stack (canonical)
bin/gantry start        # docker compose up --build
bin/gantry stop         # docker compose down
bin/gantry rebuild      # docker compose up -d --build
bin/gantry restart      # docker compose restart
bin/gantry logs         # docker compose logs -f
bin/gantry status       # docker compose ps

# Backend tests (from repo root; uses root pytest.ini)
python3 -m pytest backend/tests -v
# or: bin/gantry test

# Frontend tests and lint
bin/gantry test-frontend
# or: cd frontend && npm test && npm run lint

# Pre-commit hooks (if installed)
bin/gantry validate     # pre-commit run --all-files
```

On this branch, Docker publishes the frontend at <http://localhost:3002> (container port 3000). The backend listens on port 8000 (compose uses `network_mode: host` for the backend). API docs: <http://localhost:8000/docs>. The Vite dev server uses 5173 if you run `npm run dev` outside Docker.

Do not use `bin/gantry promote` — it points at a playbook path that is not in this tree.

Local (non-Docker) backend, from the **repo root**:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
export PYTHONPATH=.
uvicorn backend.main:app --reload --port 8000
```

Frontend: `cd frontend && npm install && npm run dev`.

Copy `.env.example` rather than inventing env files. Name variables only; never commit `.env` or print secret values.

## Build, test, and lint

- Backend tests live in `backend/tests/` (about 39 test modules). Run them from the repo root with `python3 -m pytest backend/tests -v`. Root `pytest.ini` sets `testpaths = backend/tests` and `asyncio_mode = auto`. A root `tests/e2e_smoke_test.py` also exists; it is not in the default pytest path.
- Frontend tests use Vitest: `cd frontend && npm test` (`vitest run`). Lint: `cd frontend && npm run lint`. Build: `cd frontend && npm run build`.
- Python lint on this repo is **flake8** (`.flake8`, also wired in pre-commit). Do not run a repo-wide ruff format unless asked — it would reformat the tree.
- Declare backend work done only after pytest is green. Run `bin/gantry validate` when pre-commit is installed.
- CI (`.github/workflows/ci.yml`) runs flake8 + backend pytest, and frontend lint + vitest, on `develop` and `main`.

## Code style

- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Pydantic schemas, services in `backend/services/`, routes in `backend/routers/`.
- Frontend: React 19, TypeScript, Vite 7, Tailwind CSS v4, Zustand stores.
- Follow patterns already in `backend/` and `frontend/src/` and the notes in `CONTEXT.md`. Prefer small, focused diffs. Type-hint new Python; use existing component patterns in the UI.
- Pre-commit currently runs trailing-whitespace, end-of-file-fixer, check-yaml, detect-private-key, flake8, ansible-lint, markdownlint, yamllint, djLint, stylelint, eslint, and pytest.

## Git workflow

- Branch off `develop`, not `main`. Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`).
- Merge with `--no-ff`. Never commit straight to `main` or `develop`.
- Keep feature branches local until Jason approves a push or pull request. Do not push, publish, or open a PR unless he asked for that specific action.
- `main` and `develop` have diverged in this repo; do not merge them unless he asks.

## Security and privacy

- Never commit secrets, tokens, or `.env` files. Name environment variables only; never print values.
- Never read vault files or `~/.config/neo4j-shared.env`.
- No proprietary O'Reilly data in this repo or in agent context. Pattern-level problems only.
- Ask before installing packages, changing remotes, merging, pushing, or restarting services.

Current environment variable names (values belong in `.env`, not here):

- `DATABASE_URL`, `SECRET_KEY`, `SESSION_EXPIRE_HOURS`, `GANTRY_DATA_DIR`
- `NEBULUS_CHROMA_URL` (legacy alias: `CHROMA_HOST`) — Gantry's **private** memory Chroma, default port 8001
- `NEBULUS_LLM_URL` (legacy alias: `TABBY_HOST`), `NEBULUS_LLM_API_KEY`, `NEBULUS_DEFAULT_MODEL`
- `CORS_ORIGINS`, `VITE_API_URL`, `BIND_HOST`, `HTTPS_ENABLED`
- `ATOM_BASE_URL`, `OVERLORD_ROUTING_ENABLED`, `NEBULUS_NETWORK`

## Agent boundaries

- Canonical run path is Docker Compose via `bin/gantry`. Check existing architecture before proposing new abstractions.
- For significant features: read `docs/AI_INSIGHTS.md`, draft a plan / spec under `docs/features/`, and wait for approval before coding.
- Update or add tests for the code you change. After meaningful lessons, update `docs/AI_INSIGHTS.md`.
- Wiki or remote doc pushes require explicit approval.

## Nebulus shared services

- Shared RAG in the West AI Labs ecosystem is `shared-rag` on port **8002**. The old **shared** ChromaDB on port 8001 is retired; do not treat Gantry as a client of that shared instance.
- Gantry may still use a **private** Chroma for its own long-term memory. On this branch, compose sets `NEBULUS_CHROMA_URL=http://127.0.0.1:8001`. That process is external — this `docker-compose.yml` does not start it.
- LLM URL defaults to `http://localhost:5000` in code if unset. This branch's compose default is `NEBULUS_LLM_URL=http://127.0.0.1:18789`. Prefer the env var over hardcoded ports.
- Optional integration with Nebulus Atom via `ATOM_BASE_URL` (default `http://localhost:8010`) and overlord/orchestrator routes.

## Key files and directories

| Path | Purpose |
|------|---------|
| `backend/main.py` | FastAPI app entry point, CORS, router registration |
| `backend/config.py` | Settings loaded from environment variables |
| `backend/platform.py` | LLM / Chroma URL resolution |
| `backend/models/` | ORM models (user, conversation, message, session, and others) |
| `backend/schemas/` | Pydantic request/response schemas |
| `backend/services/` | Business logic (auth, chat, LLM, memory, graph, Docker, overlord, …) |
| `backend/routers/` | API routes (`auth`, `chat`, `admin`, plus documents, personas, overlord, orchestrator, …) |
| `frontend/src/stores/` | Zustand stores |
| `frontend/src/services/api.ts` | HTTP client |
| `frontend/src/pages/` | Route-level pages |
| `docker-compose.yml` | Backend + frontend; backend uses host networking |
| `bin/gantry` | CLI for compose, tests, and validate |

## Generated or restricted files

- Do not commit `.env`, `data/*.db`, or `venv/` / `.venv/`.
- Do not edit `.claude/cache/` or similar tool caches.
- `bin/gantry test` should run backend pytest; if you find it still pointing at a missing `venv/` or at root `tests/` only, fix that wrapper rather than inventing a third command.
