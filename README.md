# Workstream API

Workstream is an API-only, multi-tenant project and issue management service. It is a modular monolith built with FastAPI, PostgreSQL, Redis, Celery, and a transactional outbox.

## Local development

Prerequisites: Docker Compose and `uv`.

```bash
cp .env.example .env
make install
make up
docker compose run --rm api python -m workstream.seed
```

The API and OpenAPI UI are at <http://localhost:8000> and <http://localhost:8000/docs>. Mailpit is at <http://localhost:8025>. Liveness, readiness, and Prometheus metrics are exposed at `/health/live`, `/health/ready`, and `/metrics`.

Local demo accounts use password `DemoPassword123!`: `owner@demo.local`, `member@demo.local`, and `viewer@demo.local`. These are seed data, never application defaults.

## Operations

Compose runs an explicit one-shot migration service before starting the API and workers. `make migrate` upgrades a host-configured database; `make migration m="description"` creates a revision and `make downgrade` rolls back one revision. `make test`, `make test-unit`, `make test-integration`, `make test-concurrency`, `make lint`, `make typecheck`, `make audit`, and `make ci` run verification. `make down` stops the stack.

Architecture details and decisions are in [docs/architecture.md](docs/architecture.md) and [docs/adr](docs/adr).
