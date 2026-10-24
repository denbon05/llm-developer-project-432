DBMATE := uv run dbmate --no-dump-schema
# The API and the worker copy their latest run's output here, for make trace
LOGS_DIR := logs

infra:
	docker compose up

down:
	docker compose down

install:
	uv sync --frozen

# The app logs each request with its id, which replaces the access log.
# Unbuffered, so the terminal shows each line as it is written.
api:
	mkdir -p $(LOGS_DIR)
	PYTHONUNBUFFERED=1 uv run uvicorn app.main:create_app --factory --reload \
		--reload-dir app --no-access-log 2>&1 | tee $(LOGS_DIR)/api.log

worker:
	mkdir -p $(LOGS_DIR)
	PYTHONUNBUFFERED=1 uv run python -m app.temporal.worker 2>&1 \
		| tee $(LOGS_DIR)/worker.log

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

# Needs the API, the worker and the model server; writes
# evals/reports/generation_<subset|full>.md; full=1 runs every case
eval-generation:
	uv run python -m evals.generation $(if $(full),--full)

# Calls and cost by model and purpose; job=<id> for one card
costs:
	uv run python -m evals.costs $(if $(job),--job $(job))

# One job's log lines from the API and the worker, in time order
trace:
	$(if $(job),,$(error usage: make trace job=<id>))
	grep -hs '$(job)' $(LOGS_DIR)/api.log $(LOGS_DIR)/worker.log | sort

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
