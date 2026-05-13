# Brew GIS Makefile
#
# Usage:
#   make <target>
#
# Override COMPOSE_FILE to use infra compose instead:
#   COMPOSE_FILE=docker-compose.infra.yml make test
#
COMPOSE_FILE ?= docker-compose.local.yml
COMPOSE_RUN = docker compose -f $(COMPOSE_FILE) run --rm django

# ─────────────────────────────────────────────
# Service lifecycle
# ─────────────────────────────────────────────

.PHONY: up
up:  ## Build and start full local stack (Django + PostGIS + Redis + tipg + Martin + Celery + Flower)
	docker compose -f $(COMPOSE_FILE) up --build

.PHONY: up-infra
up-infra:  ## Start only infrastructure services (PostGIS, Redis, tipg, Martin)
	docker compose -f docker-compose.infra.yml up -d

.PHONY: down
down:  ## Stop and remove all containers
	docker compose -f $(COMPOSE_FILE) down

.PHONY: shell
shell:  ## Open Django shell
	$(COMPOSE_RUN) python manage.py shell

# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────

.PHONY: migrate
migrate:  ## Apply database migrations
	$(COMPOSE_RUN) python manage.py migrate

.PHONY: makemigrations
makemigrations:  ## Create new database migrations
	$(COMPOSE_RUN) python manage.py makemigrations

.PHONY: check-migrations
check-migrations:  ## Check for missing migrations (CI gate)
	$(COMPOSE_RUN) python manage.py makemigrations --check --dry-run

.PHONY: clean-test-db
clean-test-db:  ## Drop and recreate the test database
	$(COMPOSE_RUN) python manage.py reset_db --noinput
	$(COMPOSE_RUN) python manage.py migrate

# ─────────────────────────────────────────────
# Testing
# ─────────────────────────────────────────────

.PHONY: test
test:  ## Run all tests (excludes e2e)
	$(COMPOSE_RUN) pytest -m "not e2e" --timeout=300

.PHONY: test-fast
test-fast:  ## Run tests with fast-fail and reuse-db
	$(COMPOSE_RUN) pytest -x --reuse-db -m "not e2e and not integration" --timeout=300

.PHONY: test-parallel
test-parallel:  ## Run tests in parallel (excludes slow and e2e, requires pytest-xdist)
	$(COMPOSE_RUN) pytest -n auto --reuse-db -m "not slow and not e2e" --timeout=300

.PHONY: test-e2e
test-e2e:  ## Run end-to-end tests only (sequential, single worker)
	$(COMPOSE_RUN) pytest tests/e2e/ -m e2e -n 0 --timeout=300
.PHONY: test-review
test-review:  ## Run UX design review tests only
	$(COMPOSE_RUN) pytest tests/review/ -m review --timeout=300

.PHONY: test-review-parallel
test-review-parallel:  ## Run UX design review tests in parallel (requires pytest-xdist)
	$(COMPOSE_RUN) pytest tests/review/ -m review -n auto --timeout=300 || echo "Warning: xdist not installed, install with 'pip install pytest-xdist'"

.PHONY: clean-review-screenshots
clean-review-screenshots:  ## Remove stale review test screenshots
	rm -rf tests/review/screenshots

.PHONY: test-models
test-models:  ## Run model tests only
	$(COMPOSE_RUN) pytest -m models --reuse-db

.PHONY: test-views
test-views:  ## Run view/HTTP tests only
	$(COMPOSE_RUN) pytest -m views --reuse-db

.PHONY: test-integration
test-integration:  ## Run integration tests only
	$(COMPOSE_RUN) pytest -m integration --reuse-db

.PHONY: test-safe
test-safe:  ## Run tests excluding slow and e2e (safe for parallel execution)
	$(COMPOSE_RUN) pytest -m "not slow and not e2e" --timeout=300 -n auto

.PHONY: test-deal
test-deal:  ## Run deal property-based tests only (sequential, with deal enabled)
	$(COMPOSE_RUN) bash -c "DEAL_ENABLED=1 DEAL_CASE_COUNT=10 pytest tests/workspace/test_deal_contracts.py -n 0 --timeout=300"

.PHONY: test-all
test-all:  ## Run all tests sequentially (safe for full coverage)
	$(COMPOSE_RUN) pytest -n 0 --timeout=300

.PHONY: test-dbt
test-dbt:  ## Run dbt seed + run + test (seed-based models only)
	$(COMPOSE_RUN) bash -c 'cd brewgis/dbt_project && dbt seed --profiles-dir . --full-refresh && dbt run --profiles-dir . --select base_canvas_geometry+ && dbt test --profiles-dir . --select base_canvas_geometry+'

.PHONY: test-mcp
test-mcp:  ## Run MCP server tests (models marker only)
	$(COMPOSE_RUN) pytest tests/workspace/test_mcp_server.py -m models -v

.PHONY: test-gx
test-gx:  ## Run Great Expectations data quality validation
	$(COMPOSE_RUN) python manage.py validate_data_quality

.PHONY: mcp-up
mcp-up:  ## Start MCP server in Docker
	$(COMPOSE_RUN) mcp
.PHONY: coverage
coverage:  ## Run tests with coverage report and fail if below threshold
	$(COMPOSE_RUN) bash -c 'coverage run -m pytest -m "not e2e" --timeout=300 && coverage report --fail-under=60'

# ─────────────────────────────────────────────
# Linting & Formatting
# ─────────────────────────────────────────────

.PHONY: lint
lint:  ## Run Ruff linter
	$(COMPOSE_RUN) ruff check brewgis/

.PHONY: lint-fix
lint-fix:  ## Run Ruff linter with auto-fix
	$(COMPOSE_RUN) ruff check brewgis/ --fix

.PHONY: format
format:  ## Run Ruff formatter
	$(COMPOSE_RUN) ruff format brewgis/ tests/

.PHONY: format-check
format-check:  ## Check formatting without changes
	$(COMPOSE_RUN) ruff format --check brewgis/ tests/

.PHONY: typecheck
typecheck:  ## Run mypy type checker
	$(COMPOSE_RUN) mypy brewgis

.PHONY: lint-dbt
lint-dbt:  ## SQLFluff lint dbt models
	$(COMPOSE_RUN) sqlfluff lint brewgis/dbt_project/

# ─────────────────────────────────────────────
# CI pipeline (mirrors CI workflow)
# ─────────────────────────────────────────────

.PHONY: check
check: lint format-check typecheck test test-dbt test-gx  ## Run full CI pipeline: lint + format-check + typecheck + test + dbt + GX data quality

# ─────────────────────────────────────────────
# Development setup
# ─────────────────────────────────────────────

.PHONY: setup
setup:  ## Install git hooks and local dependencies
	@echo "==> Installing pre-commit hooks..."
	pre-commit install
	@echo "==> Checking pre-commit hooks are active..."
	@pre-commit run --all-files --show-diff-on-failure || true
	@echo "==> Done. Make sure to 'pip install -r requirements/local.txt' if developing on host."

.PHONY: dev-host
dev-host:  ## Set up host development mode (infra containers + env file)
	@echo "==> Checking prerequisites..."
	@python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" || (echo "ERROR: Python 3.12+ required" && exit 1)
	@docker compose version >/dev/null 2>&1 || (echo "ERROR: Docker Compose required" && exit 1)
	@echo "==> Copying .env.example to .env (if missing)..."
	@test -f .env || cp .env.example .env
	@echo "==> Starting infrastructure containers..."
	docker compose -f docker-compose.infra.yml up -d
	@echo ""
	@echo "==> Infrastructure running. Run the Django dev server:"
	@echo "    python manage.py runserver"
	@echo ""
	@echo "==> Run Celery worker (separate terminal):"
	@echo "    celery -A config.celery_app worker -l info"

# ─────────────────────────────────────────────
# Help (auto-documented)
# ─────────────────────────────────────────────

.PHONY: help
help:  ## Show this help
	@grep -Eh '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
