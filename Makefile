.PHONY: test lint format collect build app

test:
	uv run pytest

lint:
	uv lock --check
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

collect:
	uv run --env-file .env leads collect

build:
	uv run leads build

app:
	uv run streamlit run src/leads/app/main.py
