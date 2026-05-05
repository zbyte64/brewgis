# Repository Guidelines

## Project Overview

Brew GIS is a GIS Workspace for Urban Planners and Data Scientists — an open-source alternative to enterprise GIS platforms (ArcGIS, Carto). It provides a batteries-included, Docker-based workspace for managing geographic data, creating map layers, organizing them into scenarios, and rendering maps with vector tiles. Built on Django with cookiecutter-django scaffolding.

**License:** GPLv3

## Architecture & Data Flow

```
User Browser                    Docker Compose Stack
     │                                │
     ├─ Auth ──► django-allauth       │
     ├─ Admin ─► Django Admin         │
     ├─ Workflow UI ─► Viewflow       │
     ├─ Map ─► MapLibre GL JS         │
     │          │                     │
     │          ▼                     │
     │      Vector Tiles ◄── tipg ◄── PostGIS
     │                                │
     ▼                                ▼
  Django (config/)              Redis ◄── Celery Worker (async tasks)
     │                                 │
     └── brewgis.workspace ────────────┘
              │
              ├─ Models: Workspace, Layer, Scenario, ScenarioLayer, UserDefinedViews
              ├─ Views: FormViews, CreateView, FBVs, Viewflow viewsets
              ├─ Async: Celery @shared_task for UserDefinedViews execution
              └─ GIS I/O: geopandas for file ingest, SQLAlchemy for PostGIS writes
```

- **Request flow:** Browser → Django (via Whitenoise for static) → View (FormView/FBV/Viewflow) → Template (Bootstrap 5 + Viewflow layout)
- **Map flow:** Template renders MapLibre GL JS → fetches vector tiles from `/tipg/collections/{schema}.{table}/tiles/{tms}/{z}/{x}/{y}` → tipg serves tiles from PostGIS
- **Async flow:** Celery beat (DatabaseScheduler via django-celery-beat) dispatches periodic tasks → Redis broker → Celery workers execute tasks (e.g., `execute_user_define_views`)
- **GIS ingest:** User uploads GIS file → `ReadGISFileView` → `geopandas.read_file()` → `df.to_postgis()` via SQLAlchemy

## Key Directories

| Directory | Purpose |
|---|---|
| `brewgis/workspace/` | The sole Django app — models, views, viewsets, tasks, templates |
| `brewgis/workspace/views/` | View classes and functions, split by feature (map, create_layer, read_gis_file) |
| `brewgis/templates/` | Django templates: base.html, form.html, workspace_map.html, allauth overrides |
| `brewgis/static/` | Static assets (CSS, JS, images, fonts) |
| `config/settings/` | Django settings: `base.py`, `local.py`, `production.py`, `test.py` |
| `config/` | Root URLconf (`urls.py`), WSGI, Celery app |
| `compose/` | Docker build contexts: `local/` and `production/` for each service |
| `requirements/` | Pip requirements: `base.txt`, `local.txt`, `production.txt` |
| `docs/` | Sphinx documentation source |
| `tests/` | Root-level test directory (cookiecutter scaffolding) |
| `.envs/.local/` | Environment files for Docker Compose local stack |
| `.github/workflows/` | CI pipeline (linter + pytest via Docker) |

## Development Commands

All commands use Docker Compose. **There is no local venv workflow** — everything runs in containers.

```bash
# Build and start the full local stack (Django + PostGIS + Redis + tipg + Celery + Flower)
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

## Code Conventions

### Python Style
- **Linter:** Ruff with extensive rule set (F, E, W, C90, I, N, UP, ASYNC, S, B, DJ, SIM, PERF, RUF, and more — see `[tool.ruff.lint.select]` in `pyproject.toml`)
- **Formatter:** Ruff format (replaces Black)
- **Naming:** Standard Django conventions — `snake_case` for functions/variables, `PascalCase` for classes
- **String quotes:** Double quotes (Ruff default)
- **Line length:** 119 for Python, 119 for Django templates
- **Template indent:** 2 spaces (djLint)
- **Imports:** `from`-imports within app preferred. Ruff enforces isort via `I` rule with `force-single-line = true`

### Error & Edge Case Handling
- Two views (`CreateLayerView.form_valid`, `ReadGISFileView.form_valid`) return bare strings instead of `HttpResponse` — marked with `# TODO return a response`
- `Layer.key` is a `CharField` **without `max_length`** — this is likely a bug (Django will use `max_length=None` which is invalid; fix to e.g. `max_length=128`)

### Django Patterns
- **No REST Framework** — no DRF serializers or API views. django-ninja `ModelSchema` is used for data serialization in the map FBV.
- **Viewflow** provides the workflow UI layer: `Viewset` and `ModelViewset` classes in `viewsets.py`
- **django-allauth** for authentication (username-based, email required + verified)
- **Celery** uses JSON serialization, Redis broker, `django-celery-beat` DatabaseScheduler
- **Settings** use `django-environ` for env-var-based configuration

### Frontend
- **CSS framework:** Bootstrap 5 with Material Design components (via Viewflow). Template base extends `viewflow/base_page.html`
- **Map library:** MapLibre GL JS v4.7+
- **JS pattern:** Inline `<script>` in templates, no build step or bundler
- **CSS/JS files:** Minimal — `project.css` (alert styling only), `project.js` (empty placeholder)

## Important Files

| File | Role |
|---|---|
| `brewgis/workspace/models.py` | Domain models — **NOTE:** only Workspace and Layer defined. Scenario, ScenarioLayer, UserDefinedViews exist only in migrations |
| `brewgis/workspace/viewsets.py` | Viewflow URL routing — **NOTE:** these viewsets are not wired into `config/urls.py` |
| `brewgis/workspace/views/read_gis_file.py` | GIS file ingest pipeline (geopandas → PostGIS) |
| `brewgis/workspace/views/map.py` | Map view using django-ninja schemas |
| `brewgis/workspace/views/create_layer.py` | Layer/scenario creation logic |
| `brewgis/workspace/tasks.py` | Celery task for UserDefinedViews execution |
| `config/settings/base.py` | Base Django settings |
| `config/urls.py` | Root URLconf |
| `config/celery_app.py` | Celery application definition |
| `brewgis/templates/workspace_map.html` | MapLibre GL JS map template |
| `pyproject.toml` | Tool configuration (pytest, coverage, mypy, ruff, djlint) |
| `docker-compose.local.yml` | Local development stack |
| `docker-compose.production.yml` | Production stack (includes Traefik, Nginx) |
| `.pre-commit-config.yaml` | Pre-commit hook configuration |

## Testing & QA

- **Framework:** pytest 8.3 + pytest-django + pytest-sugar
- **Runner:** Django's `DiscoverRunner` (Django `TestCase` available)
- **Config:** `pyproject.toml` `[tool.pytest.ini_options]` — `--ds=config.settings.test --reuse-db --import-mode=importlib`
- **Factories:** factory-boy 3.3 installed, **no factories defined yet**
- **Coverage:** `coverage` with `django_coverage_plugin`, includes `brewgis/**`, excludes `*/migrations/*` and `*/tests/*`
- **State:** Only one test exists (`test_merge_production_dotenvs_in_dotenv.py`). `brewgis/workspace/tests.py` is an empty stub. No model or view tests written.
- **CI:** GitHub Actions runs `pre-commit` and `pytest` in Docker on PRs/pushes to `master`/`main`

### Running Tests
```bash
docker compose -f docker-compose.local.yml run django pytest
# With coverage:
docker compose -f docker-compose.local.yml run django coverage run -m pytest
```

## Known Issues / Work in Progress

1. **Missing models in `models.py`:** `Scenario`, `ScenarioLayer`, and `UserDefinedViews` exist only in migration `0001_initial.py` but are not declared in `models.py`. Django will still work (models are loaded from migration state), but this is an anti-pattern — the models should be restored to `models.py` before editing them.

2. **Viewsets not wired:** The Viewflow viewsets in `brewgis/workspace/viewsets.py` (`ImportDataViewset`, `CreateLayerViewset`, `ScenarioModelViewSet`) are not included in `config/urls.py`. The viewflow UI is unreachable.

3. **Broken conftest:** `brewgis/conftest.py` imports `brewgis.users.models.User` and `brewgis.users.tests.factories.UserFactory` — neither exists. The `user` fixture would fail if tests were run. This is leftover cookiecutter scaffolding.

4. **`Layer.key` CharField has no `max_length`:** `key = models.CharField()` will cause a migration error or use `max_length=None` which is invalid. Add `max_length`.

5. **Views return strings, not `HttpResponse`:** Both `ReadGISFileView.form_valid()` and `CreateLayerView.form_valid()` return bare strings, not `HttpResponse` objects. These are marked `# TODO return a response`.
