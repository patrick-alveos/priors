PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: setup preview test lint run docker-up docker-down clean

setup:  ## Create venv, install deps, init the database
	@if command -v python3.12 >/dev/null 2>&1; then python3.12 -m venv .venv; \
	elif command -v uv >/dev/null 2>&1; then uv venv --seed --python 3.12 .venv; \
	else echo "Need Python 3.12+ (or install uv: https://docs.astral.sh/uv/)"; exit 1; fi
	$(PIP) install -e ".[dev]"
	$(PY) -m priors init-db
	@echo "Done. Next: cp .env.example .env, add your keys, then 'make preview'."

preview:  ## Build a test issue locally (no email sent, no API keys needed)
	$(PY) -m priors preview

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .

run:  ## Full weekly run (Phase 1+)
	$(PY) -m priors run

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

clean:
	rm -rf build data/artifacts
