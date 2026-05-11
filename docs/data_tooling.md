# Data Tooling Reference

This document describes the data tooling additions from ROADMAP_5.

## Postgres Helper Functions (Phase 1)

Three Postgres functions were added via migration `0030_add_acres_and_clamp_functions`.

### `public.acres(geom geometry)`

Returns the area of a geometry in acres (1 acre = 4046.86 sq meters).

```sql
SELECT public.acres(geom) AS acres_gross FROM public.parcels LIMIT 10;
```

- **Language:** `sql` — inlined at call time, no procedural overhead
- **Immunity:** `IMMUTABLE PARALLEL SAFE` — safe for index expressions and parallel queries
- **Edge case:** Point/empty geometries return 0.0

### `public.sqm_to_acres(sqm double precision)`

Converts a numeric area in square meters to acres.

```sql
SELECT public.sqm_to_acres(10000.0);  -- 2.471 acres
```

### `public.intersection_acres(a geometry, b geometry)`

Returns the area of the intersection of two geometries, in acres. Returns 0.0 for disjoint or null geometries (never NULL).

```sql
SELECT public.intersection_acres(p.geom, c.geom) AS overlap_acres
FROM parcels p, constraints c
WHERE ST_Intersects(p.geom, c.geom);
```

### `public.clamp_non_negative(val double precision)`

Returns `GREATEST(0.0, val)`. Documents intent ("clamp to non-negative") vs raw `GREATEST(0, ...)`.

```sql
SELECT public.clamp_non_negative(-5.0);  -- 0.0
SELECT public.clamp_non_negative(3.5);   -- 3.5
```

### When to use vs. inline

| Use the function | Inline the expression |
|---|---|
| Any new dbt model referencing area in acres | Single-use expression in a view (rare) |
| Any service-layer SQL computing overlap areas | Raw ST_Area for non-acre units (sqm, sqft) |
| Any non-negative clamping on computed values | Inside function definitions themselves |

## dbt Packages (Phase 2)

### `dbt_utils`

[dbt_utils](https://github.com/dbt-labs/dbt-utils) v1.3+ provides 40+ utility macros.

Key macros for this codebase:

| Macro | Use case |
|---|---|
| `surrogate_key` | Generate surrogate keys for increment/delta tables |
| `safe_add` / `safe_subtract` | Null-safe arithmetic |
| `haversine_distance` | Euclidean distance fallback for transport |
| `date_spine` | Date dimension generation |

### `dbt-expectations`

[dbt-expectations](https://github.com/calogica/dbt-expectations) v0.10+ provides generic test macros.

Key tests for this codebase:

| Test | Replaces |
|---|---|
| `expect_column_value_to_be_between` | `non_negative` + `column_between` custom tests |
| `expect_column_pair_values_A_to_be_greater_than_B` | `acres_consumed_le_gross` custom test |
| `expect_foreign_key_exists` | `relationships` with `field:` |
| `expect_multicolumn_sum` | `proportion_sum` custom test |

To install packages:

```bash
cd brewgis/dbt_project && dbt deps
```

### Project Macros (`utility.sql`)

Located at `brewgis/dbt_project/macros/utility.sql`.

| Macro | Purpose | Usage |
|---|---|---|
| `summarize_metric(ref_table, column)` | Generates a scalar SUM subquery | `{{ summarize_metric('core_end_state', 'population') }}` → `(SELECT COALESCE(SUM(population), 0) FROM ref(...)) AS total_population` |
| `coalesce_zero(expression)` | Null-safe default | `{{ coalesce_zero('acres_consumed') }}` → `COALESCE(acres_consumed, 0.0)` |
| `set_vars(names_to_defaults)` | Compress multiple var() calls | `{{ set_vars({'source_schema': 'public', 'parcel_table': 'parcels'}) }}` → one block vs 3+ lines |

## Polars in Data Pipelines (Phase 3)

[Polars](https://pola.rs) v1.0+ is available as an optional dependency for non-spatial DataFrame operations.

### Modules using Polars

| Module | What it does | Polars scope |
|---|---|---|
| `imputation_engine.py` | Three-tier cascade imputation | Accepts `pl.DataFrame` in addition to `pd.DataFrame` |

### Pandas fallback pattern

Every Polars-ported module follows the same pattern:

```python
try:
    import polars as pl
except ImportError:
    pl = None

# Later, in the method:
if pl is not None and isinstance(df, pl.DataFrame):
    return self._apply_polars(df, rules)
return self._apply_pandas(df, rules)
```

This guarantees the module works with or without Polars installed. The pandas path is the default.

### Adding a new Polars-ported module

1. Add the try/except import block
2. Write the Polars-native implementation alongside the pandas one
3. Gate the dispatch on `if pl is not None and isinstance(df, pl.DataFrame)`
4. Verify both paths with parity tests

## SQLAlchemy Core for Service SQL (Phase 4)

### When to use vs. raw cursors vs. Django ORM

| Approach | When to use |
|---|---|
| Django ORM | CRUD on model instances, admin views |
| SQLAlchemy Core | Dynamic DDL, parameterized schema operations |
| Raw cursors (`connection.cursor()`) | One-off queries, COPY, EXPLAIN, migration RunSQL |

### DDL constructor

```python
from sqlalchemy import DDL

ddl = DDL(
    "CREATE SCHEMA IF NOT EXISTS {schema}"
)
cursor.execute(ddl.statement.format(schema=quote_identifier(schema_name)))
```

Benefits:
- Parameters are bound positionally/nominally (no string concatenation)
- Identifier quoting is explicit (no hidden SQL injection vectors)
- Composable (DDL objects can be extended, tested, and reused)

Current usage:
- `canvas_view_manager.py`: `CREATE SCHEMA` and `DROP VIEW` use `DDL`

## JupySQL for Ad-hoc Analysis (Phase 5)

[JupySQL](https://jupysql.ploomber.io/) provides SQL magics (`%sql`, `%%sql`) for Jupyter notebooks.

### Setup

```bash
pip install -r requirements/local.txt  # includes jupysql
```

### Connection

```python
%load_ext sql
%sql postgresql://brewgis:brewgis@localhost:5432/brewgis
```

### Example Notebooks

| Notebook | Purpose |
|----------|---------|
| `notebooks/01_quick_stats.ipynb` | Scenario metrics overview |
| `notebooks/02_explore_layer.ipynb` | Column distributions and outliers |
| `notebooks/03_analysis_results.ipynb` | Compare scenario vs. base, export CSV |

See `docs/jupysql.md` for detailed usage.

## Verification

| Phase | Test coverage |
|---|---|
| 1 — Postgres Functions | `tests/workspace/test_sql_functions.py` (integration, needs PostGIS) |
| 2 — dbt Packages | Existing `test_dbt_schema.py` + `dbt test` after `dbt deps` |
| 3 — Polars | Existing `test_imputation_engine.py` covers pandas path; Polars path tested with `polars` installed |
| 4 — SQLAlchemy | `test_canvas_view_manager.py` covers DDL changes |
| 5 — JupySQL | Manual verification via notebooks |
