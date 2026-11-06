# Shortcuts. Windows without make: run the command on the right of each target instead.
.PHONY: install check lint test migrate openapi run ui up down

install:            ## uv sync
	uv sync

lint:               ## uv run ruff check .
	uv run ruff check .

test:               ## uv run pytest
	uv run pytest

check: lint test    ## what every PR must pass

up:                 ## docker compose up -d
	docker compose up -d

down:               ## docker compose down
	docker compose down

migrate:            ## uv run alembic upgrade head
	uv run alembic upgrade head

openapi:            ## uv run python -m app.export_openapi
	uv run python -m app.export_openapi

run:                ## uv run uvicorn app.main:app --reload
	uv run uvicorn app.main:app --reload

ui:                 ## uv run --group ui streamlit run ui/streamlit_app.py (the API must be running)
	uv run --group ui streamlit run ui/streamlit_app.py
