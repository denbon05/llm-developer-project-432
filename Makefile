DBMATE := uv run dbmate --no-dump-schema

up:
	docker compose up

down:
	docker compose down

install:
	uv sync --frozen

run:
	uv run uvicorn app.main:create_app --factory --reload

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

typecheck:
	uv run basedpyright

test:
	uv run pytest

check: lint typecheck test
