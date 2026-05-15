# Repository Guidelines

## Project Overview

Brew GIS is a GIS Workspace for Urban Planners and Data Scientists — an open-source alternative to enterprise GIS platforms (ArcGIS, Carto). It provides a batteries-included, Docker-based workspace for managing geographic data, creating map layers, and rendering maps with vector tiles. Built on Django 6.0 with cookiecutter-django scaffolding.

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
     │      Vector Tiles ◄── tipg ◄───┤
     │                   ◄── martin ◄─└── PostGIS
     ▼                                ▼
  Django (config/)              Redis ◄── Celery Worker (async tasks)
     │                                 │
     └── brewgis.workspace ────────────┘
              │
              ├─ Models: 22 model classes (Workspace, Layer, Scenario, etc.)
              ├─ Views: 38 view modules (~68 callbacks)
              ├─ Analysis: dbt pipeline (40 models, 17 macros, 4 seeds + custom tests)
              ├─ Dagster: orchestration assets + resources + jobs
              ├─ MCP server: 30+ tools (FastMCP stdio)
              └─ GIS I/O: geopandas for file ingest, SQLAlchemy for PostGIS writes
```

- **Request flow:** Browser → Django → View (FBV, FormView, CreateView) → Template (Bootstrap 5, htmx for dynamic updates, Lit for map component)
- **Map flow:** Template renders `<brew-gis-map>` Lit component → fetches vector tiles from tipg or Martin depending on `TILE_SERVER_BACKEND` setting → tile server serves tiles from PostGIS
- **Async flow:** Celery beat (DatabaseScheduler via django-celery-beat) dispatches periodic tasks → Redis broker → Celery workers execute tasks
- **GIS ingest:** User uploads GIS file → geopandas reads → `df.to_postgis()` via SQLAlchemy
- **Data pipeline (dlt → dbt):** dlt pipelines (Census, LEHD, POI, Raster) load raw data → Dagster orchestrates dbt models → scenario output summary tables
- **Analysis pipeline:** dbt models execute in dependency order: `env_constraint` → `core` (end_state) → `water_demand` / `energy_demand` → `land` / `ghg` / `transport_chain` (parallel). Module outputs are registered as Layers in the workspace
- **dbt orchestration:** AnalysisRun model tracks pipeline state (PENDING→RUNNING→SUCCESS/FAILURE). Celery tasks invoke `dbt run` per module with scenario-scoped `--vars`. Python dbt models (trip_distribution.py, mode_choice.py) run numpy-based computation inside dbt's Python model framework
- **MCP server:** FastMCP stdio server mirrors the view layer, exposing 30+ tools for AI assistant integration (workspace, scenario, layer, paint, analysis, data import, reports, job management)
- **Base canvas ETL:** Framework for spatial data ingestion with Protocol-based adapters (DemographicSource/EmploymentSource/LandUseSource), schema management, and validation
- **Data quality:** Soda Core contracts validate every pipeline stage (census, LEHD, POI, built forms, spatial allocation, column stitching)
- **Django orchestrates data tooling** (dbt runner, dlt pipelines, Dagster assets) but does not implement data processing logic.
- **Transparency** Never pass off a data failure as success or empty data. Fail early.

## Tool Boundaries — Who Does What

Coding agents must route work to the correct tool. This section defines ownership boundaries explicitly.

|Tool|Owns|Does NOT|
|---|---|---|
|**dlt**|Data ingestion/loading from external sources|Transformation, business logic|
|**dbt**|Data transformation, testing, documentation, lineage|Ingestion, orchestration, UI|
|**Dagster**|Pipeline orchestration, scheduling, asset lineage|Transformation logic, ingestion logic|
|**Django**|Business rules, user experience, auth, UI routing|Data processing, ETL, transformation|
|**Python** (Django services)|Thin glue between tools, protocol adapters, API helpers|Reimplementing dbt models, building SQL strings for ETL|
|**Soda**|Data quality contracts at pipeline boundaries|Transformation logic|

Key rules:
- Data transformations live in dbt SQL models. NOT in Python services.
- Use dbt's native `schema.yml` tests and singular tests for data quality assertions. Prefer over pytest-based data tests.
- dbt Python models are for compute that SQL cannot express (numpy gravity model). They are the exception, not the pattern.
- Django services call tools (dbt runner, dlt pipelines, Dagster assets). They do not implement the data work.


## Key Directories

|Directory|Purpose|
|---|---|
|`brewgis/workspace/`|The sole Django app — models, views, tasks, templates, services, analysis modules, symbology, built_forms, MCP server, management commands|
|`brewgis/workspace/views/`|38 view modules split by feature (home, map, paint, symbology, analysis, import, filter, scenario, report, etc.)|
|`brewgis/workspace/models.py`|22 model classes (Workspace, Layer, Scenario, PaintedCanvas, AnalysisRun, PaintConstraint, PaintEvent, MergeAudit, ScenarioReport, etc.)|
|`brewgis/workspace/tasks.py`|11 Celery shared tasks for analysis pipeline, data fetching, spatial allocation, reports|
|`brewgis/workspace/analysis/`|Pipeline orchestrator, dbt runner, module/layer registries, transport/food/equity preprocessors, network extractor, distance matrix|
|`brewgis/workspace/symbology/`|Map style generation (classifiers, generator, auto-config, legend, stats), color palettes|
|`brewgis/workspace/built_forms/`|Built form sub-app: BuildingType, PlaceType, PlaceTypeBuildingTypeMix models, allocation engine, fixture data|
|`brewgis/workspace/services/`|~34 service modules: base canvas adapters/ETL, census/LEHD/POI/NLCD fetchers, spatial allocator, stitcher, imputation engine, paint constraints, scenario cloner, canvas view manager, calibration registry, preflight, staging model, SACOG migration tooling|
|`brewgis/workspace/mcp/`|MCP server: FastMCP stdio entrypoint, auth stub, 7 tool modules (workspace, scene, layer, paint, analysis, data_import, reports)|
|`brewgis/workspace/management/commands/`|9 management commands: setup_fresno_workspace, import_sacog_demo, populate_base_canvas, compare_sacog_basemap, onboard_geography, run_mcp, export_story_packet, restore_demo_db, download_fresno_demo|
|`brewgis/dbt_project/`|dbt project: 40 models (36 SQL, 2 Python, 4 staging), 17 macros, 4 seeds, 8 custom tests|
|`brewgis/templates/`|Django templates: base.html, form.html, workspace_map.html, workspace_detail.html, scenario_comparison.html, partials|
|`brewgis/templates/workspace/partials/`|htmx partial templates for dynamic updates (data tables, layer groups, filters, symbology editor, etc.)|
|`brewgis/static/js/`|Bundled frontend: brew-gis-map.js (24KB Lit+MapLibre output from Vite+TS)|
|`brewgis/workspace/dagster/`|Dagster orchestration: assets (dbt, dlt, comparison, calibration, download, service), resources, jobs, schedules, sensors|
|`brewgis/workspace/dlt_pipelines/`|dlt data ingestion pipelines: tiger_block, tiger_bg, raster, census, lehd, poi|
|`brewgis/soda/`|Soda Core data quality: context, 9 validator functions, 9 contracts|
|`config/settings/`|Django settings: base.py, local.py, production.py, test.py|
|`config/urls.py`|Root URLconf: admin, allauth accounts, workspace app, debug toolbar|
|`config/celery_app.py`|Celery app bootstrap with DJANGO_SETTINGS_MODULE default|
|`tests/`|Root-level test directory with subdirectories per feature (workspace, e2e, review, features, dbt_math, isolation_orchestration, soda)|
|`js/src/`|TypeScript source for the Lit web component (brew-gis-map, paint-mode, maplibre-helpers, types)|

## Development Commands

All commands use Docker Compose. **There is no local venv workflow** — everything runs in containers. Host development mode (infra containers + host Django) is also supported.

### Quick Reference

```bash
make up           # Build and start full local stack
make up-infra     # Start only infrastructure services (PostGIS, Redis, tipg, Martin)
make down         # Stop and remove all containers
make shell        # Django shell
make migrate      # Apply database migrations
make makemigrations  # Create new database migrations
make check-migrations # Check for missing migrations (CI gate)
make clean-test-db   # Drop and recreate the test database
```

### Testing

```bash
make test                  # Run all tests (excludes e2e)
make test-fast             # Fast-fail + reuse-db
make test-parallel         # Parallel (excludes slow and e2e)
make test-models           # Model tests only
make test-views            # View/HTTP tests only
make test-integration      # PostGIS/dbt-dependent tests
make test-e2e              # Playwright BDD end-to-end tests
make test-review           # UX design review tests
make test-dbt              # dbt seed + run + test
make test-deal             # Deal property-based tests (sequential, DEAL_ENABLED=1)
make test-mcp              # MCP server tests
make test-soda              # Soda Core contract tests
make test-all              # All tests sequentially
make coverage              # Tests with coverage report (60% threshold)
make clean-review-screenshots  # Remove stale review screenshots
```

### Linting & Type Checking

```bash
make lint          # Ruff linter
make lint-fix      # Ruff auto-fix
make format        # Ruff formatter
make format-check  # Check formatting without changes
make typecheck     # mypy
make lint-dbt      # SQLFluff dbt SQL lint
make check         # Full CI pipeline: lint + format-check + typecheck + test + dbt + gx
```

### Host Development Mode

```bash
# 1. Copy env template
cp .env.example .env
# 2. Start infra services
docker compose -f docker-compose.infra.yml up -d
# 3. Run Django on host (requires Python 3.12 + deps)
python manage.py runserver
# 4. Run Celery on host
celery -A config.celery_app worker -l info
```

Key differences: `USE_DOCKER=no`, Django on `localhost:8000`, tile servers on `localhost:8081`/`:3000`, Redis on `localhost:6379`, Postgres on `localhost:5432`.

### Raw Docker Commands

```bash
docker compose -f docker-compose.local.yml run django python manage.py <command>
docker compose -f docker-compose.local.yml run django pytest [marker flags]
docker compose -f docker-compose.local.yml run django mypy brewgis
docker compose -f docker-compose.local.yml run django sqlfluff lint brewgis/dbt_project/
```

### Frontend Build

```bash
# Inside the js/ directory:
npm run dev       # Vite dev server
npm run build     # tsc --noEmit + vite build → brewgis/static/js/brew-gis-map.js
npm run test      # vitest
```

## Code Conventions & Common Patterns

### Python Style

- **Linter:** Ruff with 50+ rule sets (F, E, W, C90, I, N, UP, ANN, ASYNC, S, B, DJ, SIM, PERF, FURB, LOG, RUF, and more — see `pyproject.toml`)
- **Formatter:** Ruff format (replaces Black), double quotes, 119 character line length
- **Naming:** Standard Django conventions — `snake_case` for functions/variables, `PascalCase` for classes
- **Imports:** `from`-imports within app preferred; Ruff enforces isort with `force-single-line = true`
- **Type annotations:** mypy strict mode with `disallow_untyped_defs`. Per-module exceptions for Alembic, dbt, and similar files.
- **Keyword arguments for 3+ params:** Functions with three or more required parameters **MUST** be called with keyword arguments at all call sites.
- **Template indent:** 2 spaces (djLint)
- **@deal contracts** — pre/post condition design-by-contract style. Preferred over conventional unit tests wherever ergonomic, as they encode invariants closer to the logic they constrain. Enabled via `DEAL_ENABLED=1` env var.

### Django Patterns

- **No REST Framework** — no DRF serializers or API views. django-ninja ModelSchema is used for data serialization in the map FBV.
- **htmx** for dynamic HTML: form submissions, partial updates via `HX-Redirect` header, `hx-trigger="every 2s"` for status polling, self-replacing forms via `hx-target="this" hx-swap="outerHTML"`
- **Django partials** (`django-template-partials`): `{% partialdef name %}` blocks for htmx fragment swapping
- **Lit web component** for the map: `<brew-gis-map>` element with properties for style, viewport, layers, mode (view/paint)
- **django-allauth** for authentication (username-based, email optional verification)
- **Celery** uses JSON serialization, Redis broker, `django-celery-beat` DatabaseScheduler
- **Tile server:** Both tipg and Martin run; `TILE_SERVER_BACKEND` setting controls tile URL generation
- **Settings** use `django-environ` for env-var-based configuration
- **View patterns:** FBVs for map/read_gis_file, FormViews for upload, CreateViews with `HtmxResponseMixin` for model creation, auth-guarded via `@user_passes_test` or `LoginRequiredMixin`
- **JSON in template attributes:** Use the `{{ value|json_attr }}` filter (defined in `workspace_tags.py`) when embedding JSON in HTML attributes. Do **NOT** use raw `json.dumps()` in views for template consumption — pass Python objects and apply `json_attr` in the template.
- **Protocol-based adapters:** `DemographicSource`, `EmploymentSource`, `LandUseSource` as Protocols with Null implementations and real implementations (Census, LEHD, NLCD, OSM). Located in `services/base_canvas_adapters.py`.
- **EAV paint overrides:** `PaintedCanvas` model stores per-feature, per-column overrides with undo/redo via `PaintEvent` log (separate model with batch_id grouping).
- **Per-scenario SQL views:** `canvas_view_manager` dynamically creates views that LEFT JOIN paint overrides onto the base canvas.
- **Centralized database connection:** `brewgis/workspace/services/_db.py` is the sole module that imports from `sqlalchemy` directly. All other modules obtain engines via `get_engine()` and raw SQL via `text()` from `_db`. Enforced by `tests/test_architecture.py` (pytestarch rules).
- **HtmxResponseMixin** — used across CBVs for htmx-driven partial page updates.
- **Three-tier cascade imputation** — `ImputationEngine` with strategies: direct value, area-proportional, built-form default.
- **dbt Python models** — encapsulate compute-heavy transport logic (gravity model, MNL) with pure functions extracted for testability.
- **SACOG migration tooling** — dedicated service modules for v1→v3 column mapping, schema discovery, imputation validation.

### Frontend

- **CSS framework:** Bootstrap 5.2.3 (via CDN)
- **Map library:** MapLibre GL JS v4.7 wrapped in a Lit web component (`brew-gis-map.js`, ~24KB compiled bundle).
- **Dynamic HTML:** htmx 2.0.4 for AJAX form submission, partial page updates, and redirect handling.
- **Chart.js 4.4.7** on the scenario comparison page.
- **Lit component** (`<brew-gis-map>`): LitElement rendering into light DOM (`createRenderRoot` returns `this`), `delegatesFocus: true`. Properties: `map-style`, `viewport`, `layers`, `mode` (view/paint), `scenario-id`, `selection-mode` (click/box/polygon), `canvas-layer-id`, `transform-request`. Events: `mapready`, `mapidle`, `viewportchange`, `paint-features-changed`.
- **PaintModeController**: manages MapLibre feature selection with MapboxDraw polygon mode. Dispatches `paint-features-changed` CustomEvent with selected feature IDs.
- **JS pattern:** Lit web component compiled from TypeScript via Vite; inline `<script>` for minor enhancements. No bundler for non-map assets.
- **htmx patterns:**
  - Form submission: `hx-post` with `hx-target="#form-content" hx-swap="outerHTML"`, success → `HX-Redirect` header
  - Status polling: `hx-get="{% url 'analysis_status' %}" hx-trigger="every 2s" hx-swap="outerHTML"` on running/pending states
  - Self-replacing forms: `hx-target="this" hx-swap="outerHTML"` (symbology editor, bake forms)
  - Content loader: `hx-get="{url}" hx-target="#container" hx-swap="innerHTML"` (basemap picker, layer groups, legends)
  - Conditional loads: state selector `hx-get` triggers county checkbox partial load
  - CSRF via `htmx:configRequest` JavaScript event listener (wired in base.html)

### dbt Patterns

- **Project:** `brewgis/dbt_project/` with Postgres dialect, `brewgis` profile
- **Materialization:** View by default, table for computational models (transport, impact), Python models for numpy-based computation (trip_distribution, mode_choice)
- **Sources:** Dynamic `sources.yml` with table names/schemas resolved via dbt vars at runtime, loaded by Django
- **Vars:** 60+ scenario parameters defined in `dbt_project.yml` with defaults, overridden by AnalysisRun via `--vars`
- **Python models:** dbt's `python` materialization with numpy/pandas — batch processing (2000-origin batches for trip_distribution, BATCH_SIZE=2000 param). Pure functions extracted for testability (`_gravity_model`, `_multinomial_logit`).
- **Macros (17 total):** allocation (8: compute_applied_acres, compute_dwelling_units, compute_population, compute_households, compute_employment, compute_floor_area, classify_land_dev_category, distribute_employment), spatial_ops (2: constraint_acres, apply_constraint — PostGIS overlap/discount), geometry (1: st_area_projected), delta_columns (1: COALESCE diff for increment model), generic_tests (4: test_non_negative, test_proportion_sum, test_acres_consumed_le_gross, test_column_between), generate_schema_name (1: schema override), utility (3: summarize_metric, coalesce_zero, set_vars)
- **Seeds (4):** test_parcels.csv, test_base_canvas.csv, test_constraints.csv, test_built_forms.csv
- **Singular tests (4):** assert_energy_non_negative, assert_mode_share_sum, assert_fiscal_identity, assert_total_trips_conserved
- **Packages:** dbt-labs/dbt_utils, calogica/dbt_expectations, dbt_date (transitive)
- **Module organization:** staging (4 models) → env_constraint → core_allocation → transport_chain (trip_generation → trip_distribution.py → mode_choice.py → vmt → internal_capture) → land/energy/water/fiscal → GHG/health/stormwater → equity modules → scenario_summary
- **Naming:** Lowercase snake_case SQL files, prefixed by module (core_, env_constraint, transport_, energy_, water_, etc.)

## Important Files

### Source

|File|Role|
|---|---|
|`brewgis/workspace/models.py`|22 model classes: Workspace, Layer, SymbologyConfig, StyleClass, Scenario (enum ScenarioType), PaintedCanvas, AnalysisRun, DataImportRun, POICache, PaintConstraint (ConstraintOperator/ConstraintSeverity enums), MergeAudit, PaintEvent, ScenarioReport, County, DataSourceCategory, DataSource, LayerFilter, LayerGroup, ExternalMapService, Basemap|
|`brewgis/workspace/built_forms/models.py`|Built form models: BuildingType, PlaceType, PlaceTypeBuildingTypeMix (plus VintageChoices, StreetPatternChoices)|
|`brewgis/workspace/urls.py`|~70 URL patterns under namespace `workspace` — home, token auth, workspace CRUD, paint operations, symbology, built forms, analysis pipeline, import center, filters, layer groups, reports, external services, basemaps|
|`brewgis/workspace/views/__init__.py`|Exports all 38 view modules (~68 view callbacks)|
|`brewgis/workspace/tasks.py`|11 Celery tasks: export_building_types_task, run_dbt_module, run_preprocessor_and_dbt, handle_module_completed, run_census_fetch, run_lehd_fetch, run_poi_fetch, run_raster_fetch, run_spatial_allocation, run_column_stitching, generate_report_task (plus internal helpers)|
|`brewgis/workspace/admin.py`|Admin registrations for Workspace, Scenario, AnalysisRun, PaintedCanvas, PaintConstraint, DataSourceCategory, DataSource, POICache (plus built forms)|
|`brewgis/workspace/palettes.py`|Color palette registry: QUALITATIVE, SEQUENTIAL, DIVERGING palettes + helpers (get_palette, interpolate_color, sample_palette, etc.)|
|`brewgis/workspace/templatetags/workspace_tags.py`|Template filters: model_verbose_name, analysis_status_badge, report_status_badge, dictlookup, json_attr|
|`brewgis/workspace/mcp/server.py`|FastMCP stdio server entrypoint with 7 tool modules (workspace, scenario, layer, paint, analysis, data_import, reports)|
|`brewgis/workspace/dagster/definitions.py`|Top-level Dagster Definitions wiring all assets, resources, jobs, schedules, sensors|
|`brewgis/workspace/dlt_pipelines/__init__.py`|Exports run_* functions for 6 dlt pipelines (census, lehd, poi, raster, tiger_block, tiger_bg)|
|`brewgis/soda/__init__.py`|Soda Core context and 9 validator functions per pipeline stage (validate_base_canvas, validate_census_acs, validate_lehd, validate_poi, validate_nlcd, validate_synthetic_parcels, validate_spatial_allocation, validate_column_stitching, validate_built_form_export)|

### Templates

|File|Role|
|---|---|
|`brewgis/templates/base.html`|Root template with blocks (title, css, extrahead, javascript, bodyclass, body, main, content, modal, inline_javascript). Loads Bootstrap 5.2.3 + htmx 2.0.4. Global `htmx:configRequest` CSRF injection via `<meta name='csrf-token'>`.|
|`brewgis/templates/form.html`|Reusable form template with `{% partialdef form-content %}`, `hx-post="."`, `hx-target="#form-content"`, `hx-swap="outerHTML"`|
|`brewgis/templates/workspace_map.html`|Main map page (716 lines). Two modes (view/paint). Lit component + htmx for basemap picker, external services, layer groups, legends, filters, paint toolbar, paint history panel. JS event listeners for features changed and htmx swaps.|
|`brewgis/templates/workspace/workspace_detail.html`|Workspace dashboard (404 lines). Scenario management table (View/Edit/Publish/Share/Delete), data catalog accordion (Bootstrap collapse), analysis modules status list, recent runs.|
|`brewgis/templates/workspace/scenario_comparison.html`|Side-by-side scenario comparison with sync-group maps + Chart.js 4.4.7 bar charts (Population/Housing, Employment/Land)|
|`brewgis/templates/workspace/symbology/editor.html`|Symbology config editor (262 lines). Self-replacing form via `hx-target=this hx-swap=outerHTML`. Three types: single, categorical, graduated.|
|`brewgis/templates/workspace/analysis/status.html`|Analysis status poller. `{% partialdef analysis-status %}` with `hx-get` every 2s.|

### Configuration

|File|Role|
|---|---|
|`config/settings/base.py`|Base Django settings — PostgreSQL via DATABASE_URL, Redis broker, Celery config, tile server, upload limits, allauth, installed apps, middleware|
|`config/settings/local.py`|Dev overrides — debug toolbar, eager Celery (`CELERY_TASK_ALWAYS_EAGER=True`), locmem cache|
|`config/settings/test.py`|Test overrides — MD5 hasher, locmem email, token auth key (`test-token-key-dev-only`)|
|`config/settings/production.py`|Production overrides — SSL/HSTS, anymail, S3 static/media|
|`config/urls.py`|Root URLconf: admin, allauth accounts, workspace app (`/`), debug toolbar|
|`config/celery_app.py`|Celery app bootstrap with `DJANGO_SETTINGS_MODULE=config.settings.local`|
|`config/wsgi.py`|WSGI with werkzeug ProxyMiddleware for /tipg/ and /martin/ tile server proxying|
|`pyproject.toml`|Tool configuration (pytest, coverage, mypy, ruff, djlint, isort)|
|`.pre-commit-config.yaml`|Pre-commit hook configuration (14 hooks: ruff, djlint, sqlfluff, prettier 3.5, eslint 9.22, tsc --noEmit, mypy, django-upgrade 6.0, codespell, check-method-decorator)|
|`.sqlfluff`|SQLFluff config: postgres dialect, dbt templater, UPPER keywords, 119 line length|
|`package.json`|Frontend: lit, maplibre-gl, vite 6, vitest 3, typescript 5, eslint, prettier|
|`vite.config.ts`|Builds `js/src/index.ts` → `brew-gis-map.js` ES module → `brewgis/static/js/` with sourcemaps|

### dbt

|File|Role|
|---|---|
|`brewgis/dbt_project/dbt_project.yml`|Project config: 40 models, 17 macros, 4 seeds, 60+ vars across all modules|
|`brewgis/dbt_project/models/sources.yml`|3 dynamic sources (parcels, constraints, built_forms) resolved via dbt vars|
|`brewgis/dbt_project/models/_schema.yml`|30 models documented with 12 test types (not_null, unique, non_negative, column_between, relationships, accepted_values, proportion_sum)|
|`brewgis/dbt_project/models/trip_distribution.py`|Python dbt model: batched numpy gravity model with pure `_gravity_model` function|
|`brewgis/dbt_project/models/mode_choice.py`|Python dbt model: multinomial logit mode split with pure `_multinomial_logit` function|

### Docker

|File|Role|
|---|---|
|`docker-compose.local.yml`|Full local stack: django, postgres, redis, tipg, martin, celeryworker, celerybeat, flower, mcp, dagster-daemon, dagster-webserver|
|`docker-compose.infra.yml`|Infrastructure-only: postgres, redis, tipg, martin|
|`docker-compose.production.yml`|Production stack (includes Traefik, Nginx, dagster)|

## Runtime & Tooling Preferences

- **Python:** 3.12 (required)
- **Package manager:** pip via `requirements/*.txt` (no pipenv, no poetry, no conda). UV for local dev.
- **Runtime:** Docker (docker compose v2) — primary workflow. Host-mode available for breakpoints/hot-reload.
- **Database:** PostgreSQL 17 + PostGIS 3.5 + pgRouting (`psycopg2-binary` on server, `psycopg[c]` for local dev)
- **Cache/Queue:** Redis 6 (`django-redis`, `redis-py` 5.2.0, `hiredis` 3.0)
- **Linter/Formatter:** Ruff (`ruff` for linting, `ruff format` for formatting). 119 char line length.
- **Template linter:** djLint (profile: `django`, indent: 2 spaces)
- **SQL linter (dbt):** SQLFluff (postgres dialect, dbt templater, UPPER keywords)
- **Type checker:** mypy strict mode with `django-stubs` and `mypy_django_plugin`
- **CI:** GitHub Actions — pre-commit linting + Docker-based pytest + dbt seed/run/test + Soda validation
- **Pre-commit hooks:** trailing-whitespace, end-of-file-fixer, check-json/toml/yaml/xml, debug-statements, builtin-literals, case-conflict, docstring-first, detect-private-key, django-upgrade (target 6.0), ruff, ruff-format, djlint (reformat + lint), sqlfluff-lint, codespell, prettier (JS/TS/JSON/YAML/CSS/MD), eslint (JS/TS), tsc --noEmit, mypy, check-method-decorator
- **Frontend build:** Vite 6 + TypeScript 5.7, compiled to ES module in `brewgis/static/js/`
- **JS tests:** vitest 3 with jsdom

## Testing & QA

- **Framework:** pytest 8.3 + pytest-django + pytest-sugar + **Factory Boy** for fixtures + **pytest-bdd** for behavioral/e2e tests
- **Runner:** Django's `DiscoverRunner` (Django `TestCase` available)
- **Config:** `pyproject.toml` — `--ds=config.settings.test --reuse-db --import-mode=importlib`, 300s timeout
- **Coverage:** `coverage` with `django_coverage_plugin`, includes `brewgis/**`, excludes `*/migrations/*` and `*/tests/*`, **60% threshold**
- **BDD:** Gherkin `.feature` files in `tests/e2e/features/` (10), `tests/review/features/` (15), `tests/features/` (1) with pytest-bdd step definitions and Page Object Models
- **Property-based:** Hypothesis for numerical invariants (mode choice shares sum to 1, trip conservation, SQL math parity)
- **pytestarch (architecture guards):** `pytestarch` enforces import-level constraints in `tests/test_architecture.py`. Rules prevent regression to eliminated patterns (e.g., direct SQLAlchemy `create_engine` calls outside `brewgis.workspace.services._db`). Run with `pytest tests/test_architecture.py -v`.
- **@deal pre/post contracts:** `deal` library for design-by-contract. Use wherever ergonomic — superior to equivalently scoped unit tests because contracts are checked at call/return boundaries automatically and encode invariants declaratively. Conditionally enabled via `DEAL_ENABLED=1`.
- **Soda Core:** `brewgis/soda/` has 9 contracts validating ETL pipeline stages. Validator functions (validate_census_acs, validate_lehd, etc.) called within Celery tasks after dlt pipeline completion. Warning-only — never blocks, always logged.
- **Test-first for new features:** Every new view, model method, task, or template include **MUST** have a corresponding test. Guard-rail tests (validation, auth, CRUD completeness, edge cases) are not optional.
- **CI:** GitHub Actions runs `pre-commit` (all hooks) and `pytest` (test suite) plus `dbt seed + run + test` in Docker on PRs/pushes to `master`/`main`

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
- Tests run with `--reuse-db` — the test DB is created once and reused across runs.
- Raw SQL fixtures (creating/dropping tables in `setUp`/`tearDown`) are used for PostGIS-dependent integration tests.
- PostGIS extension must be enabled explicitly in raw SQL fixtures (`CREATE EXTENSION IF NOT EXISTS postgis`).
- Base canvas tables and geometry tables are created as PostGIS fixtures in `tests/conftest.py`.

**User fixtures and factories:**
- `tests/conftest.py` provides 10 factory-based fixtures (user, workspace, scenario, layer, symbology_config, building_type, place_type, mix, base_canvas_table, geometry_table).
- `tests/factories.py` defines 11 DjangoModelFactory classes: `UserFactory`, `WorkspaceFactory`, `LayerFactory`, `SymbologyConfigFactory`, `StyleClassFactory`, `ScenarioFactory`, `AnalysisRunFactory`, `PaintedCanvasFactory`, `BuildingTypeFactory`, `PlaceTypeFactory`, `PlaceTypeBuildingTypeMixFactory`.
- `brewgis/conftest.py` provides a separate `user` fixture via `UserModel.objects.create_user()` (no email). These may diverge — use `tests/conftest.py` fixtures for all pytest-based tests.

**E2E/BDD fixtures:**
- `tests/e2e/conftest.py`: session-scoped Chromium browser, per-test context/page, `logged_in_user`/`logged_in_page` helpers, automatic screenshot+DOM dump on failure.
- `tests/review/conftest.py`: mirrors e2e conftest with dedicated screenshots directory.
- `tests/features/conftest.py`: raw psycopg `db_conn`, `scenario_context` dict for step state, cleanup registry.
- `tests/isolation_orchestration/conftest.py`: mocked MODULE_TASKS (MagicMock), `default_workspace` fixture.

**Test directory layout:**
```
tests/
├── conftest.py              # Root: hypothesis, deal, fixtures
├── factories.py             # 11 Factory Boy factories
├── test_*.py                # ~15 root-level integration tests
├── workspace/               # ~60 files — models, views, paint, adapters, ETL, MCP
├── dbt_math/                # Property-based dbt SQL math: pure ref + SQL parity. Verification tool, NOT a pattern to extend — new models should use dbt native testing (schema tests, singular tests, dbt_expectations)
├── features/                # BDD — PostGIS-level isolation (psycopg)
├── isolation_orchestration/ # BDD — orchestration-level isolation (mocked Celery)
├── e2e/                     # Playwright BDD — 10 feature files, 7 POMs
├── review/                  # UX design review — 15+ feature files, 11 POMs
└── soda/                     # Soda Core contract validation (2 test files)
```

## Gotchas & Patterns

### Database Migrations — First-time Setup

If the development database has pre-existing tables but no migration records:

```bash
make makemigrations
docker compose -f docker-compose.local.yml run django python manage.py migrate workspace --fake
```

### PostgreSQL Transaction Abort Handling

When a query fails, PostgreSQL aborts the entire transaction. Catching the exception *inside* a `transaction.atomic()` block prevents the rollback from completing.

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

**Wrong** (exception caught inside blocks rollback):
```python
with transaction.atomic():
    try:
        risky_db_operation()
    except DatabaseError:
        pass  # PG connection is now broken
```

### Docker File Ownership

Files created inside containers (migrations, staticfiles) are owned by root on the host. Fix with:

```bash
docker compose -f docker-compose.local.yml run --rm django bash /app/scripts/fix-perms.sh
```

### Plan Review Checklist

Before implementing, verify:
- **SQL identifier quoting**: Any dynamic SQL composing identifiers from user-controlled strings must double-quote them. PostgreSQL treats unquoted hyphens as minus operators.
- **Schema/namespace lifecycle**: All `CREATE SCHEMA`, `CREATE TABLE`, `CREATE VIEW` operations must use `IF NOT EXISTS`.
- **PostGIS extension in tests**: Enable explicitly (`CREATE EXTENSION IF NOT EXISTS postgis`) — test DB template may not include it.
- **Lifecycle hooks**: Delete/cascade/signal behavior must be explicitly wired, not described at high level.
- **Route completeness**: Every new object/feature needs create, read, update, delete routes.
- **Auth & CSRF**: New views must be auth-guarded. htmx CSRF is wired via `htmx:configRequest` event in base.html.
- **Callsite audit**: Search for every `def` change's usages. Update all callers.
- **JSON in template attributes**: Use `{{ value|json_attr }}`, not raw `json.dumps()`.

### Anti-Patterns — What NOT to Do

These patterns have been eliminated or must be actively avoided. Do not reintroduce them.

1. **Python string-SQL ETL** — do not build ETL pipelines by concatenating SQL strings in Python services. Use dbt models for all data transformations.
2. **Python reference implementations of dbt SQL** — do not write Python code that reimplements dbt model logic for testing. Use dbt's native tests (schema.yml tests, singular tests) and Soda contracts instead.
3. **Django views/models for data processing** — Django owns business rules and UX. Data processing, transformation, and analytics belong in dbt, dlt, or Dagster.
4. **Swallowing validation runtime errors** - never add a try/except in the context of running validation, if running validation is broken then stop.