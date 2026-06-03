# Repository Guidelines

## Project Overview

BrewGIS is a GIS Workspace for Urban Planners and Data Scientists — an open-source alternative to enterprise GIS platforms (ArcGIS, Carto). It provides a batteries-included, Docker-based workspace for managing geographic data, creating map layers, and running scenario-based urban planning analysis. Built on Django 6.0 with PostGIS, SQLMesh (migrated from dbt), dlt for data ingestion, and Dagster for orchestration.

**License:** GPLv3

## Architecture & Data Flow

```
User Browser                    Docker Compose Stack
     │                                │
     ├─ Auth ──► django-allauth       │
     ├─ Admin ─► Django Admin         │
     ├─ Dynamic HTML ─► htmx 2.0      │
     ├─ Map ─► MapLibre GL JS (Lit)   │
     │          │                     │
     │          ▼                     │
     │      Vector Tiles ◄── tipg ◄───┘
     │                   ◄── martin ◄─└── PostGIS
     ▼                                ▼
  Django (config/)              Redis ◄── Celery Worker (async tasks)
     │                                 │
     └── brewgis.workspace ────────────┘
              │
              ├─ Models: 24 classes (Workspace, Layer, Scenario, PaintedCanvas, etc.)
              ├─ Views: 27 modules (~75 URL patterns)
              ├─ SQLMesh: ~69 models (67 SQL, 2 Python), 39 audits, 8 macros, 20 seeds
              ├─ Dagster: 22 assets, 3 jobs, 3 schedules
              ├─ MCP server: 45+ tools (FastMCP stdio)
              ├─ dlt: 11 pipelines (Census, LEHD, POI, TIGER, NLCD, OSM, etc.)
              └─ GIS I/O: geopandas, rasterio, osmnx for data ingest
```

- **Request flow:** Browser → Django → View (FBV, FormView, CreateView) → Template (Bootstrap 5, htmx, Lit map component)
- **Map flow:** Template renders `<brew-gis-map>` Lit component → fetches vector tiles from tipg or Martin → serves tiles from PostGIS
- **Async flow:** Celery beat (DatabaseScheduler via django-celery-beat) dispatches periodic tasks → Redis broker → Celery workers execute tasks
- **GIS ingest:** User uploads GIS file → geopandas reads → `df.to_postgis()` via SQLAlchemy
- **Data pipeline (dlt → SQLMesh):** dlt pipelines load raw data → SQLMesh stages, transforms, runs analysis models → Dagster orchestrates
- **Paint/overrides:** `PaintedCanvas` model stores per-feature, per-column overrides with undo/redo via `PaintEvent` log. Canvas views dynamically LEFT JOIN paints onto base data.
- **MCP server:** FastMCP stdio server mirrors the view layer, exposing 45+ tools across 7 modules for AI assistant integration
- **Custom ruff rules:** `brewgis/_ruff_rules/rules.py` enforces project-specific anti-patterns inline (replacing most old pytestarch rules)

## Tool Boundaries — Who Does What

|Tool|Owns|Does NOT|
|---|---|---|
|**dlt**|Data ingestion/loading from external sources|Transformation, business logic|
|**SQLMesh**|Data transformation, testing, documentation, lineage, Python models|Ingestion, orchestration, UI|
|**Dagster**|Pipeline orchestration, scheduling, asset lineage|Transformation logic, ingestion logic|
|**Django**|Business rules, user experience, auth, UI routing|Data processing, ETL, transformation|
|**Python** (Django services)|Thin glue between tools, raw SQL ETL, API helpers|Reimplementing SQLMesh models, building SQL strings for transformation logic|
|**SQLMesh audits**|Data quality at pipeline boundaries (39 audit files)|Transformation logic|

Key rules:
- Data transformations live in SQLMesh SQL models. NOT in Python services.
- Use SQLMesh audits for row-level assertions; use `_schema.yml` column-level tests for `not_null`, `unique`, `non_negative`.
- SQLMesh Python models are for compute that SQL cannot express (numpy gravity model, multinomial logit). They are the exception, not the pattern.
- Django services call tools (SQLMesh runner, dlt pipelines, Dagster assets). They do not implement the data work.

## Key Directories

|Directory|Purpose|
|---|---|
|`brewgis/workspace/`|The sole Django app — models, views, tasks, templates, services, analysis modules, symbology, built_forms, MCP server, management commands|
|`brewgis/workspace/views/`|27 view modules split by feature (home, map, paint, symbology, analysis, import, filter, scenario, report, etc.)|
|`brewgis/workspace/models.py`|24 model classes (Workspace, Layer, SymbologyConfig, StyleClass, Scenario, PaintedCanvas, AnalysisRun, DataImportRun, POICache, PaintConstraint, MergeAudit, PaintEvent, ScenarioReport, County, DataSourceCategory, DataSource, LayerFilter, LayerGroup, ExternalMapService, Basemap, BaseCanvasColumn, BaseCanvas)|
|`brewgis/workspace/built_forms/models.py`|Built form sub-app: BuildingType, PlaceType, PlaceTypeBuildingTypeMix|
|`brewgis/workspace/tasks.py`|11 Celery tasks for data import, export, allocation, stitching, report generation|
|`brewgis/workspace/analysis/`|Pipeline orchestrator, module/layer registries, transport/food/equity preprocessors, network extractor, distance matrix|
|`brewgis/workspace/symbology/`|Map style generation (classifiers, generator, auto-config, legend, stats), color palettes|
|`brewgis/workspace/services/`|~34 service modules: base canvas ETL pipeline (1047 lines), schema, fetchers (Census, LEHD, POI, NLCD, assessor), spatial allocator, stitcher, imputation engine, built form classifier, paint constraints, scenario cloner, canvas view manager, staging model, SACOG migration tooling, `_db.py` (cached SQLAlchemy singleton)|
|`brewgis/workspace/mcp/`|MCP server: FastMCP stdio entrypoint, auth stub, 7 tool modules (workspace, scenario, layer, paint, analysis, data_import, reports)|
|`brewgis/workspace/dlt_pipelines/`|11 dlt pipeline modules: vida_buildings, raster, poi, lehd, census, nlcd, assessor, osm, tiger_bg, tiger_block|
|`brewgis/workspace/dagster/`|Dagster orchestration: 22 assets across 6 asset files, resources, 3 jobs, 3 schedules, check_provenance, typed configs|
|`brewgis/workspace/management/commands/`|9 management commands: setup_fresno_workspace, import_sacog_demo, populate_base_canvas, compare_sacog_basemap, onboard_geography, run_mcp, export_story_packet, restore_demo_db, download_fresno_demo|
|`brewgis/sqlmesh/`|SQLMesh project: ~69 models (67 SQL, 2 Python) across 10 subdirs, 8 macros, 20 seeds, 39 audits, config.py|
|`brewgis/templates/`|~50 Django templates: base.html, form.html, workspace_map.html (830 lines), workspace_detail.html, scenario_comparison.html, symbology/editor.html, import_center.html, partials, allauth overrides|
|`brewgis/templates/workspace/partials/`|htmx partial templates (data tables, layer groups, filters, symbology editor, basemap picker, etc.)|
|`brewgis/static/js/`|Bundled frontend: brew-gis-map.js (1.3MB Lit+MapLibre ESM from Vite+TS)|
|`brewgis/_ruff_rules/`|Custom Ruff lint rules for project-specific anti-patterns (replaces old pytestarch rules)|
|`brewgis/contrib/`|Additional django-only localflavor|
|`js/src/`|TypeScript source: Lit web component, PaintModeController, maplibre helpers, types, tests|
|`config/`|Django settings (single file), root URLconf, Celery app, WSGI with tile server proxying|
|`tests/`|~80 test files across 8 subdirectories|
|`tests/workspace/`|~56 test files covering models, views, paint, filters, allocation, fetchers, ETL, built forms, MCP, stats|
|`tests/dbt_math/`|SQLMesh parity tests: Python reference implementations with @deal + Hypothesis + SQLMesh integration tests|
|`tests/e2e/`|Playwright BDD e2e tests: 10 feature files, 12 page objects, session-scoped browser|
|`tests/review/`|UX design review tests: 13 feature files, screenshots, same POMs as e2e|
|`tests/features/` + `tests/isolation_orchestration/`|Shared BDD isolation feature file consumed at two abstraction levels (raw SQL vs Django model)|
|`_schema.yml`|Root-level column tests: not_null, unique, non_negative for 3 base_canvas models|

## Development Commands

All commands use Docker Compose. **No local venv workflow** — everything runs in containers. Host development mode (infra containers + host Django) is also supported.

### Quick Reference

```bash
make up           # Build and start full local stack (11 services)
make up-infra     # Start only infrastructure (PostGIS, Redis, tipg, Martin)
make down         # Stop and remove all containers
make shell        # Django shell
make migrate      # Apply database migrations
make makemigrations  # Create new database migrations
make check-migrations # Check for missing migrations (CI gate)
make clean-test-db   # Drop and recreate the test database
make check        # Full CI pipeline: lint + format-check + typecheck + test + dbt + soda
```

### Testing

```bash
make test                  # Run all tests
make test-fast             # Fast-fail + reuse-db
make test-parallel         # Parallel (excludes slow and e2e)
make test-models           # Model tests only
make test-views            # View/HTTP tests only
make test-integration      # PostGIS/SQLMesh-dependent tests
make test-e2e              # Playwright BDD end-to-end tests (sequential)
make test-review           # UX design review tests (Playwright)
make test-deal             # Deal property-based tests (sequential, DEAL_ENABLED=1)
make test-mcp              # MCP server tests
make test-soda             # Soda Core contract validation (legacy reference)
make test-all              # All tests sequentially
make coverage              # Tests with coverage report (60% threshold)
```

### Linting & Type Checking

```bash
make lint          # Ruff linter
make lint-custom   # Custom ruff anti-pattern checks
make lint-fix      # Ruff auto-fix
make format        # Ruff formatter
make format-check  # Check formatting without changes
make typecheck     # mypy strict mode
make typecheck-fast # basedpyright (faster local iteration)
make lint-dbt      # SQLFluff SQL lint (legacy)
```

### Host Development Mode

```bash
# 1. Start infra services
docker compose -f docker-compose.infra.yml up -d
# 2. Run Django on host (Python 3.12+)
python manage.py runserver
# 3. Run Celery on host
celery -A config.celery_app worker -l info
```

Host mode: `USE_DOCKER=no`, Django on `localhost:8000`, tile servers on `localhost:8081`/:3000`.

### Frontend Build

```bash
# Inside js/ directory:
npm run dev       # Vite dev server
npm run build     # tsc --noEmit + vite build → brewgis/static/js/brew-gis-map.js
npm run test      # vitest
```

## Code Conventions & Common Patterns

### Python Style

- **Linter:** Ruff with ~50 rule sets (F, E, W, C90, I, N, UP, ANN, ASYNC, S, B, DJ, SIM, PERF, FURB, LOG, RUF, custom brewgis rules)
- **Formatter:** Ruff format (replaces Black), double quotes, 119 character line length
- **Naming:** `snake_case` for functions/variables, `PascalCase` for classes
- **Imports:** `from __future__ import annotations` at module top using PEP 604 syntax. TYPE_CHECKING guards for circular imports. Ruff enforces isort with `force-single-line = true`.
- **Type annotations:** mypy strict mode with `disallow_untyped_defs`. PEP 604 union syntax (`str | None` instead of `Optional[str]`). Per-module exceptions for Alembic, SQLMesh, etc.
- **Keyword arguments for 3+ params:** Functions with three or more required parameters MUST be called with keyword arguments.
- **Template indent:** 2 spaces (djLint)
- **@deal contracts:** Preferred over conventional unit tests where ergonomic — encode invariants declaratively. Enabled via `DEAL_ENABLED=1`.

### Django Patterns

- **No REST Framework** — no DRF serializers or API views. django-ninja ModelSchema used minimally. MCP server uses Pydantic v2 schemas.
- **htmx** for dynamic HTML: form submissions (`hx-post`, `hx-target="this" hx-swap="outerHTML"`), partial updates via `HX-Redirect`, status polling (`hx-trigger="every 2s"`), lazy-loading panels (`hx-get="{% url ... %}" hx-target="#container" hx-swap="innerHTML"`)
- **Django partials** (`{% partialdef name %}` blocks) for htmx fragment swapping
- **Lit web component** for the map: `<brew-gis-map>` with properties for style, viewport, layers, mode (view/paint)
- **JSON in template attributes:** Use `{{ value|json_attr }}` filter — do NOT use raw `json.dumps()` in views for template consumption
- **django-allauth** for authentication (username-based, email optional verification)
- **django-celery-beat** DatabaseScheduler for periodic tasks
- **Tile server:** Both tipg and Martin run; `TILE_SERVER_BACKEND` setting controls tile URL generation
- **Settings** use `django-environ` for env-var-based configuration (12-factor)
- **View patterns:** FBVs (decorated with `@require_POST`/`@require_GET`/`@login_required`) dominant. CBVs (`CreateView`, `UpdateView`) reserved for built-forms CRUD.
- **EAV paint overrides:** `PaintedCanvas` model stores per-feature, per-column overrides. `PaintEvent` model logs changes with batch_id grouping for undo/redo.
- **Per-scenario SQL views:** `canvas_view_manager` dynamically creates views that LEFT JOIN paint overrides onto the base canvas.
- **Centralized DB connection:** `_db.py` is the sole module importing from `sqlalchemy` directly. All other modules use `get_engine()` and `text()` from it. Enforced by custom ruff rules + test_architecture.py.
- **No Protocol/adapter patterns** — codebase uses concrete classes with duck typing.

### Frontend

- **CSS framework:** Bootstrap 5.2.3 (via CDN)
- **Map library:** MapLibre GL JS v4.7 wrapped in LitElement web component
- **HTMX 2.0.4** for AJAX interactivity — no SPA framework
- **Lit component** (`<brew-gis-map>`): Light DOM rendering (`createRenderRoot` returns `this`, `delegatesFocus: true`). Properties: `map-style`, `viewport`, `layers`, `mode` (view/paint), `scenario-id`, `selection-mode` (click/box/polygon), `canvas-layer-id`, `transform-request`. Events: `mapready`, `mapidle`, `viewportchange`, `featureselected`, `paint-features-changed`.
- **PaintModeController**: Manages MapLibre feature selection with MapboxDraw polygon mode. Dispatches `paint-features-changed` CustomEvent.
- **JS build:** TypeScript source (js/src/) → tsc typecheck → vite build → brewgis/static/js/brew-gis-map.js (single ESM, no code-splitting, MapLibre + Lit inlined)
- **htmx CSRF:** Wired globally via `htmx:configRequest` event handler in base.html reading `<meta name='csrf-token'>`

### SQLMesh Patterns (replaced dbt)

- **Project:** `brewgis/sqlmesh/config.py` with Postgres dialect, `local` gateway
- **Materialization:** SQL views by default, Python models for numpy-based computation
- **Variables:** 60+ scenario parameters in config.py, overridden via SQLMesh plan variables
- **29 analysis models** in dependency graph: env_constraint → core → parallel downstream (water, energy, transport, fiscal, land, health, etc.) → scenario_summary
- **Python models (2):** `trip_distribution.py` (gravity model with BATCH_SIZE=2000), `mode_choice.py` (multinomial logit)
- **Macros (8):** allocation (compute_applied_acres, compute_dwelling_units, compute_population, etc.), spatial_ops (constraint_acres, apply_constraint), geometry (st_area_projected), delta_columns, utility, generic_tests
- **Seeds (20):** calibration_parameters, dasymetric_weights, test data for all pipeline stages (parcels, ACS, built_forms, constraints, NLCD, TIGER, etc.)
- **Audits (39):** SQL assertion files for data quality across all pipeline stages (spatial allocation, employment conservation, trip conservation, mode share sum, DU subtype validation, fiscal identity, correlation bounds, etc.)
- **Naming:** Lowercase snake_case SQL files, prefixed by module (core_, transport_, energy_, water_, fiscal_, etc.)

## Important Files

### Source

|File|Role|
|---|---|
|`brewgis/workspace/models.py`|24 model classes (Workspace, Layer, SymbologyConfig, StyleClass, Scenario, PaintedCanvas, AnalysisRun, DataImportRun, POICache, PaintConstraint, MergeAudit, PaintEvent, ScenarioReport, County, DataSourceCategory, DataSource, LayerFilter, LayerGroup, ExternalMapService, Basemap, BaseCanvasColumn, BaseCanvas)|
|`brewgis/workspace/built_forms/models.py`|Built form models: BuildingType (22 fields), PlaceType, PlaceTypeBuildingTypeMix|
|`brewgis/workspace/urls.py`|~75 URL patterns under `app_name='workspace'`|
|`brewgis/workspace/views/__init__.py`|Exports all 27 view modules|
|`brewgis/workspace/tasks.py`|11 Celery shared tasks (census fetch, LEHD fetch, POI fetch, raster fetch, spatial allocation, column stitching, report generation, building type export, plus helpers)|
|`brewgis/workspace/admin.py`|Admin registrations for 8 models (Workspace, Scenario, AnalysisRun, PaintedCanvas, PaintConstraint, DataSourceCategory, DataSource, POICache)|
|`brewgis/workspace/palettes.py`|Color palette registry: QUALITATIVE, SEQUENTIAL, DIVERGING palettes + helpers|
|`brewgis/workspace/templatetags/workspace_tags.py`|5 custom template filters: json_attr, model_verbose_name, analysis_status_badge, report_status_badge, dictlookup|
|`brewgis/workspace/analysis/module_registry.py`|Single source of truth for 29 analysis modules: dependency graph, output table templates, dbt select patterns, human labels|
|`brewgis/workspace/mcp/server.py`|FastMCP stdio server entrypoint with 7 tool modules|
|`brewgis/workspace/dagster/definitions.py`|Top-level Dagster Definitions wiring all 22 assets, resources, 3 jobs, 3 schedules|
|`brewgis/workspace/dlt_pipelines/__init__.py`|Exports run_* functions for 11 dlt pipelines + source definitions|
|`brewgis/workspace/services/_db.py`|Cached SQLAlchemy engine singleton (functools.lru_cache)|
|`brewgis/workspace/services/base_canvas_pipeline.py`|1047-line 11-step ETL pipeline (raw SQL with SQL injection quoting)|
|`brewgis/sqlmesh/config.py`|SQLMesh config: Postgres connector, 60+ scenario variables, gateway settings|
|`brewgis/_ruff_rules/rules.py`|Custom Ruff lint rules for project anti-patterns|
|`_schema.yml`|Root-level column tests (not_null, unique, non_negative)|

### Templates

|File|Role|
|---|---|
|`brewgis/templates/base.html`|Root template: Bootstrap 5.2.3 + htmx 2.0.4 CDN, CSRF meta tag, htmx:configRequest handler|
|`brewgis/templates/form.html`|Reusable htmx form pattern with {% partialdef form-content %}|
|`brewgis/templates/workspace_map.html`|Main map page (~830 lines) — Lit component + htmx panels (basemap picker, paint toolbar, history, legends)|
|`brewgis/templates/workspace/workspace_detail.html`|Workspace dashboard: scenario table, data catalog accordion, analysis modules, recent runs|
|`brewgis/templates/workspace/scenario_comparison.html`|Side-by-side scenario maps + Chart.js bar charts + PDF export|
|`brewgis/templates/workspace/symbology/editor.html`|Self-replacing htmx symbology editor (single/categorical/graduated types)|

### Configuration

|File|Role|
|---|---|
|`config/settings.py`|Single Django settings module — tri-mode (test/dev/prod) via DJANGO_TESTING/DJANGO_DEBUG env vars|
|`config/urls.py`|Root URLconf: admin, allauth, workspace app, debug toolbar|
|`config/celery_app.py`|Celery 5.4 app with DatabaseScheduler|
|`config/wsgi.py`|WSGI with Werkzeug ProxyMiddleware for tile server proxying|
|`pyproject.toml`|Tool config (pytest, coverage, mypy, ruff, djlint, basedpyright, vulture) — single source of truth|
|`Makefile`|~27 targets for Docker-based dev lifecycle|
|`.pre-commit-config.yaml`|19 hooks: linting, formatting, type checking, django-upgrade 6.0, codespell, custom checks|
|`package.json`|Frontend: lit, maplibre-gl, vite 6, vitest 3, typescript 5.7, eslint 9, prettier 3.5|
|`tsconfig.json`|Target ES2022, strict mode, experimentalDecorators (for Lit)|
|`vite.config.ts`|Builds js/src/index.ts → brew-gis-map.js ESM → brewgis/static/js/|
|`vitest.config.ts`|jsdom environment, globals: true, setup file|

### SQLMesh

|File|Role|
|---|---|
|`brewgis/sqlmesh/config.py`|Project config, ~60 vars, postgres dialect|
|`brewgis/sqlmesh/models/`|~69 models across 10 directories (staging, base_canvas, analysis, assessor, nlcd, comparison, python, seeds, tests, shared)|
|`brewgis/sqlmesh/macros/`|8 macro files (allocation, spatial_ops, geometry, delta_columns, utility, generic_tests, gen_scenario_blueprints)|
|`brewgis/sqlmesh/seeds/`|20 CSV seed files (calibration + test data)|
|`brewgis/sqlmesh/audits/`|39 audit SQL files for pipeline data quality|

## Runtime & Tooling Preferences

- **Python:** 3.12 (required)
- **Package manager:** pip via `requirements/*.txt` (base, local, production — 3-tier inheritance)
- **Runtime:** Docker (docker compose v2) — primary workflow. Host-mode available for breakpoints/hot-reload.
- **Database:** PostgreSQL 17 + PostGIS 3.5 + pgRouting (`psycopg2-binary` on server)
- **Cache/Queue:** Redis 6 (`django-redis`, `redis-py`, `hiredis`)
- **Transformation:** SQLMesh (migrated from dbt)
- **Orchestration:** Dagster (22 assets, typed configs, @dlt_assets)
- **Ingestion:** dlt (11 pipeline modules)
- **Linter/Formatter:** Ruff (`ruff` for linting, `ruff format` for formatting). 119 char line length.
- **Template linter:** djLint (profile: `django`, indent: 2 spaces)
- **Type checker:** mypy strict mode (CI, with django-stubs). basedpyright (fast local mode, `make typecheck-fast`).
- **CI:** GitHub Actions — pre-commit (19 hooks) + Docker-based pytest + SQLMesh plan/apply
- **Pre-commit hooks:** trailing-whitespace, end-of-file-fixer, check-json/toml/yaml/xml, debug-statements, ruff (--fix), ruff-format, djlint-reformat, prettier (JS/TS/JSON/YAML/CSS/MD), django-upgrade (target 6.0), eslint (JS/TS), tsc --noEmit, mypy, codespell, custom antic-pattern rules
- **Frontend build:** Vite 6 + TypeScript 5.7, compiled to ES module (lit + maplibre-gl inlined, 1.3MB)
- **JS tests:** vitest 3 with jsdom, mocked MapLibre backend

## Testing & QA

- **Framework:** pytest 8.3 + pytest-django + pytest-sugar + Factory Boy + pytest-bdd + pytest-playwright
- **Runner:** Django's DiscoverRunner. Config: `--ds=config.settings --reuse-db --import-mode=importlib`, 300s timeout
- **Coverage:** coverage with django_coverage_plugin, includes `brewgis/**`, excludes `*/migrations/*` and `*/tests/*`, **60% threshold**
- **BDD:** Gherkin `.feature` files in `tests/e2e/features/` (10), `tests/review/features/` (13), `tests/features/` (1) — shared across two abstraction levels
- **Property-based:** Hypothesis for numerical invariants in tests/dbt_math/ (mode choice shares sum to 1, trip conservation, SQL math parity vs Python reference)
- **@deal contracts:** Design-by-contract for function pre/post conditions. Used in test reference implementations and symbology classifiers. Enable with `DEAL_ENABLED=1`.
- **Factory Boy:** 10 factories in `tests/factories.py` (UserFactory, WorkspaceFactory, LayerFactory, SymbologyConfigFactory, StyleClassFactory, ScenarioFactory, AnalysisRunFactory, PaintedCanvasFactory, BuildingTypeFactory, PlaceTypeFactory, PlaceTypeBuildingTypeMixFactory)
- **pytestarch (architecture guards):** Only 2 rules remain in `tests/test_architecture.py` — most migrated to custom ruff rules in `brewgis/_ruff_rules/rules.py`
- **SQLMesh audits:** 39 SQL assertion files for pipeline data quality (replaces Soda)
- **Column schema tests:** `_schema.yml` at repo root for `not_null`, `unique`, `non_negative` on base_canvas models
- **Test taxonomy:**

|Marker|Purpose|Dependencies|
|---|---|---|
|`@pytest.mark.models`|Django model unit tests|DB|
|`@pytest.mark.views`|View/HTTP tests|DB, client|
|`@pytest.mark.integration`|PostGIS/SQLMesh-dependent tests|Running PostGIS|
|`@pytest.mark.slow`|Property-based or long-running|hypothesis, external services|
|`@pytest.mark.e2e`|Playwright BDD e2e tests|Full stack|
|`@pytest.mark.review`|UX design review tests|Playwright|

**Database fixture strategy:**
- Tests run with `--reuse-db` — test DB created once and reused.
- Raw SQL fixtures for PostGIS-dependent integration tests (CREATE EXTENSION IF NOT EXISTS postgis).
- Two conftest.py levels: `tests/conftest.py` (factory-backed fixtures, hypothesis profiles, deal config) vs `brewgis/conftest.py` (direct `create_user`, management-command oriented).

## Gotchas & Patterns

### PostgreSQL Transaction Abort Handling

When a query fails, PostgreSQL aborts the entire transaction. Catching the exception inside a `transaction.atomic()` block prevents the rollback from completing.

**Correct:**
```python
from django.db import transaction
from django.db.utils import DatabaseError
try:
    with transaction.atomic():
        risky_db_operation()
except DatabaseError:
    handle_gracefully()  # rollback completes before this runs
```

**Wrong** (exception caught inside prevents rollback):
```python
with transaction.atomic():
    try:
        risky_db_operation()
    except DatabaseError:
        pass  # PG connection is now broken
```

### Docker File Ownership

Files created inside containers (migrations, staticfiles) are owned by root. Fix with:
```bash
docker compose -f docker-compose.local.yml run --rm django bash /app/scripts/fix-perms.sh
```

### Plan Review Checklist

- **SQL identifier quoting:** Dynamic SQL composing identifiers from user-controlled strings must double-quote them. PostgreSQL treats unquoted hyphens as minus operators.
- **Schema/namespace lifecycle:** All `CREATE SCHEMA`, `CREATE TABLE`, `CREATE VIEW` operations must use `IF NOT EXISTS`.
- **PostGIS extension in tests:** Enable explicitly (`CREATE EXTENSION IF NOT EXISTS postgis`) — test DB template may not include it.
- **Lifecycle hooks:** Delete/cascade/signal behavior must be explicitly wired.
- **Route completeness:** Every new object/feature needs create, read, update, delete routes.
- **Auth & CSRF:** New views must be auth-guarded. htmx CSRF is wired via `htmx:configRequest` event in base.html.
- **Callsite audit:** Search for every `def` change's usages. Update all callers.
- **JSON in template attributes:** Use `{{ value|json_attr }}`, not raw `json.dumps()`.

### Anti-Patterns — What NOT to Do

1. **Python string-SQL transformation** — do not build transformation pipelines by concatenating SQL strings in Python services. Use SQLMesh models for all data transformations.
2. **Python reference implementations of SQLMesh models** — do not write Python code that reimplements SQLMesh model logic for testing. Use SQLMesh audits and `make test-dbt` instead.
3. **Django views/models for data processing** — Django owns business rules and UX. Data processing belongs in SQLMesh, dlt, or Dagster.
4. **Swallowing validation runtime errors** — never add a try/except in the context of running validation or loading data. If validation is broken, stop.
5. **Modifying imported data** — do not write Python code that manipulates imported data; that is the role of a SQLMesh model.
6. **Adhoc model creation** — only three things are allowed to create models: Django Migrations, SQLMesh & dlt. Python that tells a SQL cursor to make a table is not allowed.
7. **Unindexed GIS lookups** — never do intersectional joins on non-indexed geometries. If a join needs a different SRID, provide a materialized table projecting geometry onto a new indexed field.
8. **Low-fidelity types** — always import data at their highest fidelity. Never import geometries as text or a number as text.
9. **Column name with mixed types** — a column name represents a singular data type. A `parcel_id` is always a number, an `APN` is always text. Never reshape so an APN becomes a parcel_id.
10. **`{"success": False, "error": "..."}` return dicts instead of exceptions** — This pattern obfuscates failure locations. A bare `raise` produces a stack trace pointing at the exact line that failed. Only use error-return dicts when the failure is an expected business condition, every caller already handles it, and raising would force superfluous try/except at every call site.
