.PHONY: install up down build logs migrate migration downgrade seed test test-unit test-integration test-concurrency lint format typecheck audit ci
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
downgrade:
	uv run alembic downgrade -1
seed:
	uv run python -m workstream.seed
test:
	uv run pytest
test-unit:
	uv run pytest -m unit
test-integration:
	uv run pytest -m integration
test-concurrency:
	uv run pytest -m concurrency
lint:
	uv run ruff format --check . && uv run ruff check .
format:
	uv run ruff format . && uv run ruff check --fix .
typecheck:
	uv run mypy
audit:
	uv run pip-audit
ci: lint typecheck test audit
