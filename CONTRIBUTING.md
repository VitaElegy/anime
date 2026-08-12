# Contributing to NicoTracker / anime

Thanks for your interest in contributing! This document explains how to set up
the project locally, run checks, and submit changes.

## Development setup

Prerequisites: Python 3.11+, Node.js 20+, pnpm/npm, and (optionally) qBittorrent.

### Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# run the API server
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev        # Vite dev server, proxies /api to :8000
```

## Running checks

```bash
make test          # backend pytest + frontend vitest
make lint          # ruff check (backend) + eslint (frontend)
make build         # frontend production build
```

Or run them individually:

```bash
pytest tests/ -q                     # backend
cd frontend && npm test -- --run      # frontend unit tests
cd frontend && npm run build          # frontend production build
ruff check app/ tests/                # Python lint
```

All checks must pass before a PR is merged. The CI workflow
(`.github/workflows/ci.yml`) runs the same commands.

## Project layout

```
app/            FastAPI backend (routers, services, models, config)
frontend/       React + Vite frontend
tests/          Backend test suite
deploy/         Nginx + systemd deployment assets
docs/           Protocol & design documents
```

## Commit conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new capability
- `fix:` bug fix
- `test:` tests only
- `docs:` documentation only
- `chore:` maintenance (build, tooling, deps)
- `refactor:` code change that neither fixes a bug nor adds a feature

Example: `feat(backend): add mikan search source`

## Pull request process

1. Fork the repo and create a feature branch from `master`.
2. Make focused commits (one logical change per commit).
3. Run `make test` and `make lint` locally.
4. Open a PR; CI must be green.
5. Keep PRs small and describe the change and motivation in the description.
