.PHONY: up down install run lint

up:
	docker compose up

down:
	docker compose down

install:
	uv sync --frozen

run:
	uv run uvicorn app.main:app --reload

lint:
	uv run ruff check app
