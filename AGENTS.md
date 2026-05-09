# Repository Guidelines

## Project Overview

Brew GIS is a GIS Workspace for Urban Planners and Data Scientists — an open-source alternative to enterprise GIS platforms (ArcGIS, Carto). It provides a batteries-included, Docker-based workspace for managing geographic data, creating map layers, and rendering maps with vector tiles. Built on Django with cookiecutter-django scaffolding.

**License:** GPLv3

## Architecture & Data Flow

```
User Browser                    Docker Compose Stack
     │                                │
     ├─ Auth ──► django-allauth       │
     ├─ Admin ─► Django Admin         │
     ├─ Dynamic HTML ─► htmx          │
     ├─ Map ─► MapLibre GL JS (Lit)   │
     │          │                     │
     │          ▼                     │
     │      Vector Tiles ◄── tipg ◄───┤
     │                   ◄── martin ◄─└── PostGIS
     ▼                                ▼
  Django (config/)              Redis ◄── Celery Worker (async tasks)
     │                                 │
     └── brewgis.workspace ────────────┘
              │
              ├─ Models: Workspace, Layer, Scenario, AnalysisRun, PaintedCanvas
              ├─ Views: 19 view modules (FormViews, CreateViews, FBVs)
              ├─ Analysis: dbt pipeline (30 models, 4 macros, Python + SQL)
              └─ GIS I/O: geopandas for file ingest, SQLAlchemy for PostGIS writes
```
- **Request flow:** Browser → Django → View (FormView/CreateView/FBV) → Template (Bootstrap 5, htmx for dynamic updates, Lit for map component)
|- **Map flow:** Template renders `<brew-gis-map>` Lit component → fetches vector tiles from tipg (`/tipg/collections/{schema}.{table}/tiles/{tms}/{z}/{x}/{y}`) or Martin (`/martin/{schema}.{table}/{z}/{x}/{y}`) depending on `TILE_SERVER_BACKEND` setting → tile server serves tiles from PostGIS
- **Async flow:** Celery beat (DatabaseScheduler via django-celery-beat) dispatches periodic tasks → Redis broker → Celery workers execute tasks
- **GIS ingest:** User uploads GIS file → `ReadGISFileView` → `geopandas.read_file()` → `df.to_postgis()` via SQLAlchemy
- **Dynamic UI:** htmx handles form submissions, partial page updates, and AJAX navigation without a JavaScript framework
|- **Analysis pipeline:** dbt models execute in dependency order: `env_constraint` → `core` (end_state) → `water_demand` / `energy_demand` (parallel). Module outputs are registered as Layers in the workspace.
|- **dbt orchestration:** AnalysisRun model tracks pipeline state (PENDING→RUNNING→SUCCESS/FAILURE). Celery tasks invoke `dbt run` per module with scenario-scoped `--vars`. Python dbt models (trip_distribution.py, mode_choice.py) run numpy-based computation inside dbt's Python model framework.

## Key Directories

|Directory|Purpose|
|---|---|
|`brewgis/workspace/`|The sole Django app — models, views, tasks, templates, services, analysis modules, symbology, built_forms, management commands|
|`brewgis/workspace/views/`|19 view modules split by feature (home, map, create_layer, read_gis_file, paint, symbology, analysis, import, workspace_crud, etc.)|
|`brewgis/workspace/models.py`|13 domain models (see Important Files)|
|`brewgis/workspace/tasks.py`|11 Celery shared tasks for analysis pipeline, data fetching, spatial allocation|
|`brewgis/workspace/analysis/`|Analysis module registry, preprocessors, stitchers, allocation engine|
|`brewgis/workspace/symbology/`|Map style generation (generator.py, color schemes, paint constraints)|
|`brewgis/workspace/built_forms/`|Built form models: BuildingType, PlaceType, PlaceTypeBuildingTypeMix|
|`brewgis/workspace/services/`|Service layer (census fetcher, LEHD fetcher, POI fetcher, etc.)|
|`brewgis/dbt_project/`|dbt project: 30 models (4 Python, 26 SQL), 4 macros, 4 seeds, 4 custom tests|
|`brewgis/templates/`|Django templates: base.html, form.html, workspace_map.html, allauth overrides|
|`brewgis/templates/workspace/partials/`|htmx partial templates for dynamic updates|
|`brewgis/static/`|Static assets (CSS, JS, images, fonts)|
|`brewgis/static/js/brew-gis-map.js`|Lit-based MapLibre GL JS web component (compiled via Vite+TS)|
|`config/settings/`|Django settings: `base.py`, `local.py`, `production.py`, `test.py`|
|`config/`|Root URLconf (`urls.py`), WSGI, Celery app|
|`compose/`|Docker build contexts: `local/` and `production/` for each service|
|`requirements/`|Pip requirements: `base.txt`, `local.txt`, `production.txt`|
|`docs/`|Sphinx documentation source|
|`tests/`|Root-level test directory with subdirectories per feature|
|`tests/workspace/`|Workspace app tests (views, models, fetchers, allocation, paint, symbology, etc.)|
|`tests/e2e/`|Playwright end-to-end BDD tests (features, steps, pages)|
|`tests/review/`|UX design review BDD tests (features, steps, pages)|
|`tests/features/`|BDD integration/behavioral feature files|
|`.envs/.local/`|Environment files for Docker Compose local stack|
|`.github/workflows/`|CI pipeline (pre-commit linting + pytest via Docker)|

## Development Commands

All commands use Docker Compose. **There is no local venv workflow** — everything runs in containers. Martin tile server runs alongside tipg in the local stack.

**Quick reference (see `Makefile` for all targets):**
```bash
# Build and start the full local stack
make up

# Start only infrastructure services (PostGIS, Redis, tipg, Martin)
make up-infra

# Run all tests
make test

# Run tests with fast-fail and reuse-db
make test-fast

# Run tests in parallel
make test-parallel

# Run only model tests
make test-models

# Run only view/HTTP tests
make test-views

# Run only integration tests (PostGIS, dbt, external services)
make test-integration

# Run end-to-end tests (Playwright BDD)
make test-e2e

# Run UX design review tests
make test-review

# Lint and format
make lint
make lint-fix
make format
make format-check

# Type checking
make typecheck

# Database migrations
make migrate
make makemigrations
make check-migrations

# Django shell
make shell

# dbt tests
make test-dbt

# Full CI pipeline (lint + format-check + typecheck + test)
make check
```

**Overriding the compose file:**
```bash
# Use infra compose instead of local compose
COMPOSE_FILE=docker-compose.infra.yml make test
```

**Raw Docker commands** (when `make` is not available or you need fine-grained control):
```bash
# Build and start the full local stack (Django + PostGIS + Redis + tipg + Martin + Celery + Flower)
docker compose -f docker-compose.local.yml up --build

# Run Django management commands
docker compose -f docker-compose.local.yml run django python manage.py <command>

# Run tests
docker compose -f docker-compose.local.yml run django pytest

# Run specific test markers
docker compose -f docker-compose.local.yml run django pytest -m models
docker compose -f docker-compose.local.yml run django pytest -m integration
docker compose -f docker-compose.local.yml run django pytest -m e2e

# Run tests with coverage
docker compose -f docker-compose.local.yml run django coverage run -m pytest
docker compose -f docker-compose.local.yml run django coverage html

# Type checking
docker compose -f docker-compose.local.yml run django mypy brewgis

# Lint (via pre-commit, runs in CI)
pre-commit run --all-files

# Install pre-commit hooks (run once after cloning)
make setup
pre-commit install

# Create superuser
docker compose -f docker-compose.local.yml run django python manage.py createsuperuser

# Check for missing migrations
docker compose -f docker-compose.local.yml run django python manage.py makemigrations --check

# Build docs
docker compose -f docker-compose.docs.yml build docs

# SQLFluff lint dbt models
docker compose -f docker-compose.local.yml run django sqlfluff lint brewgis/dbt_project/
```

## Host Development Mode

As an alternative to running the full stack in Docker, you can run Django (and Celery) directly on the host machine while Docker Compose provides infrastructure services (PostgreSQL/PostGIS, Redis, tipg, Martin). This enables breakpoints, hot-reload without container rebuilds, and avoids Docker filesystem overhead.

```bash
# 1. Copy the environment template and customize as needed
cp .env.example .env

# 2. Start only infrastructure services (PostGIS, Redis, tipg, Martin)
docker compose -f docker-compose.infra.yml up -d

# 3. Run Django dev server on the host (requires Python 3.12 + deps installed)
python manage.py runserver

# 4. Run Celery worker on the host (separate terminal or background)
celery -A config.celery_app worker -l info
```

**Key differences from Docker mode:**
|Aspect|Docker mode|Host mode|
|---|---|---|
|Compose file|`docker-compose.local.yml`|`docker-compose.infra.yml`|
|Django location|Inside container|On host (`localhost:8000`)|
|Tile servers|Docker network (`http://tipg:8081`)|Host ports (`http://localhost:8081`)|
|Redis URL|`redis://redis:6379/0`|`redis://localhost:6379/0`|
|Database URL|Docker service name|`localhost:5432`|
|Breakpoints|Requires Docker attach|Works natively|
|Settings file|`config.settings.local`|`config.settings.local`|
|`.env` file|Not used (env from compose)|Read from project root|
|`USE_DOCKER`|`yes`|`no`|
|Quick start|`docker compose -f docker-compose.local.yml up`|`docker compose -f docker-compose.infra.yml up -d` then `python manage.py runserver`|

**Infrastructure services** are managed via `docker-compose.infra.yml`:
- `postgres` on `localhost:5432`
- `redis` on `localhost:6379`
- `tipg` on `localhost:8081`
- `martin` on `localhost:3000`

**Full Docker stack** continues to work unchanged:
```bash
docker compose -f docker-compose.local.yml up --build
```

## Runtime & Tooling
- **Python:** 3.12 (required)
- **Package manager:** pip via `requirements/*.txt`
- **Runtime:** Docker (docker compose v2)
- **Database:** PostgreSQL 17 + PostGIS 3.5
- **Linter/Formatter:** Ruff (`ruff` for linting, `ruff format` for formatting)
- **Template linter:** djLint (profile: `django`, indent: 2 spaces)
- **Type checker:** mypy 1.13 with `django-stubs` and `mypy_django_plugin`
- **CI:** GitHub Actions — pre-commit linting + pytest in Docker
- **Pre-commit hooks (18 total):** `trailing-whitespace`, `end-of-file-fixer`, `check-json`, `check-toml`, `check-yaml`, `check-xml`, `debug-statements`, `builtin-literals`, `case-conflict`, `docstring-first`, `detect-private-key`, `django-upgrade` (target 6.0), `ruff`, `ruff-format`, `djlint-reformat-django`, `djlint-django`, `sqlfluff-lint`, `codespell`, `prettier` (js/ts/json/yaml/css/md), `eslint` (ts/js), local `tsc --noEmit`, local check-method-decorator script
|-
|- **SQL linter (dbt):** SQLFluff (`sqlfluff` + `sqlfluff-templater-dbt`, dialect: `postgres`, templater: `dbt`) — runs in Django container via `docker compose run django sqlfluff lint brewgis/dbt_project/`
|- **dbt LSP:** `j-clemons/dbt-language-server` (Go binary, v0.4.2) — installed on host at `~/.local/bin/dbt-language-server`. Resolves dbt refs, sources, macros, and variables in SQL/YAML files. Does not include Postgres function docs.

## Code Conventions

### Python Style
- **Linter:** Ruff with extensive rule set (F, E, W, C90, I, N, UP, ASYNC, S, B, DJ, SIM, PERF, RUF, and more — see `[tool.ruff.lint.select]` in `pyproject.toml`)
- **Formatter:** Ruff format (replaces Black)
- **Naming:** Standard Django conventions — `snake_case` for functions/variables, `PascalCase` for classes
- **String quotes:** Double quotes (Ruff default)
- **Line length:** 119 for Python, 119 for Django templates
- **Template indent:** 2 spaces (djLint)
- **Imports:** `from`-imports within app preferred. Ruff enforces isort via `I` rule with `force-single-line = true`
- **Type annotations:** mypy strict mode with `disallow_untyped_defs`. Per-module exceptions for Alembic, dbt, and similar files.

### Django Patterns
- **No REST Framework** — no DRF serializers or API views. django-ninja `ModelSchema` is used for data serialization in the map FBV.
- **htmx** for dynamic HTML: form submissions, partial updates via `HX-Redirect` header, `hx-trigger="every 2s"` for status polling
- **Lit web component** for the map: `<brew-gis-map>` element with properties for style, viewport, layers
- **django-allauth** for authentication (username-based, email required + verified)
- **Celery** uses JSON serialization, Redis broker, `django-celery-beat` DatabaseScheduler
|- **Tile server:** Martin (`ghcr.io/maplibre/martin`) and tipg (`ghcr.io/developmentseed/tipg`) both run; `TILE_SERVER_BACKEND` setting (`"tipg"` or `"martin"`) controls tile URL generation.
- **Settings** use `django-environ` for env-var-based configuration
- **Django partials** (`django-partial` library): `{% partialdef name %}` blocks for htmx fragment swapping, self-replacing forms via `hx-target="this" hx-swap="outerHTML"`
- **View patterns:** FBVs for map/read_gis_file, FormViews for upload, CreateViews for model creation, auth-guarded via `@user_passes_test` or `LoginRequiredMixin`

### Frontend
- **CSS framework:** Bootstrap 5 (via CDN)
- **Map library:** MapLibre GL JS v4.7+ wrapped in a Lit web component
- **Dynamic HTML:** htmx 2.x for AJAX form submission, partial page updates, and redirect handling
- **JS pattern:** Lit-based web component for the map (compiled from TypeScript via Vite); inline `<script>` for minor enhancements. No bundler for non-map assets.
- **CSS/JS files:** `project.css` (alert styling only), `project.js` (empty placeholder)
- **htmx patterns:**
  - Form submission: `hx-post` with `hx-target="#form-content" hx-swap="outerHTML"`, success → `HX-Redirect` header
  - Status polling: `hx-get="{% url 'analysis_status' %}" hx-trigger="every 2s" hx-swap="outerHTML"` on running/pending states
  - Self-replacing forms: `hx-target="this" hx-swap="outerHTML"` (symbology editor, bake forms)
  - Conditional loads: state selector `hx-get` triggers county checkbox partial load

### dbt Patterns
- **Project:** `brewgis/dbt_project/` with Postgres dialect, `brewgis` profile
- **Materialization:** View by default, table for computational models (transport, impact), Python models for numpy-based computation (trip_distribution, mode_choice)
- **Sources:** Dynamic `sources.yml` with table names/schemas resolved via dbt vars at runtime
- **Vars:** ~80 scenario parameters defined in `dbt_project.yml` with defaults, overridden by AnalysisRun via `--vars`
- **Python models:** dbt's `python` materialization with numpy/pandas — batch processing (2000-origin batches for trip_distribution)
- **Macros:** `delta_columns`, `du_per_acre`, `emp_per_acre`, `far` — in `brewgis/dbt_project/macros/`
- **Seeds:** CSV data files in `brewgis/dbt_project/seeds/` (rate tables, lookup data)
- **Tests:** Column-level (not_null, unique, non_negative) and model-level tests in `_schema.yml`
- **Naming:** Lowercase snake_case SQL files, prefixed by module (core_, env_constraint, transport_, energy_, water_, etc.)

## Important Files

|File|Role|
|---|---|
|`brewgis/workspace/models.py`|13 domain models: Workspace, Layer, SymbologyConfig, StyleClass, Scenario, PaintedCanvas, AnalysisRun, DataImportRun, PaintConstraint, MergeAudit, PaintEvent, County, DataSourceCategory, DataSource|
|`brewgis/workspace/urls.py`|38 URL patterns under namespace `workspace` — home, workspace CRUD, paint operations, symbology, built forms, analysis pipeline, import center|
|`brewgis/workspace/views/__init__.py`|Exports 19 view modules: home, map, create_layer, read_gis_file, workspace_detail, paint_canvas, symbology, analysis_views, built_forms, import_center, etc.|
|`brewgis/workspace/views/home.py`|Home page view listing workspaces (FBV with auth guard)|
|`brewgis/workspace/views/read_gis_file.py`|GIS file ingest pipeline (geopandas → PostGIS)|
|`brewgis/workspace/views/map.py`|Map view using django-ninja schemas, workspace-based, with scenario paint mode|
|`brewgis/workspace/views/create_layer.py`|Layer creation using ModelForm + CreateView|
|`brewgis/workspace/tasks.py`|11 Celery tasks: export_building_types, run_dbt_module, run_preprocessor_and_dbt, handle_module_completed, run_census_fetch, run_lehd_fetch, run_poi_fetch, run_spatial_allocation, run_column_stitching|
|`brewgis/workspace/admin.py`|Admin registrations for Workspace, Scenario, AnalysisRun, PaintedCanvas, PaintConstraint, DataSourceCategory, DataSource|
|`brewgis/templates/workspace/home.html`|Landing page with workspace list|
|`brewgis/templates/form.html`|Form template extending base.html, uses partials for htmx re-render|
|`brewgis/templates/workspace_map.html`|MapLibre GL JS map template with `<brew-gis-map>` component, paint toolbar, scenario selector, htmx-driven paint operations|
|`brewgis/templates/workspace/partials/_form_content.html`|htmx partial for form content (re-rendered on validation errors)|
|`brewgis/templates/workspace/partials/_form_result.html`|htmx partial for success/error messages|
|`brewgis/static/js/brew-gis-map.js`|Lit-based MapLibre GL JS web component (compiled via Vite + TypeScript)|
|`config/settings/base.py`|Base Django settings|
|`config/urls.py`|Root URLconf (admin, allauth accounts, workspace URLs, media, debug toolbar)|
|`config/celery_app.py`|Celery application definition|
|`pyproject.toml`|Tool configuration (pytest, coverage, mypy, ruff, djlint)|
|`docker-compose.local.yml`|Local development stack (6 services: django, postgres, tipg, martin, redis, celeryworker, celerybeat, flower)|
|`docker-compose.infra.yml`|Infrastructure-only stack (postgres, redis, tipg, martin) for host-mode dev|
|`docker-compose.production.yml`|Production stack (includes Traefik, Nginx)|
|`.pre-commit-config.yaml`|Pre-commit hook configuration (18 hooks)|
|`.sqlfluff`|SQLFluff configuration (postgres dialect, dbt templater, 119 line length)|
|`brewgis/dbt_project/dbt_project.yml`|dbt project config — 30 models, 4 macros, 4 seeds, ~80 vars|
|`brewgis/dbt_project/models/sources.yml`|Dynamic dbt sources (parcels, constraints, built_forms resolved via vars)|
|`brewgis/dbt_project/models/_schema.yml`|Schema tests for all documented models|
|`brewgis/dbt_project/models/env_constraint.sql`|Environmental constraint overlay engine|
|`brewgis/dbt_project/models/core_end_state.sql`|Core end-state allocation (central model all others depend on)|
|`brewgis/dbt_project/models/core_increment.sql`|Delta computation (end_state - base_canvas)|
|`brewgis/dbt_project/models/trip_distribution.py`|Python dbt model: batched numpy gravity model with Euclidean/network distance|
|`brewgis/dbt_project/models/mode_choice.py`|Python dbt model: multinomial logit mode split|

## Testing & QA
- **Framework:** pytest 8.3 + pytest-django + pytest-sugar + **Factory Boy** for fixtures + **pytest-bdd** for behavioral/e2e tests
- **Runner:** Django's `DiscoverRunner` (Django `TestCase` available)
- **Config:** `pyproject.toml` `[tool.pytest.ini_options]` — `--ds=config.settings.test --reuse-db --import-mode=importlib`, 300s timeout
- **Coverage:** `coverage` with `django_coverage_plugin`, includes `brewgis/**`, excludes `*/migrations/*` and `*/tests/*`, **60% threshold**
- **BDD:** Gherkin `.feature` files in `tests/e2e/features/`, `tests/review/features/`, `tests/features/` with pytest-bdd step definitions
- **Property-based:** Hypothesis for numerical invariants (mode choice shares sum to 1, trip conservation, etc.)
- **CI:** GitHub Actions runs `pre-commit` (all hooks) and `pytest` (test suite) in Docker on PRs/pushes to `master`/`main`

### Test Architecture

The test suite follows a taxonomy based on test weight and external dependencies:

|Marker|Purpose|Dependencies|When to use|
|---|---|---|---|
|`@pytest.mark.models`|Django model unit tests|`django.test.TestCase`, DB|Model methods, validation, defaults|
|`@pytest.mark.views`|View/HTTP tests|`django.test.TestCase`, DB, `self.client`|Form submissions, auth guards, redirects|
|`@pytest.mark.integration`|PostGIS/dbt-dependent tests|Running PostGIS instance, raw SQL fixtures|dbt model templates, DB queries, compute statistics|
|`@pytest.mark.slow`|Property-based or long-running|hypothesis, external services|Hypothesis fuzz tests, expensive model runners|
|`@pytest.mark.e2e`|Browser end-to-end tests|Playwright/browser, full stack|Full user workflows across Django + JS|
|`@pytest.mark.review`|UX design review tests|Playwright/browser|Visual/UX validation workflows|

**When to use `TestCase` vs plain classes:**
- Use `TestCase` (from `django.test`) when tests need database access via the ORM, `self.client` for HTTP, or Django transaction management.
- Use plain `unittest.TestCase` or bare `class TestX:` for pure functions (formulas, module registry, template string checks).
- Use `@pytest.mark.django_db` on individual test functions that need DB access but don't use `TestCase`.

**Database fixture strategy:**
- Tests run with `--reuse-db` (configured in `pyproject.toml`) — the test DB is created once and reused across runs.
- Raw SQL fixtures (creating/dropping tables in `setUp`/`tearDown`) are used for PostGIS-dependent integration tests.
- PostGIS extension must be enabled explicitly in raw SQL fixtures (`CREATE EXTENSION IF NOT EXISTS postgis`).
- Base canvas tables and geometry tables are created as PostGIS fixtures in `tests/conftest.py`.

**User fixtures and factories:**
- `tests/conftest.py` provides `user`, `workspace`, `scenario`, `layer`, `building_type`, `place_type`, `mix` fixtures using Factory Boy.
- `tests/factories.py` defines 12+ DjangoModelFactory classes: `UserFactory`, `WorkspaceFactory`, `LayerFactory`, `SymbologyConfigFactory`, `StyleClassFactory`, `ScenarioFactory`, `AnalysisRunFactory`, `PaintedCanvasFactory`, `BuildingTypeFactory`, `PlaceTypeFactory`, `PlaceTypeBuildingTypeMixFactory`.
- `brewgis/conftest.py` provides a separate `user` fixture via `UserModel.objects.create_user()` (no email). These may diverge — use `tests/conftest.py` fixtures for all pytest-based tests.

**E2E/BDD fixtures:**
- `tests/e2e/conftest.py`: session-scoped Chromium browser, per-test context/page, `logged_in_user`/`logged_in_page` helpers, automatic screenshot+DOM dump on failure.
- `tests/review/conftest.py`: mirrors e2e conftest with dedicated screenshots directory.
- `tests/features/conftest.py`: raw psycopg `db_conn`, `scenario_context` dict for step state, cleanup registry.

### Running Tests
```bash
docker compose -f docker-compose.local.yml run django pytest
# With coverage:
docker compose -f docker-compose.local.yml run django coverage run -m pytest
# Specific markers:
docker compose -f docker-compose.local.yml run django pytest -m models
docker compose -f docker-compose.local.yml run django pytest -m integration
```

## Gotchas & Patterns

### Database Migrations — First-time Setup

If the development database has pre-existing tables but no migration records:

```bash
# 1. Generate the initial migration (one-time):
docker compose -f docker-compose.local.yml run django python manage.py makemigrations workspace

# 2. Fake it on the existing database:
docker compose -f docker-compose.local.yml run django python manage.py migrate workspace --fake
```

Subsequent schema changes use normal `makemigrations` + `migrate` — no `--fake`.

### PostgreSQL Transaction Abort Handling

When a query fails, PostgreSQL aborts the entire transaction.  Catching the Python
exception *inside* a `transaction.atomic()` block prevents the rollback from
completing, leaving the connection in an `InFailedSqlTransaction` state.

**Correct pattern:**

```python
from django.db import transaction
from django.db.utils import DatabaseError

try:
    with transaction.atomic():
        risky_db_operation()
except DatabaseError:
    handle_gracefully()  # rollback completes before this runs
```

**Wrong pattern** (exception caught inside the `with` block prevents rollback):

```python
with transaction.atomic():
    try:
        risky_db_operation()
    except DatabaseError:
        pass  # PG connection is now broken
```

### Docker File Ownership

Docker containers run as root by default.  Files created inside containers
(migrations, staticfiles) are owned by root on the host.

**Fix ownership:**

```bash
docker compose -f docker-compose.local.yml run --rm django bash /app/scripts/fix-perms.sh
```

Or rebuild after adding `user: "${UID:-1000}:${GID:-1000}"` to the django service
in `docker-compose.local.yml` (already configured).

## Plan Review Checklist

Before implementing a plan, verify each item below. Plans written at a high level
often omit PostgreSQL/ORM mechanics that a Django developer must catch during
implementation.
- **SQL identifier quoting**: Any dynamic SQL that composes identifiers from
  user-controlled strings (even slugified) must double-quote them. PostgreSQL
  treats unquoted hyphens as minus operators.
  *Lesson from Phase 1c: hyphens in scenario slugs broke `DROP VIEW` queries.*
- **Schema/namespace lifecycle**: All `CREATE SCHEMA`, `CREATE TABLE`, or
  `CREATE VIEW` operations must handle existence with `IF NOT EXISTS`. Schema
  namespaced objects should own their schema creation.
  *Lesson from Phase 1c: `create_canvas_view` assumed the target schema existed.*
- **PostGIS extension in tests**: Test fixtures that create geometry tables must
  enable the extension explicitly. Django's test database starts from template,
  which may not include PostGIS.
  *Lesson from Phase 1c: `type "geometry" does not exist` on geometry table creation.*
- **Lifecycle hooks**: All lifecycle hooks (delete, cascade, signals) must be
  explicitly wired or documented as not needed. Describing behavior at a high
  level ("view is dropped on delete") without specifying the mechanism (model
  override vs. signal) is a gap.
  *Lesson from Phase 1c: plan described delete behavior without specifying mechanism.*
- **Placeholder values**: All placeholder values (`"TODO"`, `"CHANGEME"`,
  `DEFAULT_*` constants) should be tracked for future reconciliation.
- **Test fixture review**: When creating test fixtures that depend on external
  systems (PostGIS, Redis, external APIs), verify the test environment can
  satisfy those dependencies.
