# JupySQL — Interactive PostGIS Analysis

[JupySQL](https://jupysql.ploomber.io/) lets you run SQL directly from Jupyter notebooks
using `%sql` magic. This is useful for data scientists and analysts who want to
query the BrewGIS PostGIS database without writing Django views.

## Setup

```bash
# JupySQL is installed as a dev dependency:
pip install -r requirements/local.txt  # includes jupysql
```

## Connection

In a notebook cell, run:

```python
%load_ext sql
%sql postgresql://brewgis:brewgis@localhost:5432/brewgis
```

## Example Queries

### Using the `acres()` helper function (Phase 1)

```sql
%sql SELECT parcel_id, public.acres(geom) AS acres_gross FROM public.parcels LIMIT 10
```

### List scenarios

```sql
%%sql
SELECT id, slug, name, base_year, horizon_year
FROM workspace_scenario
ORDER BY id
```

### Check data import status

```sql
%%sql
SELECT id, import_type, status, rows_imported, created
FROM workspace_dataimportrun
ORDER BY created DESC
LIMIT 5
```

### Trigger analysis run (read-only view only)

```sql
-- View analysis runs and their status
%%sql
SELECT id, scenario_id, status, created
FROM workspace_analysisrun
ORDER BY created DESC
LIMIT 10
```

## Available Notebooks

| Notebook | Purpose |
|----------|---------|
| `notebooks/01_quick_stats.ipynb` | Quick scenario metrics overview |
| `notebooks/02_explore_layer.ipynb` | Inspect column distributions and outliers |
| `notebooks/03_analysis_results.ipynb` | Compare scenario vs. base metrics, export CSV |

## Notes

- Connection strings are environment-specific. Replace the credentials and host
  as needed for your setup.
- The `acres()` function is only available after running the Phase 1 migration.
- For write operations (INSERT/UPDATE/DELETE), use Django management commands
  or API views — JupySQL is for ad-hoc read-only analysis.
- Output cells in notebooks are gitignored (see `.gitignore`).
