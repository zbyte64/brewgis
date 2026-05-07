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
              ├─ Models: Workspace, Layer
              ├─ Views: FormViews, CreateView, FBVs
              └─ GIS I/O: geopandas for file ingest, SQLAlchemy for PostGIS writes
```
- **Request flow:** Browser → Django → View (FormView/CreateView/FBV) → Template (Bootstrap 5, htmx for dynamic updates, Lit for map component)
|- **Map flow:** Template renders `<brew-gis-map>` Lit component → fetches vector tiles from tipg (`/tipg/collections/{schema}.{table}/tiles/{tms}/{z}/{x}/{y}`) or Martin (`/martin/{schema}.{table}/{z}/{x}/{y}`) depending on `TILE_SERVER_BACKEND` setting → tile server serves tiles from PostGIS
- **Async flow:** Celery beat (DatabaseScheduler via django-celery-beat) dispatches periodic tasks → Redis broker → Celery workers execute tasks
- **GIS ingest:** User uploads GIS file → `ReadGISFileView` → `geopandas.read_file()` → `df.to_postgis()` via SQLAlchemy
- **Dynamic UI:** htmx handles form submissions, partial page updates, and AJAX navigation without a JavaScript framework
|- **Analysis pipeline:** dbt models execute in dependency order: `env_constraint` → `core` (end_state) → `water_demand` / `energy_demand` (parallel). Module outputs are registered as Layers in the workspace.
|
|  |Module|Purpose|Output table|
|  |---|---|---|
|  |`env_constraint`|Environmental constraint overlay|`env_constraint_{scenario_id}`|
|  |`core`|End-state allocation + increment|`end_state_{scenario_id}`, `increment_{scenario_id}`|
|  |`water_demand`|Residential & non-residential water demand (L/yr)|`water_demand_{scenario_id}`|
|  |`energy_demand`|Residential & non-residential energy demand (kWh/yr)|`energy_demand_{scenario_id}`|

## Key Directories

|Directory|Purpose|
|---|---|
|`brewgis/workspace/`|The sole Django app — models, views, tasks, templates|
|`brewgis/workspace/views/`|View classes and functions, split by feature (home, map, create_layer, read_gis_file)|
|`brewgis/templates/`|Django templates: base.html, form.html, workspace_map.html, allauth overrides|
|`brewgis/templates/workspace/partials/`|htmx partial templates for dynamic updates|
|`brewgis/static/`|Static assets (CSS, JS, images, fonts)|
|`brewgis/static/js/brew-gis-map.js`|Lit-based MapLibre GL JS web component|
|`config/settings/`|Django settings: `base.py`, `local.py`, `production.py`, `test.py`|
|`config/`|Root URLconf (`urls.py`), WSGI, Celery app|
|`compose/`|Docker build contexts: `local/` and `production/` for each service|
|`requirements/`|Pip requirements: `base.txt`, `local.txt`, `production.txt`|
|`docs/`|Sphinx documentation source|
|`tests/`|Root-level test directory (cookiecutter scaffolding)|
|`.envs/.local/`|Environment files for Docker Compose local stack|
|`.github/workflows/`|CI pipeline (linter + pytest via Docker)|

## Development Commands

All commands use Docker Compose. **There is no local venv workflow** — everything runs in containers. Martin tile server runs alongside tipg in the local stack.
```bash
# Build and start the full local stack (Django + PostGIS + Redis + tipg + Martin + Celery + Flower)
docker compose -f docker-compose.local.yml up --build

# Run Django management commands
docker compose -f docker-compose.local.yml run django python manage.py <command>

# Run tests
docker compose -f docker-compose.local.yml run django pytest

# Run tests with coverage
docker compose -f docker-compose.local.yml run django coverage run -m pytest
docker compose -f docker-compose.local.yml run django coverage html

# Type checking
docker compose -f docker-compose.local.yml run django mypy brewgis

# Lint (via pre-commit, runs in CI)
pre-commit run --all-files

# Create superuser
docker compose -f docker-compose.local.yml run django python manage.py createsuperuser

# Check for missing migrations
docker compose -f docker-compose.local.yml run django python manage.py makemigrations --check

# Build docs
docker compose -f docker-compose.docs.yml build docs
|# SQLFluff lint dbt models
|docker compose -f docker-compose.local.yml run django sqlfluff lint brewgis/dbt_project/
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
- **Pre-commit hooks:** `trailing-whitespace`, `end-of-file-fixer`, `check-json`, `check-toml`, `check-yaml`, `debug-statements`, `django-upgrade` (target 5.0), `ruff`, `ruff-format`, `djlint-reformat-django`, `djlint-django`
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

### Django Patterns
- **No REST Framework** — no DRF serializers or API views. django-ninja `ModelSchema` is used for data serialization in the map FBV.
- **htmx** for dynamic HTML: form submissions, partial updates via `HX-Redirect` header
- **Lit web component** for the map: `<brew-gis-map>` element with properties for style, viewport, layers
- **django-allauth** for authentication (username-based, email required + verified)
- **Celery** uses JSON serialization, Redis broker, `django-celery-beat` DatabaseScheduler
|- **Tile server:** Martin (`ghcr.io/maplibre/martin`) and tipg (`ghcr.io/developmentseed/tipg`) both run; `TILE_SERVER_BACKEND` setting (`"tipg"` or `"martin"`) controls tile URL generation.
- **Settings** use `django-environ` for env-var-based configuration

### Frontend
- **CSS framework:** Bootstrap 5 (via CDN)
- **Map library:** MapLibre GL JS v4.7+ wrapped in a Lit web component
- **Dynamic HTML:** htmx 2.x for AJAX form submission, partial page updates, and redirect handling
- **JS pattern:** Lit-based web component for the map; inline `<script>` for minor enhancements. No build step or bundler.
- **CSS/JS files:** `project.css` (alert styling only), `project.js` (empty placeholder)

## Important Files

|File|Role|
|---|---|
|`brewgis/workspace/models.py`|Domain models: Workspace and Layer|
|`brewgis/workspace/urls.py`|Workspace URL patterns (home, upload, create_layer, workspace_map)|
|`brewgis/workspace/views/home.py`|Home page view listing workspaces|
|`brewgis/workspace/views/read_gis_file.py`|GIS file ingest pipeline (geopandas → PostGIS)|
|`brewgis/workspace/views/map.py`|Map view using django-ninja schemas, workspace-based|
|`brewgis/workspace/views/create_layer.py`|Layer creation using ModelForm + CreateView|
|`brewgis/templates/workspace/home.html`|Landing page with workspace list|
|`brewgis/templates/form.html`|Form template extending base.html, uses `_form_content.html` partial for htmx|
|`brewgis/templates/workspace_map.html`|MapLibre GL JS map template with `<brew-gis-map>` component|
|`brewgis/templates/workspace/partials/_form_content.html`|htmx partial for form content (re-rendered on validation errors)|
|`brewgis/templates/workspace/partials/_form_result.html`|htmx partial for success/error messages|
|`brewgis/static/js/brew-gis-map.js`|Lit-based MapLibre GL JS web component|
|`config/settings/base.py`|Base Django settings|
|`config/urls.py`|Root URLconf|
|`config/celery_app.py`|Celery application definition|
|`pyproject.toml`|Tool configuration (pytest, coverage, mypy, ruff, djlint)|
|`docker-compose.local.yml`|Local development stack|
|`docker-compose.production.yml`|Production stack (includes Traefik, Nginx)|
|`.pre-commit-config.yaml`|Pre-commit hook configuration|
|`.sqlfluff`|SQLFluff configuration (postgres dialect, dbt templater, 119 line length)
|`brewgis/dbt_project/models/core_end_state.sql`|Core end-state allocation dbt model|
|`brewgis/dbt_project/models/water_demand.sql`|Water demand dbt model (residential + non-residential, L/yr)|
|`brewgis/dbt_project/models/energy_demand.sql`|Energy demand dbt model (electricity + gas, kWh/yr)|

## Testing & QA
- **Framework:** pytest 8.3 + pytest-django + pytest-sugar
- **Runner:** Django's `DiscoverRunner` (Django `TestCase` available)
- **Config:** `pyproject.toml` `[tool.pytest.ini_options]` — `--ds=config.settings.test --reuse-db --import-mode=importlib`
- **Coverage:** `coverage` with `django_coverage_plugin`, includes `brewgis/**`, excludes `*/migrations/*` and `*/tests/*`
- **State:** Over 50 tests across model, view, and analysis modules. Key test files: `tests/test_water_demand.py`, `tests/test_energy_demand.py`, `tests/test_dbt_runner.py`, `tests/test_layer_registry.py`, `tests/test_analysis_run.py`, `tests/workspace/test_built_forms_models.py`, `tests/workspace/test_built_forms_views.py`.
- **CI:** GitHub Actions runs `pre-commit` and `pytest` in Docker on PRs/pushes to `master`/`main`

### Running Tests
```bash
docker compose -f docker-compose.local.yml run django pytest
# With coverage:
docker compose -f docker-compose.local.yml run django coverage run -m pytest
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
