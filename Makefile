.PHONY: test lint format build

test:
	uv run pytest

lint:
	uv lock --check
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

build:
	uv run leads build
