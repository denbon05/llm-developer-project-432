DBMATE := uv run dbmate --no-dump-schema

infra:
	docker compose up

down:
	docker compose down

install:
	uv sync --frozen

run:
	uv run uvicorn app.main:create_app --factory --reload

worker:
	uv run python -m app.temporal.worker

# Needs the API and the worker running; dir defaults to evals/datasets
ingest:
	uv run python -m evals.ingest $(dir)

migrate-up:
	$(DBMATE) up

migrate-status:
	$(DBMATE) status

migrate-rollback:
	$(DBMATE) rollback

migration:
	$(DBMATE) new $(name)

lint:
	uv run ruff check
	uv run ruff format --check

format:
	uv run ruff format

typecheck:
	uv run basedpyright

test:
	uv run pytest

check: lint typecheck test
