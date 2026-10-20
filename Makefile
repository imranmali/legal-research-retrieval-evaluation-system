.PHONY: install lint format typecheck test check spec-validate

install:
	uv sync

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

test:
	uv run pytest --cov --cov-report=term-missing --cov-report=xml

spec-validate:
	openspec validate --all --strict

check: lint typecheck test
