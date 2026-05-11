# Brew GIS

GIS Workspace for Urban Planners and Data Scientists — an open-source alternative to enterprise GIS platforms such as ArcGIS and Carto.

[![Built with Cookiecutter Django](https://img.shields.io/badge/built%20with-Cookiecutter%20Django-ff69b4.svg?logo=cookiecutter)](https://github.com/cookiecutter/cookiecutter-django/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

License: GPLv3

---

## Overview

Brew GIS is a batteries-included, Docker-based workspace for managing geographic data, creating scenarios, performing analysis, and rendering maps with vector tiles. Built on Django 6.0 with PostGIS, MapLibre GL JS, and an integrated dbt analytics pipeline.

### Architecture

```
User Browser                    Docker Compose Stack
     |                                |
     |- Auth --> django-allauth       |
     |- Admin --> Django Admin        |
     |- Dynamic HTML --> htmx 2.0     |
     |- Map --> MapLibre GL JS (Lit)  |
     |          |                     |
     |          v                     |
     |      Vector Tiles <-- tipg <---+-- PostGIS
     |                   <-- martin <-+
     v                                |
  Django (config/)              Redis <-- Celery Worker (async tasks)
     |                                 |
     +-- brewgis.workspace ------------+
              |
              +-- Models: 20+ model classes
              +-- Views: 30+ view modules
              +-- Analysis: dbt pipeline (40 models, 17 macros)
              +-- GIS I/O: geopandas, SQLAlchemy, PostGIS
```

- **Request flow:** Browser -> Django -> View -> Template (Bootstrap 5, htmx for dynamic updates, Lit for map component)
- **Map flow:** `<brew-gis-map>` Lit component fetches vector tiles from tipg or Martin -> tile server serves from PostGIS
- **Async flow:** Celery beat dispatches periodic tasks -> Redis broker -> Celery workers
- **Analysis pipeline:** dbt models execute in dependency order; outputs registered as Layers

## Quick Start

### Prerequisites

- Docker & Docker Compose v2
- Make

### Development Setup

```bash
# Copy environment template
cp .env.example .env

# Build and start full local stack
make up
```

This starts: Django dev server, PostGIS, Redis, tipg, Martin, Celery worker, Celery beat, and Flower.

### Key Commands

```bash
make up              # Build and start full local stack
make up-infra        # Start only infrastructure (PostGIS, Redis, tipg, Martin)
make down            # Stop and remove all containers
make migrate         # Apply database migrations
make makemigrations  # Create new database migrations
make shell           # Django shell
make test            # Run all tests
make lint            # Ruff linter
make format          # Ruff formatter
make typecheck       # mypy strict mode
make check           # Full CI pipeline
```

See `AGENTS.md` for the full command reference.

### Host Development Mode

For hot-reload and breakpoint support:

```bash
cp .env.example .env
docker compose -f docker-compose.infra.yml up -d
python manage.py runserver     # Django on localhost:8000
celery -A config.celery_app worker -l info  # Celery on host
```

## Key Features

| Feature | Description |
|---------|-------------|
| **Map** | Lit-based MapLibre GL JS web component with vector tile rendering |
| **Paint** | Per-feature, per-column overrides with undo/redo via PaintEvent log |
| **Symbology** | Single, categorical, and graduated classification with auto-generation |
| **Analysis** | dbt-driven pipeline: transport, land use, energy, water, GHG, equity |
| **Import** | GIS file upload (geopandas), Census ACS, LEHD/LODES, OSM POIs |
| **Scenarios** | Side-by-side comparison with synchronized maps and Chart.js |
| **Built Forms** | Building types, place types, place-type/building-type mix allocation |
| **MCP Server** | AI assistant integration via Model Context Protocol |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 6.0, django-htmx, django-ninja, django-allauth |
| Database | PostgreSQL 17 + PostGIS 3.5 |
| Map | MapLibre GL JS 4.7+ via Lit web component |
| Tiles | tipg (OGC Features API) and Martin (MVT) |
| Async | Celery 5.4 + Redis 6 + django-celery-beat |
| Analytics | dbt-core 1.8+ (SQL + Python models with numpy/pandas) |
| Frontend | Bootstrap 5.2, htmx 2.0, Chart.js 4.4 |
| Templates | Django templates with django-template-partials |
| SEO/UX | django-allauth, crispy forms, role-based access |
| Tools | Ruff, mypy strict, pytest, Playwright, djLint, SQLFluff |

## Project Structure

```
brewgis/
  workspace/           # The sole Django app
    models.py          # 20+ model classes
    views/             # 30+ view modules
    services/          # 25+ service modules
    analysis/          # dbt pipeline orchestrator, module/layer registries
    symbology/         # Map style generation, classifiers, legends
    built_forms/       # BuildingType, PlaceType, allocation engine
    mcp/               # MCP server for AI assistant integration
  dbt_project/         # dbt project (40 models, 17 macros, 4 seeds)
  templates/           # Django templates + htmx partials
  static/js/           # Lit-based MapLibre GL JS web component
config/
  settings/            # Django settings (base, local, production, test)
  urls.py              # Root URLconf
  celery_app.py        # Celery app bootstrap
  wsgi.py              # WSGI config
tests/                 # pytest test suite with factory_boy
  workspace/           # Unit and integration tests
  e2e/                 # Playwright BDD end-to-end tests
  review/              # UX design review tests
docs/                  # Project documentation
```

## Documentation

- `AGENTS.md` — Full development guide, architecture, conventions, and command reference
- `docs/mcp.md` — MCP server reference for AI assistant integration
- `docs/data_tooling.md` — Postgres functions, dbt packages, Polars, SQLAlchemy, JupySQL
- `docs/jupysql.md` — Interactive PostGIS analysis with JupySQL
- `docs/design-review-checklist.md` — UX design review heuristics

## Testing

```bash
make test                  # All tests (excludes e2e)
make test-fast             # Fast-fail + reuse-db
make test-parallel         # Parallel execution
make test-models           # Model tests only
make test-views            # View/HTTP tests only
make test-integration      # PostGIS/dbt-dependent tests
make test-e2e              # Playwright BDD end-to-end tests
make test-dbt              # dbt seed + run + test
make coverage              # Tests with coverage report (60% threshold)
```

### Test Architecture

| Marker | Purpose |
|--------|---------|
| `@pytest.mark.models` | Django model unit tests |
| `@pytest.mark.views` | View/HTTP tests |
| `@pytest.mark.integration` | PostGIS/dbt-dependent tests |
| `@pytest.mark.slow` | Property-based or long-running |
| `@pytest.mark.e2e` | Playwright browser end-to-end tests |
| `@pytest.mark.review` | UX design review tests |

## Docker Services

| Service | Image | Purpose |
|---------|-------|---------|
| `django` | Custom | Django dev server (port 8000) |
| `postgres` | Custom | PostgreSQL 17 + PostGIS 3.5 |
| `redis` | `redis:6` | Cache/queue broker |
| `tipg` | `developmentseed/tipg` | OGC Features API tile server (port 8081) |
| `martin` | `maplibre/martin:v1.8` | MVT tile server (port 3000) |
| `celeryworker` | extends django | Celery task worker |
| `celerybeat` | extends django | Celery beat scheduler |
| `flower` | extends django | Celery monitoring (port 5555) |
