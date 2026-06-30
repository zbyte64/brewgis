---
name: sqlmesh
description: "SQLMesh is a data transformation framework that has state-aware, incremental-by-default execution, virtual data environments, and native Python/SQL co-existence."
---


## Architecture Overview

```
SQLMesh Project
├── config.yaml          # Project config (replaces dbt_project.yml)
├── models/              # SQL and Python model files
│   ├── core.sql         # SQL model with MODEL DDL
│   ├── trip_distribution.py  # Python model with @model decorator
│   └── seeds/           # SEED model CSV files
├── macros/              # Python macro files
├── audits/              # Custom audit .sql files
├── tests/               # Unit test .yaml files
└── seeds/               # Alternative seed location (when using $root)
```

### Running SQLMesh Commands

All SQLMesh commands run through the Docker django container. The project root is
`brewgis/sqlmesh/`, passed via `-p` flag:

```bash
# Full Docker invocation
docker compose -f docker-compose.local.yml run --rm django sqlmesh -p brewgis/sqlmesh/ <command>

# Convenience Makefile targets
make lint-sql          # sqlmesh lint
make sqlmesh-ui        # Launch SQLMesh browser UI
make sqlmesh-clean     # Drop all snapshots, fresh start
```

In code blocks below, `dc-run sqlmesh` is shorthand for the full Docker invocation.
Commands with a Make target are noted. All examples assume `-p brewgis/sqlmesh/`
(the project root) is already set.

## Core Concepts

### 1. MODEL DDL

Every SQL model starts with a `MODEL` DDL block. This is SQL — NOT Jinja, NOT YAML:

```sql
MODEL (
  name db.customers,        -- schema.model_name (becomes the view name)
  kind FULL,                 -- FULL | VIEW | INCREMENTAL_BY_TIME_RANGE | SEED | ...
  owner jane_doe,
  cron '@daily',
  grain customer_id,         -- primary key (for merge/upsert strategies)
  start '2024-01-01',        -- backfill start date
  audits (                   -- built-in or custom audits
    not_null(columns := (id, email)),
    unique_values(columns := (id))
  ),
  description 'Customer master data'
);

SELECT
  id::INT,
  name::TEXT,
  email::TEXT
FROM raw.customers;
```

**Key MODEL properties:**
- `name` — Required. Schema-qualified view name (e.g., `sushi.customers`). SQLMesh prefixes schemas in non-prod environments.
- `kind` — Defaults to `VIEW` for SQL, `FULL` for Python. Kinds: `FULL`, `VIEW`, `INCREMENTAL_BY_TIME_RANGE`, `INCREMENTAL_BY_UNIQUE_KEY`, `SEED`, `SCD_TYPE_2_BY_TIME`, `EMBEDDED`, `EXTERNAL`, `MANAGED`, `CUSTOM`.
- `cron` — Schedule for when the model should run (e.g., `@daily`).
- `grain` — Column(s) defining uniqueness in the output.
- `start` — Earliest date for backfill.
- `audits` — List of audit names, optionally with arguments.
- `dialect` — SQL dialect of the model (auto-detected from project default).
- `owner` — Point of contact.
- `tags` — Labels for organization.
- `description` — Registers as table comment in the warehouse.
- `column_descriptions` — Per-column comments.
- `blueprints` — **The killer feature** (see below).

### 2. Model Kinds

| Kind | Behavior | When to Use |
|---|---|---|
| `FULL` | Rebuilds entire table every run | Small tables, reference data |
| `VIEW` | Creates a view, no storage | Lightweight transforms, always fresh |
| `INCREMENTAL_BY_TIME_RANGE` | Only processes missing time intervals | Event/transaction data, large tables |
| `INCREMENTAL_BY_UNIQUE_KEY` | Upserts based on unique key | Slowly changing dimensions, entity updates |
| `SEED` | Loads from CSV file | Static reference data |
| `EMBEDDED` | Inlined into downstream queries (no physical table) | Subqueries used once |
| `EXTERNAL` | References a table not managed by SQLMesh | PostGIS tables, dlt-loaded data |
| `SCD_TYPE_2_BY_TIME` | Tracks historical changes with time ranges | Dimension tables with history |
| `CUSTOM` | User-defined materialization strategy | Advanced use cases |

### 3. External Models — Replaces `{{ source() }}` + `sources.yml`

Tables not managed by SQLMesh (e.g., PostGIS base canvas, dlt-loaded raw data) are declared as external models in a `schema.yaml` file:

```yaml
# schema.yaml
- name: raw_census
  tables:
    acs_block_group:
      columns:
        geoid: text
        total_pop: int
        geometry: geometry
    wac_block:
      columns:
        geoid: text
        c000: int
```

External models are then referenced directly in SQL models by their schema-qualified name. SQLMesh automatically infers the dependency.

Generate external model schemas from the database:
```bash
dc-run sqlmesh create_external_models
```

### 4. Blueprinting

Blueprinting lets a single SQL/Python model generate multiple concrete models from a template.

**Static blueprinting:**

```sql
MODEL (
  name @scenario_schema.@output_table,
  kind FULL,
  blueprints (
    (scenario_schema := scenario_1, output_table := core_end_state,
     parcel_table := parcels_sc1, constraint_table := constraints_sc1),
    (scenario_schema := scenario_2, output_table := core_end_state,
     parcel_table := parcels_sc2, constraint_table := constraints_sc2),
    (scenario_schema := scenario_3, output_table := core_end_state,
     parcel_table := parcels_sc3, constraint_table := constraints_sc3),
  )
);

SELECT
  p.id,
  p.geometry,
  c.constraint_type
FROM @{parcel_table} AS p
LEFT JOIN @{constraint_table} AS c ON p.id = c.parcel_id;
```

**Dynamic blueprinting via Python macro:**

```sql
MODEL (
  name @scenario_schema.core_end_state,
  kind FULL,
  blueprints @gen_scenario_blueprints()
);
```

```python
# macros/gen_scenario_blueprints.py
from sqlmesh import macro

@macro()
def gen_scenario_blueprints(evaluator):
    """Read scenarios from a control table and generate blueprint mappings."""
    # Could read from db, CSV, or API
    scenarios = [
        {"scenario_schema": "sc_1", "parcel_table": "parcels_sc1", ...},
        {"scenario_schema": "sc_2", "parcel_table": "parcels_sc2", ...},
    ]
    parts = []
    for s in scenarios:
        vars_str = ", ".join(
            f"{k} := {v}" for k, v in s.items()
        )
        parts.append(f"({vars_str})")
    return "(" + ", ".join(parts) + ")"
```

### 5. Virtual Data Environments → Native Scenario Isolation

SQLMesh environments provide isolated namespaces without data duplication:

```bash
# Create isolated dev environment for a scenario
dc-run sqlmesh plan dev_scenario_1

# Compare two scenarios directly
dc-run sqlmesh table_diff prod_scenario_1:prod_scenario_2

# Promote to production
dc-run sqlmesh plan prod
```

Under the hood, SQLMesh creates versioned physical tables (`sqlmesh__<schema>.<model>__<fingerprint>`) and environment-specific views (`<schema>__<env>.<model>`) that point to those tables. This means:

- Each scenario analysis run creates versioned tables
- Scenario comparison uses `table_diff` natively
- No data duplication between identical model versions
- Rollback is instant (view swap)

### 6. Audits

Audits run automatically after every model evaluation. Built-in audits include:

| Built-in Audit | dbt Equivalent |
|---|---|
| `not_null(columns := (...))` | `not_null` test |
| `unique_values(columns := (...))` | `unique` test |
| `accepted_values(column := x, values := (...))` | `accepted_values` test |
| `number_of_rows(threshold := N)` | Custom row-count test |
| `forall(criteria := (...))` | Arbitrary boolean expression checks |
| `at_least_one(columns := (...))` | At least one non-NULL value |
| `mutually_exclusive_range(columns := (...))` | Range overlap check |
| `sequential_values(columns := (...))` | No gaps in sequence |
| `satisfies_statement_has_output(statement := ...)` | Subquery returns no rows |
| `valid_uuid(columns := (...))` | UUID format validation |

Non-blocking variants exist for all: append `_non_blocking` (e.g., `not_null_non_blocking`).

**Audit layering strategy:**

BrewGIS uses two complementary audit levels:

1. **Model-level `audits` block** — runs after every model evaluation. Use for row-level invariants
   and cross-column business rules (e.g., aggregate conservation, fiscal identity).
2. **`_schema.yml` column-level tests** — declared at repo root. Use for structural constraints
   that every model of that name must satisfy (`not_null`, `unique`, `non_negative`).
   These are enforced by `check_schema.py` and serve as documentation.

Every `INCREMENTAL_BY_UNIQUE_KEY` model MUST include at minimum:

```sql
MODEL (
  name brewgis.assessor.my_model,
  kind INCREMENTAL_BY_UNIQUE_KEY (unique_key (apn), batch_size 100000),
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,))   -- comma in tuple is intentional
  )
);
```

And a corresponding entry in `_schema.yml`:

```yaml
- name: my_model
  columns:
  - name: apn
    tests:
    - unique
    - not_null
```

**Custom audits:**

Standalone audit files go in `brewgis/sqlmesh/audits/`. Use `@this_model` in the query,
NOT bare `@this` (which resolves to a different table in some SQLMesh versions).

```sql
-- audits/assert_employment_conserved.sql
AUDIT (
  name assert_employment_conserved,
  dialect postgres,
  defaults (tolerance := 0.01)
);
SELECT *
FROM @this_model
WHERE ABS(input_jobs - output_jobs) / NULLIF(input_jobs, 0) > @tolerance;
```

**Row-count audits for critical models:**

When a model has a known expected row range, add a bounded row-count audit to catch
load failures, duplicates, or upstream data issues before they propagate:

```sql
-- audits/assert_row_count_between.sql
AUDIT (
  name assert_row_count_between,
  dialect postgres
);
WITH actual AS (SELECT COUNT(*) AS cnt FROM @this_model)
SELECT cnt AS actual_rows
FROM actual
WHERE cnt < @min_rows OR cnt > @max_rows;
```

```sql
-- In model:
MODEL (
  name brewgis.assessor.parcel_dasymetric_weights,
  audits (
    not_null(columns := (apn)),
    unique_values(columns := (apn,)),
    assert_parcel_dasymetric_weights_row_count
  )
);
```

Where the specific audit encodes the expected range:

```sql
-- audits/assert_parcel_dasymetric_weights_row_count.sql
-- Sacramento County has ~510K parcels.
AUDIT (name assert_parcel_dasymetric_weights_row_count, dialect postgres);
WITH actual AS (SELECT COUNT(*) AS cnt FROM @this_model)
SELECT cnt AS actual_rows
FROM actual
WHERE cnt < 500000 OR cnt > 520000;
```

**UNIQUE APN audit:**

```sql
-- audits/assert_unique_apn.sql
AUDIT (name assert_unique_apn, dialect postgres);
SELECT apn, COUNT(*) AS copies
FROM @this_model
GROUP BY apn
HAVING COUNT(*) > 1
ORDER BY copies DESC
LIMIT 50;
```

**Dedup patterns:**

Deduplicate at two boundaries:

1. **Load boundary (Python)** — in dlt/fetcher pipelines, dedup before `to_postgis()`.
   For ArcGIS sources that may return multi-part parcels, keep the row with the most
   complete data (largest lotsize, most non-null columns, newest year_built):

```python
if dup_mask.any():
    parcels = parcels.sort_values(
        "lotsize", ascending=False
    ).drop_duplicates(subset="apn", keep="first")
```

2. **SQL model boundary** — when a JOIN could produce multiple rows per grain row,
   use `DISTINCT ON` with a deterministic pick:

```sql
-- Self-join dedup: pick one calibration row per APN
LEFT JOIN (
    SELECT DISTINCT ON (apn) apn, region_avg_sqft_per_unit, min_du
    FROM calibration
) c ON p.apn = c.apn
```

**Aggregate consistency audits:**

Verify that parent columns equal the sum of their sub-columns:

```sql
-- audits/assert_aggregate_consistency.sql
AUDIT (name assert_aggregate_consistency, dialect postgres);
SELECT parcel_id, emp_ret,
  COALESCE(emp_retail_services, 0) + COALESCE(emp_restaurant, 0)
    + COALESCE(emp_accommodation, 0) + COALESCE(emp_arts_entertainment, 0)
    + COALESCE(emp_other_services, 0) AS emp_ret_sum
FROM @this_model
WHERE ABS(emp_ret - emp_ret_sum) > 0.5;
```

**Correlation bounds audits:**

For model comparison/validation, audit that correlation coefficients between
BrewGIS output and reference data fall within acceptable ranges:

```sql
AUDIT (name assert_correlation_bounds, dialect postgres);
-- Tests Pearson r for each column pair, flags values outside [lower, upper]
SELECT * FROM correlation_results WHERE r < @lower_bound OR r > @upper_bound;
```

### 7. Unit Tests

YAML-based, can test the full query or individual CTEs:

```yaml
# tests/test_core_end_state.yaml
test_core_acreage_scaling:
  model: brewgis.core_end_state
  inputs:
    brewgis.parcels:
      rows:
        - parcel_id: 1
          gross_acres: 10.0
          geometry: "POINT(0 0)"
        - parcel_id: 2
          gross_acres: 5.0
    brewgis.constraints:
      rows:
        - parcel_id: 1
          constraint_type: wetland
          constraint_acres: 3.0
  outputs:
    query:
      rows:
        - parcel_id: 1
          net_acres: 7.0
        - parcel_id: 2
          net_acres: 5.0

  # Test specific CTE
  ctes:
    filtered_parcels:
      rows:
        - parcel_id: 1
        - parcel_id: 2
```

Generate tests automatically from live data:
```bash
dc-run sqlmesh create_test brewgis.core_end_state \
  --query brewgis.parcels "SELECT * FROM brewgis.parcels LIMIT 10"
```

Run tests:
```bash
dc-run sqlmesh test
```

### 8. Macros

SQLMesh macros are **NOT** string templating like Jinja. They build and modify
the *semantic representation* of the SQL query using sqlglot. This means macros
understand SQL structure — commas between SELECT fields, identifier quoting,
and expression context.

Two macro systems exist: **SQLMesh macros** (`@macro_name`) — preferred — and
**Jinja** (`{{ jinja_expr }}`). Use Jinja only when you need Python control flow
during parsing (rare).

#### 8a. Variable Types

SQLMesh has four variable scopes, resolved from most specific to least:

| Scope | Defined In | Precedence |
|---|---|---|
| **Local** | `@DEF(var, value)` in model | Highest |
| **Blueprint** | `blueprints ( ... )` in MODEL block | ↓ |
| **Gateway** | `gateways.<name>.variables` in config | ↓ |
| **Global** | `variables` key in config | Lowest |

**Global variables** in `config.py`:
```python
variables = {
    "default_srid": 4326,
    "projected_srid": 32611,
    "transport_impedance_exponent": 2.0,
}
```

Access with `@variable_name` or `@VAR('variable_name', default)`:
```sql
SELECT * FROM table WHERE srid = @default_srid
-- or with fallback
SELECT * FROM table WHERE srid = @VAR('missing_var', 4326)
```

Override at plan/run time:
```bash
dc-run sqlmesh plan --var fiscal_year 2025
```

**Local variables** with `@DEF`:

```sql
MODEL (
  name brewgis.my_model,
  kind FULL
);  -- semicolon required after MODEL statement for @DEF

@DEF(min_parcel_area, 0.01);   -- semicolon required after each @DEF
@DEF(max_density, 150.0);

SELECT *
FROM parcels
WHERE lot_size_acres >= @min_parcel_area
  AND du_per_acre <= @max_density;
```

`@DEF` placement rules:
1. Model statement MUST end with `;`
2. All `@DEF` MUST be between MODEL and the SQL query
3. Each `@DEF` MUST end with `;`

#### 8b. Identifier vs Literal Rendering

`@var` renders as a **string literal** (quoted). `@{var}` renders as an **identifier** (unquoted or dialect-quoted):

```sql
-- @var renders as string: SELECT 'col_name' FROM ...
SELECT @my_column FROM table;

-- @{var} renders as identifier: SELECT col_name FROM ...
SELECT @{my_column} FROM table;
```

Use `@{}` when embedding variables in column/table names:
```sql
SELECT @{prefix}_sqft, @{prefix}_acres FROM table;
```

Blueprint variables must distinguish carefully:
```sql
-- blueprint: (label := 'urban', col := area_sqft)
-- @label renders as string literal 'urban'
-- @{col} renders as identifier area_sqft
SELECT @label AS category, @{col} AS value FROM ...
```

#### 8c. Built-in Macro Operators

SQLMesh provides powerful operators that generate SQL structure, not just strings.

##### `@EACH` — Iterate over a list

Generate repeated SQL fragments. SQLMesh automatically inserts commas in SELECT.

```sql
-- Generate indicator columns for a list of built_form_keys
SELECT
    apn,
    @EACH(['detsf_sl', 'detsf_ll', 'attsf', 'mf2to4', 'mf5p', 'commercial'],
          key -> CASE WHEN built_form_key = key THEN 1 ELSE 0 END AS has_@key)
FROM parcel_dasymetric_weights;
```

Renders to:
```sql
SELECT
    apn,
    CASE WHEN built_form_key = 'detsf_sl' THEN 1 ELSE 0 END AS has_detsf_sl,
    CASE WHEN built_form_key = 'detsf_ll' THEN 1 ELSE 0 END AS has_detsf_ll,
    CASE WHEN built_form_key = 'attsf' THEN 1 ELSE 0 END AS has_attsf,
    -- ...
```

##### `@IF` — Conditional inclusion

```sql
SELECT
    parcel_id,
    @IF(@runtime_stage = 'evaluating', computed_value, NULL) AS dynamic_col
FROM ...
```

Most commonly used for conditional `post_statements`:
```sql
@IF(@runtime_stage = 'evaluating',
  CREATE INDEX IF NOT EXISTS idx_my_model_parcel_id_@snapshot_hash
  ON @this_model USING btree (parcel_id)
);
```

##### `@EVAL` — Compute values at render time

```sql
@DEF(base_year, 2024);
SELECT @EVAL(@base_year + 2) AS projection_year FROM ...  -- → 2026
```

##### `@REDUCE` — Combine items with a binary function

Build a WHERE clause from column names:
```sql
WHERE
  @REDUCE(
    @EACH([col1, col2, col3], x -> x IS NOT NULL),
    (x, y) -> x AND y
  )
-- Renders: WHERE col1 IS NOT NULL AND col2 IS NOT NULL AND col3 IS NOT NULL
```

##### `@FILTER` — Subset an array by condition

```sql
@FILTER([1, NULL, 3, NULL], x -> x IS NOT NULL)  -- → [1, 3]
```

##### `@STAR` — Dynamically select columns from a table

Select all columns except geometry, with a prefix:
```sql
SELECT
  @STAR(brewgis.assessor.parcel_dasymetric_weights, exclude := [geometry], prefix := 'dw_')
FROM brewgis.assessor.parcel_dasymetric_weights
```

##### `@GENERATE_SURROGATE_KEY` — Hash-based surrogate key

```sql
SELECT @GENERATE_SURROGATE_KEY(apn, data_year) AS surrogate_id FROM ...
-- Renders: MD5(CONCAT(COALESCE(CAST(apn AS TEXT), ...), '|', ...))
```

##### `@SAFE_ADD` / `@SAFE_SUB` — Null-safe arithmetic

```sql
-- Instead of: COALESCE(a, 0) + COALESCE(b, 0) + COALESCE(c, 0)
SELECT @SAFE_ADD(a, b, c) AS total
-- Returns NULL only if ALL operands are NULL
```

#### 8d. Inline Macro Functions with @DEF

Define reusable expressions directly in SQL without Python files:

```sql
MODEL (name brewgis.my_model, kind FULL);

@DEF(acres_to_sqft, acres -> @acres * 43560.0);
@DEF(net_density, (du, acres) -> CASE WHEN @acres > 0 THEN @du / @acres ELSE 0 END);

SELECT
    apn,
    @acres_to_sqft(gross_acres) AS gross_sqft,
    @net_density(dwelling_units, net_acres) AS du_per_acre
FROM parcels;
```

Multiple arguments use `(arg1, arg2)` syntax:
```sql
@DEF(pythag, (x, y) -> sqrt(pow(@x, 2) + pow(@y, 2)));
SELECT @pythag(side_a, side_b) AS hypotenuse FROM triangles;
```

**When to use inline @DEF vs Python macro:**

| Factor | Inline @DEF | Python @macro() |
|---|---|---|
| Complexity | Simple expressions | Multi-statement logic, DB queries |
| Reuse scope | Single model | Across models |
| Maintenance | Colocated with SQL | Separate file, importable |
| Testing | Not directly testable | Unit-testable Python |
| SQL generation | Limited to expressions | Full control via evaluator |

#### 8e. Python Macro Functions

For cross-model reuse, complex logic, or database access:

```python
# macros/allocation.py
from sqlmesh import macro

@macro()
def compute_dwelling_units(evaluator, acres: str, du_per_acre: str) -> str:
    """Compute dwelling units from density-adjusted acres."""
    return f"({acres}) * ({du_per_acre})"

@macro()
def classify_land_dev_category(
    evaluator, du_per_acre_expr: str, lot_size_expr: str
) -> str:
    """Classify land development category based on DU density."""
    return f"""
    CASE
        WHEN ({du_per_acre_expr}) > 20 THEN 'urban_core'
        WHEN ({du_per_acre_expr}) > 8  THEN 'urban'
        WHEN ({du_per_acre_expr}) > 2  THEN 'suburban'
        WHEN ({lot_size_expr}) > 40    THEN 'rural'
        ELSE 'undeveloped'
    END"""
```

Usage in SQL models:
```sql
SELECT
    parcel_id,
    @compute_dwelling_units(c.acres, c.du_per_acre) AS dwelling_units,
    @classify_land_dev_category(c.du_per_acre, c.lot_size_acres) AS land_dev_category
FROM computed c;
```

**Accessing evaluator context in macros:**

```python
@macro()
def my_macro(evaluator, ...):
    # Read global/gateway variables
    default_srid = evaluator.var('default_srid')

    # Get current environment name
    env = evaluator.locals.get('runtime_stage')

    # Access engine adapter for DB queries (rare)
    # result = evaluator.engine_adapter.fetchdf("SELECT ...")

    return f"..."
```

**Macro argument rules:**
- Arguments passed by position: `@my_macro(col_a, col_b)`
- Arguments passed by name: `@my_macro(col_a, my_arg := 'value')`
- After the first named argument, all subsequent ones must be named.
- Use `:=` for named arguments in SQL, NOT `=`.

#### 8f. Predefined Macro Variables

| Variable | Description | Example Output |
|---|---|---|
| `@start_ds` / `@end_ds` | Date range start/end | `'2024-01-01'` |
| `@start_dt` / `@end_dt` | Timestamp range | SQL TIMESTAMP |
| `@execution_ds` | Execution date | `'2024-01-01'` |
| `@execution_dt` | Execution timestamp | SQL TIMESTAMP |
| `@runtime_stage` | Current stage | `'evaluating'`, `'creating'`, `'auditing'`, etc. |
| `@this_model` | Qualified physical table name | `'"schema"."model"'` |
| `@gateway` | Current gateway name | `'local'` |
| `@start_epoch` / `@end_epoch` | Unix epoch seconds | `1704067200` |
| `@execution_epoch` | Execution Unix epoch | `1704067200` |

#### 8g. BrewGIS Macro Catalog

| Macro | File | Purpose |
|---|---|---|
| `@compute_applied_acres` | `allocation.py` | `acres × dev_pct × gross_net_pct` |
| `@compute_dwelling_units` | `allocation.py` | `acres × du_per_acre` |
| `@compute_population` | `allocation.py` | `du × household_size` |
| `@compute_households` | `allocation.py` | `du × (1 − vacancy_rate)` |
| `@compute_employment` | `allocation.py` | `acres × emp_per_acre` |
| `@compute_floor_area` | `allocation.py` | `acres × 43560 × far` |
| `@classify_land_dev_category` | `allocation.py` | CASE expression for density classification |
| `@distribute_employment` | `allocation.py` | Distribute total employment across sector mix |
| `@constraint_acres` | `spatial_ops.py` | Overlap area between parcel and constraint |
| `@apply_constraint` | `spatial_ops.py` | Developable acres after constraint discount |
| `@compute_allocation_weight` | `spatial_ops.py` | Area-weighted allocation factor |
| `@summarize_metric` | `utility.py` | Scalar subquery: `SUM(column) FROM ref_table` |
| `@coalesce_zero` | `utility.py` | `COALESCE(expr, 0.0)` |
| `@gen_scenario_blueprints` | `gen_scenario_blueprints.py` | Dynamic blueprint generation from DB |
| `@test_non_negative` | `generic_tests.py` | Audit: column ≥ 0 |
| `@test_proportion_sum` | `generic_tests.py` | Audit: proportions sum ≈ 1.0 |
| `@test_acres_consumed_le_gross` | `generic_tests.py` | Audit: acres_consumed ≤ area_gross |
| `@test_column_between` | `generic_tests.py` | Audit: column in [min, max] |
| `@st_area_projected` | `geometry.py` | Project geometry and compute ST_Area |
| `@delta_columns` | `delta_columns.py` | Generate delta expressions between two table aliases |

#### 8h. DRY Patterns to Adopt

**Pattern 1: Eliminate repeated column lists with @EACH**

Before (20+ repetitive lines):
```sql
SELECT
    COALESCE(emp_retail_services, 0) + COALESCE(emp_restaurant, 0) +
    COALESCE(emp_accommodation, 0) + COALESCE(emp_arts_entertainment, 0) +
    COALESCE(emp_other_services, 0) AS emp_ret_sum
```

After (one line, self-documenting):
```sql
@DEF(emp_retail_subsectors, [emp_retail_services, emp_restaurant, emp_accommodation,
                              emp_arts_entertainment, emp_other_services]);
SELECT
    @SAFE_ADD(@emp_retail_subsectors) AS emp_ret_sum
```

**Pattern 2: Use @SAFE_ADD/@SAFE_SUB instead of COALESCE chains**

Before:
```sql
COALESCE(a, 0) + COALESCE(b, 0) + COALESCE(c, 0) AS total
```

After:
```sql
@SAFE_ADD(a, b, c) AS total
```

**Pattern 3: Use @GENERATE_SURROGATE_KEY for composite keys**

Before:
```sql
apn || '_' || data_year::text AS composite_key
```

After:
```sql
@GENERATE_SURROGATE_KEY(apn, data_year) AS composite_key
```

**Pattern 4: Use @STAR for upstream column passthrough**

Before (manual column list that drifts from source):
```sql
SELECT
    a.parcel_id, a.apn, a.geometry, a.lot_size_acres, ...
FROM upstream a
```

After (always matches source schema):
```sql
SELECT @STAR(brewgis.assessor.parcel_dasymetric_weights, a, exclude := [geometry])
FROM brewgis.assessor.parcel_dasymetric_weights AS a
```

**Pattern 5: Extract magic numbers into @DEF at model top**

Before:
```sql
WHERE lot_size_acres > 0.15 AND du_per_acre BETWEEN 2.0 AND 40.0
```

After:
```sql
MODEL (name brewgis.my_model, kind FULL);

@DEF(min_lot_single_family, 0.15);
@DEF(min_urban_density, 2.0);
@DEF(max_suburban_density, 40.0);

SELECT ...
WHERE lot_size_acres > @min_lot_single_family
  AND du_per_acre BETWEEN @min_urban_density AND @max_suburban_density;
```

**Pattern 6: @EACH + @REDUCE for dynamic audit predicates**

```sql
-- Generate: WHERE col1 IS NOT NULL AND col2 IS NOT NULL AND ...
WHERE @REDUCE(
    @EACH(['apn', 'parcel_id', 'geometry', 'data_year'], c -> c IS NOT NULL),
    (x, y) -> x AND y
)
```

### 9. Python Models

```python
# models/trip_distribution.py
from sqlmesh import ExecutionContext, model
from sqlmesh.core.model.kind import ModelKindName
import numpy as np
import pandas as pd

@model(
    "brewgis.trip_distribution",
    kind=dict(
        name=ModelKindName.FULL,
    ),
    columns={
        "origin_id": "int",
        "destination_id": "int",
        "trips": "float",
    },
    audits=("not_null(columns := (origin_id, destination_id))",),
)
def execute(
    context: ExecutionContext,
    start: datetime,
    end: datetime,
    execution_time: datetime,
    **kwargs,
) -> pd.DataFrame:
    # Fetch upstream data
    productions = context.fetchdf("SELECT * FROM brewgis.trip_productions")
    attractions = context.fetchdf("SELECT * FROM brewgis.trip_attractions")
    distance_matrix = context.fetchdf("SELECT * FROM brewgis.distance_matrix")

    # Pure numpy computation (extracted for testability)
    result = _gravity_model(
        productions.values, attractions.values, distance_matrix.values,
        impedance_exponent=kwargs.get("transport_impedance_exponent", 2.0),
    )

    return pd.DataFrame(result, columns=["origin_id", "destination_id", "trips"])
```

### 10. Seeds

```sql
-- models/national_holidays.sql
MODEL (
  name reference.national_holidays,
  kind SEED (
    path 'national_holidays.csv',  -- relative to model file, or $root/seeds/...
    csv_settings (
      delimiter = "|"
    )
  ),
  columns (
    name VARCHAR,
    date DATE
  )
);
```

With pre/post-statements:
```sql
MODEL (name ref.holidays, kind SEED (path 'holidays.csv'));

-- pre-statements
ALTER SESSION SET TIMEZONE = 'UTC';

@INSERT_SEED();  -- marks where seed data is inserted

-- post-statements
ALTER SESSION SET TIMEZONE = 'PST';
```

### 11. Pre/Post Statements and ON_VIRTUAL_UPDATE

**Canonical index creation pattern (**`@snapshot_hash`** convention):**

Every non-VIEW model that is joined by downstream models MUST create indexes on its
join columns in `post_statements`. Use `IF NOT EXISTS` for idempotency and wrap with
`@IF(@runtime_stage = 'evaluating', ...)` to restrict execution to the data-population phase.

**Critical: `post_statements` are NOT re-executed on existing versioned tables.**

SQLMesh creates versioned physical tables (e.g. `<model>__<fingerprint>`). When a
model's SQL hasn't changed, SQLMesh reuses the existing versioned table and skips
`evaluate()` — which means `post_statements` (including `CREATE INDEX`) do NOT run
on that table again.

This has a critical consequence: if a GiST (or B-tree) index is missing from a
versioned table — because `post_statements` silently failed, were mis-configured,
or the table was cloned without indexes — **subsequent plans will NOT recreate it**.
The index stays missing until the model is restated (SQL change forces a new
fingerprint), the environment is cleaned with `sqlmesh clean`, or the index is
created manually.

**Mitigation:** Use the MCP service to find active versions of the table.
Query `pg_indexes` for the active versioned tables and `CREATE INDEX`
if missing.


**⬆ Index naming: use `@snapshot_hash` to avoid name collisions across versions**

SQLMesh creates multiple snapshot versions of the same model in one schema (e.g.
`assessor__sacog_assessor_parcels__962285576` and
`assessor__sacog_assessor_parcels__4277093331`). PostgreSQL's `IF NOT EXISTS` is
database-wide — it checks if the index **name** exists anywhere, not just on the
target table. Without unique names, the first snapshot version gets the index and
every subsequent version silently skips it because the name already exists.

**Always append `_@snapshot_hash` to every `CREATE INDEX` name.** The
`@snapshot_hash` macro extracts the 9-digit fingerprint from the physical table
name (defined in `brewgis/sqlmesh/macros/utility.py`).

The `@this_model` reference resolves to the versioned physical table. Use it
instead of the model FQN (views can't have indexes).


GiST index for geometry columns (spatial joins):

```sql
-- post_statements
CREATE INDEX IF NOT EXISTS idx_my_model_geometry_@snapshot_hash
ON @this_model USING GIST (geometry)
```

B-tree index for key columns (equality joins, GROUP BY, WHERE filters):

```sql
-- post_statements
CREATE INDEX IF NOT EXISTS idx_my_model_parcel_id_@snapshot_hash
ON @this_model USING btree (parcel_id)
```

B-tree index on columns used in downstream WHERE clause filters:

```sql
-- post_statements
-- indexes for columns used in downstream WHERE: parcel_acres_agriculture > 0
CREATE INDEX IF NOT EXISTS idx_core_end_state_parcel_acres_ag_@snapshot_hash
ON @this_model USING btree (parcel_acres_agriculture)
```

**Bridge-table indexes:** When a source model uses a different gateway (e.g., DuckDB),
the GiST index lives in the consumer (Postgres) model's `post_statements`. These
target an explicit table (not `@this_model`), so they do NOT use `@snapshot_hash`:

```sql
-- overture_land_use is DuckDB gateway, so geometry index lives here
CREATE INDEX IF NOT EXISTS idx_overture_land_use_bridge_geometry
ON brewgis.staging.overture_land_use USING GIST (geometry)
```

**INDEX + ANALYZE for freshly created indexes:**

```sql
CREATE INDEX IF NOT EXISTS idx_intersection_density_geometry_@snapshot_hash
ON @this_model USING GIST (geometry);
ANALYZE @this_model;
```

**Temporary index pattern (discouraged):**

```sql
-- Pre-statements: run before model query
CREATE INDEX IF NOT EXISTS idx_temp ON some_table(col)

SELECT ... FROM ...;

-- Post-statements: run after model query
DROP INDEX IF EXISTS idx_temp
```

Prefer permanent indexes in the referenced model's `post_statements` over temporary
indexes. Temporary indexes add DDL overhead to every model run and don't benefit
other consumers.

**ON_VIRTUAL_UPDATE:** Runs after schema views are created (e.g., for GRANT):

```sql
ON_VIRTUAL_UPDATE_BEGIN;
GRANT SELECT ON VIEW @this_model TO ROLE analyst_role;
ON_VIRTUAL_UPDATE_END;
```

## Performance Patterns

### 1. Precompute Transforms in CTEs

Never put `ST_Transform` or `ST_Area` inside a JOIN condition or WHERE clause —
it defeats GiST index pushdown. Precompute in a CTE:

```sql
-- BAD: ST_Transform in JOIN forces sequential scan
JOIN other ON ST_Intersects(ST_Transform(p.geom, 3310), other.geom)

-- GOOD: precompute in CTE, join on already-transformed column
WITH transformed AS (
    SELECT *, ST_Transform(geom, 3310) AS geom_3310 FROM parcels
)
SELECT ...
JOIN other ON ST_Intersects(other.geom, transformed.geom_3310)
```

Similarly, precompute `ST_Area` and projected geometry in a CTE to avoid per-row
recomputation for every parcel-building pair:

```sql
WITH precomputed AS (
    SELECT *, ST_Area(local_geometry) AS area_sqft
    FROM parcels
)
```

### 2. NOT MATERIALIZED CTE Hint

When a CTE is a thin wrapper around a large table (no aggregation, no DISTINCT),
mark it `AS NOT MATERIALIZED` so Postgres can push join filters into the table
scan instead of spilling the CTE to disk:

```sql
overture_lu AS NOT MATERIALIZED (
    SELECT ST_SetSRID(geometry, 4326) AS geometry, subtype, class
    FROM brewgis.staging.overture_land_use
)
```

### 3. Envelope Intersection for ORDER BY Tie-Breaking

`ST_Area(ST_Intersection(a.geom, b.geom))` is expensive — it computes the full
intersection polygon. When you only need an ordering (not the actual area value),
use bounding-box envelope intersection instead:

```sql
-- EXPENSIVE: full geometry intersection for every row
ORDER BY parcel_id, ST_Area(ST_Intersection(olu.geometry, u.geometry)) DESC

-- FAST: bounding-box intersection, no geometry computation
ORDER BY parcel_id,
  COALESCE(ST_Area(ST_Intersection(
    ST_Envelope(olu.geometry), ST_Envelope(u.geometry)
  )), 0) DESC
```

### 4. Fold Columns Upstream to Eliminate Redundant Joins

If model A does a spatial join to get columns X, Y, Z from model B, and model C
upstream of A also joins against B, fold those columns into model C. This turns
a spatial join in model A into a cheap key-based passthrough:

```sql
-- BEFORE: parcel_building_sqft_by_type does expensive spatial join to
-- overture_land_use to get Overture class-bucket columns

-- AFTER: fold 4 Overture class-bucket columns into parcel_building_footprints,
-- then parcel_building_sqft_by_type reads them via simple apn-keyed LEFT JOIN.
```

### 5. CROSS JOIN with Pre-Filtered Row → Avoid ROW_NUMBER OVER Trick

When joining every row of table A with a single "best" row from small table B,
a `CROSS JOIN` with a pre-filtered one-row CTE is much cheaper than
`LEFT JOIN … ON TRUE` + `ROW_NUMBER() OVER (PARTITION BY …)`:

```sql
-- BAD: N×M join with window function per row
FROM parcels ap
LEFT JOIN building_medians bm ON TRUE  -- N×M cross product
QUALIFY ROW_NUMBER() OVER (PARTITION BY ap.apn ORDER BY bm.parcel_count DESC) = 1

-- GOOD: pre-filter medians to one row, then CROSS JOIN (N×1)
best_medians AS (
    SELECT * FROM building_medians ORDER BY parcel_count DESC LIMIT 1
)
...
FROM parcels ap
CROSS JOIN best_medians bm
```

### 6. 3-Sigma Bounds on Cross Joins

When a cross join is unavoidable (e.g., z-score similarity matching), bound the
pairs with cheap pre-filters to eliminate most rows before the expensive math:

```sql
-- Before z-score comparison (expensive per pair), eliminate ~80-90% of pairs
-- using a 3-sigma lot-size bound
FROM target_parcels tp
CROSS JOIN source_parcels sp
WHERE ABS(tp.lot_size_acres - sp.lot_size_acres)
      <= 3 * (SELECT STDDEV(lot_size_acres) FROM source_parcels)
```

### 7. Two-Phase SELECT for Computed Columns

When a column is computed from other columns in the same SELECT, wrap the
computation in a subquery so Postgres computes it once, not per reference:

```sql
-- Column `weighted_intersect_area` depends on `intersect_area` computed in
-- the same level. Wrap in subquery to compute once.
SELECT
    i.*,
    i.intersect_area * COALESCE(i.emp_dasym_weight, 1.0) AS weighted_intersect_area
FROM (
    SELECT
        ST_Area(ST_ClipByBox2D(p.local_geometry, w.wac_envelope)) AS intersect_area,
        p.emp_dasym_weight,
        ...
    FROM parcel_with_weights p
    JOIN wac_prep w ON ST_Intersects(p.geometry, w.geometry)
) i
```

### 8. MERGE Redundant UNION ALL Branches

When multiple UNION ALL branches query the same base table with different filters,
merge them into a single LEFT JOIN pass:

```sql
-- BEFORE: 6 UNION ALL branches, each scanning the same ~510K parcels
SELECT apn, 'tier1' AS source FROM tier1
UNION ALL SELECT apn, 'tier2' FROM tier2
UNION ALL ...

-- AFTER: single LEFT JOIN on assessor_parcels with CASE-based classification
-- Knows which parcels were already classified via NOT EXISTS guards
SELECT
    ap.apn,
    CASE WHEN ... THEN 'detsf_sl' ... END AS built_form_key
FROM assessor_parcels ap
WHERE NOT EXISTS (SELECT 1 FROM already_classified ac WHERE ac.apn = ap.apn)
```

### 9. Avoid Self-Joins for Per-Group Lookups

When you need a per-APN calibration value from a small calibration table,
a self-join through the calibration table can produce duplicates if calibration
has multiple rows per APN. Guard with `DISTINCT ON`:

```sql
LEFT JOIN (
    SELECT DISTINCT ON (apn) apn, region_avg_sqft_per_unit, min_du
    FROM calibration
) c ON p.apn = c.apn
```

## Linter Rules

SQLMesh linter rules in `brewgis/sqlmesh/linter/rules.py` are auto-discovered and
run during `make lint-sql` (or `dc-run sqlmesh lint`) and `dc-run sqlmesh plan`. They prevent performance anti-patterns
before they reach production.

### NoTransformInJoinWhere

**Flags:** `ST_Transform` inside a JOIN condition or WHERE clause.

**Why:** Forces the query planner to compute the transform for every row,
defeating GiST index usage.

**Fix:** Pre-compute the transform into a CTE, then join/filter against the
already-transformed column.

### MissingGeometryIndex

**Flags:** Models with a `geometry`/`geography` column that lack a GiST index in
`post_statements`.

**Why:** Every downstream spatial join forces a sequential scan without the index.
Raw `CREATE INDEX` outside the MODEL block is dead code — SQLMesh never executes it.

**Exemptions:** VIEW models (can't have indexes), DuckDB gateway models.

### UnindexedJoin

**Flags:** JOIN conditions referencing columns from other SQLMesh models that lack
corresponding indexes on the referenced model.

Detects three join types:
- **Key joins** (`a.parcel_id = b.parcel_id`) — requires B-tree index on the
  referenced column.
- **Spatial joins** (`ST_Intersects(a.geom, b.geom)`, `a.geom && b.geom`) —
  requires GiST index on the geometry column.
- **Expression joins** (`LEFT(a.key, 4) = LEFT(b.key, 4)`) — warns that an
  expression index may be needed.

Skips CROSS JOIN, `ON TRUE`, LATERAL, dynamic table references (`@var`), and
external tables not managed by SQLMesh.

### UnindexedGroupBy

**Flags:** `GROUP BY` columns from other SQLMesh models that lack indexes on
the referenced model.

### UnindexedWhereClause

**Flags:** `WHERE` filter columns from other SQLMesh models that lack indexes on
the referenced model. Skips columns inside spatial functions (those are handled
by `UnindexedJoin`).

### Configuration

Linter rules are registered in `brewgis/sqlmesh/config.py` as `warn_rules`:

```python
linter = LinterConfig(
    warn_rules=[
        "NoTransformInJoinWhere",
        "MissingGeometryIndex",
        "UnindexedJoin",
        "UnindexedGroupBy",
        "UnindexedWhereClause",
    ],
    enabled=True,
)
```

Run lint (use Makefile target):
```bash
make lint-sql
# or directly:
dc-run sqlmesh lint
```

Run lint for a specific model:
```bash
dc-run sqlmesh lint brewgis.assessor.parcel_dasymetric_weights
```

## Configuration

### config.yaml

```yaml
project: brewgis
gateways:
  local:
    connection:
      type: postgres
      host: postgres
      port: 5432
      user: brewgis
      password: brewgis
      database: brewgis

default_gateway: local

model_defaults:
  dialect: postgres
  start: 2024-01-01
  cron: '@daily'

variables:
  default_srid: 4326
  projected_srid: 32611

plan:
  auto_categorize_changes:
    external: full  # Auto-detect breaking vs non-breaking

state:
  connection:
    type: postgres  # State DB (can be same as data warehouse)
    host: postgres
    port: 5432
    user: brewgis
    password: brewgis
    database: brewgis_state
```

### config.py (for dynamic configuration)

```python
from sqlmesh.core.config import (
    Config, ModelDefaultsConfig,
    PlanConfig, AutoCategorizationMode,
    GatewayConfig, ConnectionConfig,
)

config = Config(
    project="brewgis",
    gateways={
        "local": GatewayConfig(
            connection=ConnectionConfig(
                type="postgres",
                host="postgres",
                port=5432,
                user="brewgis",
                password="brewgis",
                database="brewgis",
            ),
            state_connection=ConnectionConfig(
                type="postgres",
                host="postgres",
                port=5432,
                user="brewgis",
                password="brewgis",
                database="brewgis_state",
            ),
        ),
    },
    model_defaults=ModelDefaultsConfig(
        dialect="postgres",
        start="2024-01-01",
    ),
)
```

## CLI Commands

All commands run through the Docker django container. Use `make lint-sql` for linting,
`make sqlmesh-ui` for the browser IDE, `make sqlmesh-clean` to reset state.

| Command | Purpose | dbt Equivalent |
|---|---|---|
| `dc-run sqlmesh plan [env]` | Apply local changes to environment | `dbt build` |
| `dc-run sqlmesh run [env]` | Evaluate missing intervals | `dbt run` |
| `dc-run sqlmesh test` | Run unit tests | `dbt test` |
| `dc-run sqlmesh audit` | Run audits for models | `dbt test --select` |
| `dc-run sqlmesh dag` | Render DAG as HTML | `dbt docs generate` |
| `dc-run sqlmesh ui` (or `make sqlmesh-ui`) | Interactive browser IDE | `dbt docs serve` |
| `dc-run sqlmesh evaluate <model>` | Evaluate a model and show results | `dbt show` |
| `dc-run sqlmesh fetchdf "SELECT ..."` | Run arbitrary SQL | `dbt run-operation` |
| `dc-run sqlmesh render <model>` | Render model SQL with variables | `dbt compile` |
| `dc-run sqlmesh format` | Format all SQL models | `sqlfluff fix` |
| `dc-run sqlmesh lint` (or `make lint-sql`) | Lint models | `sqlfluff lint` |
| `dc-run sqlmesh create_test <model>` | Auto-generate test fixture | N/A |
| `dc-run sqlmesh create_external_models` | Generate external model schemas | `dbt-generate-source` |
| `dc-run sqlmesh table_diff a:b` | Compare tables across environments | N/A (huge win) |
| `dc-run sqlmesh invalidate <env>` | Mark environment for cleanup | N/A |
| `dc-run sqlmesh clean` (or `make sqlmesh-clean`) | Clear cache and artifacts | `dbt clean` |
| `dc-run sqlmesh info` | Project info + connection test | `dbt debug` |

**Key plan options:**
```bash
dc-run sqlmesh plan dev_scenario_1 \
  --start 2024-01-01 \      # Limit backfill range
  --end 2024-12-31 \
  --skip-tests \             # Skip tests for speed
  --auto-apply \             # Don't prompt
  --forward-only \           # No backfill, use existing table
  --select-model "+core_end_state"  # Only specific models
```

## Gotchas and Anti-Patterns

### DO NOT:
- **Use Jinja when SQLMesh macros suffice** — Jinja is legacy support; SQLMesh macros are type-safe and composable.
- **Create physical tables in pre/post-statements** — these run twice (at table creation and at query evaluation). Use `@IF(@runtime_stage = 'evaluating', ...)` to condition.
- **Use `SELECT *` in models that depend on blueprinted models** — if the upstream columns change, the downstream model breaks silently.
- **Forget `columns={}` in Python `@model` decorator** — SQLMesh needs the schema to create the table before running the model.
- **Mix timezones in `time_column`** — must be UTC. Use `cron_tz` for local time display, not storage.
- **Use non-idempotent models (`INCREMENTAL_BY_UNIQUE_KEY`, etc.) with limited `--start` in non-prod** — they can only preview, not fully backfill.

### DO:
- **Always cast types in the final SELECT** (`column::INT`) — SQLMesh infers schema from casts.
- **Use `grain` for merge/upsert strategies** — enables `table_diff` and audit efficiency.
- **Use `dc-run sqlmesh create_test --query ...` to bootstrap tests** — then refine by hand.
- **Use `--forward-only` for additive changes** (new columns, new models) — avoids unnecessary backfill.
- **Run `dc-run sqlmesh dag` after significant model changes** — verify the DAG before planning.

## BrewGIS-Specific Patterns

### Base Canvas → External Models

```yaml
# schema.yaml
- name: base_canvas
  tables:
    parcels:
      columns:
        parcel_id: int
        gross_acres: float
        geometry: geometry
    constraints:
      columns:
        parcel_id: int
        constraint_type: text
        constraint_acres: float
    built_forms:
      columns:
        building_type_id: int
        place_type_id: int
```

### Analysis Module → Blueprinted Template

```sql
-- models/analysis_module.sql
MODEL (
  name @scenario.@output_table,
  kind FULL,
  blueprints (
    (scenario := scenario_1, output_table := core_end_state,
     input_table := base_canvas.parcels, constraint_table := base_canvas.constraints),
    (scenario := scenario_2, output_table := core_end_state,
     input_table := base_canvas.parcels, constraint_table := base_canvas.constraints),
    -- ... generated from scenario control table
  ),
  audits (
    not_null(columns := (parcel_id)),
    number_of_rows(threshold := 1)
  )
);

SELECT
  p.parcel_id,
  p.gross_acres - COALESCE(c.constraint_acres, 0) AS net_acres,
  p.geometry
FROM @{input_table} AS p
LEFT JOIN @{constraint_table} AS c ON p.parcel_id = c.parcel_id;
```

### Transport Chain → Python Model + Blueprints

```python
# models/trip_distribution.py
@model(
    "@scenario.trip_distribution",
    kind=dict(name=ModelKindName.INCREMENTAL_BY_TIME_RANGE, time_column="batch_id"),
    columns={
        "origin_id": "int",
        "destination_id": "int",
        "trips": "float",
        "batch_id": "int",
    },
    blueprints="@gen_scenario_blueprints()",
)
def execute(context, start, end, execution_time, **kwargs):
    ...
```

### Scenario Comparison → table_diff + View

```bash
# Compare core results between two scenarios
dc-run sqlmesh table_diff scenario_a:scenario_b \
  --on parcel_id \
  --skip-columns geometry \
  --model "+core_*" \
  --show-sample

# Generate comparison views
dc-run sqlmesh evaluate comparison_view --var left=scenario_a --var right=scenario_b
```

## Reference: Full MODEL DDL Properties

```
MODEL (
  name schema.model_name,           # Required. View name in production.
  kind FULL,                        # Model kind with optional kind-specific args
  project project_name,             # For multi-repo setups
  owner owner_name,                 # Point of contact
  cron '@daily',                    # Schedule (cron syntax or presets)
  grain column_name,                # Primary key column(s)
  start '2024-01-01',               # Backfill start date
  stamp 'v1.2',                     # Arbitrary version string for forcing new snapshot
  tags (tag1, tag2),                # Organization labels
  description 'Model description',  # Table comment in warehouse
  column_descriptions (             # Per-column comments
    col1 = 'Description of col1',
    col2 = 'Description of col2'
  ),
  columns (                         # Explicit column types (for SEED, Python)
    col1 INT,
    col2 TEXT
  ),
  audits (                          # Audit references
    not_null(columns := (col1, col2)),
    unique_values(columns := (col1)),
    my_custom_audit(arg := value)
  ),
  dialect postgres,                 # SQL dialect
  blueprints (                      # Blueprint variable mappings
    (var1 := val1, var2 := val2),
    (var1 := val3, var2 := val4),
  ),
  -- Kind-specific properties:
  partitioned_by (col1, col2),      # Physical partitioning
  -- INCREMENTAL_BY_TIME_RANGE properties:
  --   kind INCREMENTAL_BY_TIME_RANGE (
  --     time_column event_date,
  --     lookback 2,                # Days to re-process for late data
  --     batch_size 10000,          # Rows per batch during backfill
  --   )
  -- INCREMENTAL_BY_UNIQUE_KEY properties:
  --   kind INCREMENTAL_BY_UNIQUE_KEY (
  --     unique_key id,
  --   )
  -- SEED properties:
  --   kind SEED (
  --     path 'file.csv',
  --     csv_settings (delimiter = "|")
  --   )
);

## Performance Tuning Protocol (EXPLAIN → Modify → Re-EXPLAIN → Compare)

A rigorous, repeatable process for optimizing SQLMesh model performance.
Always capture baselines before changing code. Never modify blindly and hope.

### MCP Tools

| Tool | Purpose |
|---|---|---|
| `get_model_plan_stats(model_name, analyze=false)` | EXPLAIN (COSTS, VERBOSE, FORMAT JSON) — captures query plan without executing. Returns `total_cost`, `plan_rows`, `node_count`, `nested_loops`, `seq_scans`, `max_depth`. |
| `get_model_plan_stats(model_name, analyze=true)` | EXPLAIN ANALYZE — actually runs the query. Returns `actual_total_time`, `actual_rows`. Use ONLY after verifying the plan shape is acceptable. |
| `render_model_sql(model_name, environment)` | Expands macros, substitutes variables. Shows exactly what will be executed. |
| `search_models(query)` | Find models by name or tag pattern. |
| `get_model_detail(model_name)` | Columns, audits, grains, dependencies, kind. Confirm the schema won't change. |

### Protocol Steps

#### Step 1: Capture baseline

```
1. get_model_plan_stats(m, analyze=false)  → baseline cost, node count, nested_loop count
2. render_model_sql(m, env)                 → save as "before.sql" for reference
3. get_model_detail(m)                      → confirm current output schema
```

Record these **baseline metrics** — the yardstick for improvement:

| Metric | What it measures |
|---|---|
| `total_cost` | Optimizer's cost estimate (arbitrary units, but comparable within same model) |
| `startup_cost` | Cost before first row returned (high = long wait for first result) |
| `nested_loops` | Count of nested-loop join nodes. Each one multiplies rows. >10 is a red flag. |
| `seq_scans` | Tables being sequentially scanned (no index used). Each entry names the table + row estimate. |
| `node_count` | Total plan nodes — simpler plans are usually faster. |
| `plan_rows` | Output row estimate — if wildly wrong vs expectations, statistics are stale. |

#### Step 2: Analyze the plan

Investigate these patterns:

- **Nested Loop on large tables** — lateral subqueries, `CROSS JOIN LATERAL` with `LIMIT 1`, or correlated subqueries. Each row from the outer table triggers a separate inner scan → O(n × m). Fix: replace with `DISTINCT ON`, window functions, or a single join.
- **Sequential scan on indexed column** — GiST index on `geometry` is being ignored, possibly due to function wrapping (e.g., `ST_Intersects(ST_Transform(a.geom, …), b.geom)` loses index pushdown). Fix: pre-transform or add expression index.
- **High `startup_cost` relative to `total_cost`** — sort-heavy plan. May benefit from index or pre-sorted subquery.
- **Bogus row estimates** — `plan_rows` far from actual after ANALYZE. Run `ANALYZE` on upstream tables, or the plan is choosing a bad strategy based on stale statistics.

#### Step 3: Modify model SQL

Edit the SQL file, keeping output columns and types identical. Schema-changing optimizations invalidate the before/after comparison.

#### Step 4: Re-capture and compare

```
1. get_model_plan_stats(m, analyze=false)  → new cost, node count, etc.
2. render_model_sql(m, env)                 → confirm the change took effect
3. get_model_detail(m)                       → confirm schema unchanged
```

#### Step 5: Apply the go/no-go gate

The new plan MUST show:

- **Total cost at least 10× lower** (for lateral→join conversions) or **clear structural improvement** (nested loops → 0, seq scans → index scans)
- **Plan shape change**: old bottleneck pattern eliminated. E.g., old: dominated by `Nested Loop` + many `Sort` nodes; new: `Hash Join` or `Merge Join` with one `Sort`/`Unique`.
- **rendered SQL** matches the intended change.
- **Output schema identical** — same columns, types, nullability.

If cost doesn't drop substantially or plan shape didn't change, **stop**. The rewrite didn't change PostgreSQL's execution strategy, and a different approach is needed.

#### Step 6: Run EXPLAIN ANALYZE (optional)

If the plan shape is clearly better, verify actual runtime with `analyze=true`. Gates before this protect against accidentally running a 7-hour ANALYZE on a bad plan.

### Template

When starting a new performance investigation:

```
---
1. Start Postgres: docker compose up -d postgres
2. Capture baseline:
   - get_model_plan_stats(model, analyze=false)
   - render_model_sql(model, env_name)
   - get_model_detail(model)
3. Analyze plan for bottlenecks
4. Edit model SQL
5. Re-capture
6. Compare — apply go/no-go gate
7. If gate passes: run EXPLAIN ANALYZE for actual timing
8. Report: baseline metrics, change description, new metrics, % improvement
---
```

### Pitfalls

- **Postgres not running**: MCP tools need the `postgres` service. Start with `docker compose up -d postgres`.
- **SQLMesh context stale**: If SQL files changed, call `refresh_sqlmesh_context` before re-capturing.
- **Stale statistics**: If `plan_rows` is off by >10×, run `ANALYZE` on upstream tables and retry.
- **Temp file limits**: Spatial joins with CTEs may materialize millions of rows. If EXPLAIN ANALYZE hits temp-file limits, increase `temp_file_limit` in postgres config or add `SET LOCAL work_mem = '512MB'` as a pre-hook.
- **Not all cost drops are equal**: A 1e6→1e4 drop from eliminating 502K lateral subqueries is credible. A 1e6→1e4 drop from a different join order may be optimizer guesswork — re-run with analyze=true to confirm.
