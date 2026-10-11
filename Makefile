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

# Computes the chunk vectors that are missing or from another model
reindex:
	uv run python -m app.rag.reindex

# Needs ingested documents; mode: vector, keyword or hybrid (default)
search:
	uv run python -m evals.search query "$(q)" $(if $(mode),--mode $(mode)) $(if $(top_k),--top-k $(top_k))

# Writes evals/reports/search_<lang>.md; lang: en (default) or ru
eval-search:
	uv run python -m evals.search eval $(if $(lang),--lang $(lang))

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
