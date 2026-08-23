.PHONY: install up down build logs migrate migration seed test lint format typecheck audit ci
install:
	uv sync --all-groups
up:
	docker compose up -d --build
down:
	docker compose down
build:
	docker compose build
logs:
	docker compose logs -f api worker beat
migrate:
	uv run alembic upgrade head
migration:
	uv run alembic revision --autogenerate -m "$(m)"
seed:
	uv run python -m workstream.seed
test:
	uv run pytest
lint:
	uv run ruff format --check . && uv run ruff check .
format:
	uv run ruff format . && uv run ruff check --fix .
typecheck:
	uv run mypy
audit:
	uv run pip-audit
ci: lint typecheck test audit

