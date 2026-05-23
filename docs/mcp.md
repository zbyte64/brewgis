# BrewGIS MCP Server Reference

## Overview

BrewGIS exposes an MCP (Model Context Protocol) server that lets AI assistants
(Claude Desktop, Cursor, VS Code extensions, custom agents) query workspace
state, trigger analysis, import data, and manipulate paint/symbology — without
going through the web UI.

The MCP server is a thin transport layer that wraps existing Django views,
Celery tasks, and service modules. It adds zero new business logic.

## Quick Start

### Prerequisites

- Python 3.12 with dependencies installed
- Running PostGIS and Redis instances

### Host Mode (Development)

```bash
# Set up environment
export DJANGO_SETTINGS_MODULE=config.settings

# Start the MCP server
python manage.py run_mcp
```

The server reads from stdin and writes to stdout. By default it listens until
stdin closes or SIGTERM.

### Docker Mode

```bash
# Start the MCP service alongside other services
docker compose -f docker-compose.local.yml up mcp
```

The Docker service is configured in `docker-compose.local.yml` following the
same pattern as `celeryworker`.

## Auth Token

Phase 5 (Authentication & Authorization) is not yet implemented. The server
currently runs without authentication. Set `MCP_AUTH_TOKEN` as an environment
variable to prepare for Phase 5 rollout:

```bash
# The token is logged but not enforced until Phase 5
export MCP_AUTH_TOKEN=your-token-here
python manage.py run_mcp
```

## Tool Reference

### Workspace Tools

| Tool | Description | Sync/Async |
|------|-------------|------------|
| `list_workspaces(query?)` | List workspaces, optional name filter | Sync |
| `get_workspace(slug)` | Get detailed workspace info | Sync |

### Scenario Tools

| Tool | Description | Sync/Async |
|------|-------------|------------|
| `list_scenarios(workspace_slug)` | List scenarios for a workspace | Sync |
| `get_scenario(workspace_slug, scenario_slug)` | Get detailed scenario info | Sync |
| `compare_scenarios(workspace_slug, scenario_slugs, metrics?)` | Compare multiple scenarios | Sync |
| `create_scenario(workspace_slug, name, description, base_year, horizon_year, clone_from?)` | Create a new scenario | Sync |
| `delete_scenario(workspace_slug, scenario_slug)` | Delete a scenario | Sync |
| `rename_scenario(workspace_slug, scenario_slug, new_name)` | Rename a scenario | Sync |

### Layer Tools

| Tool | Description | Sync/Async |
|------|-------------|------------|
| `list_layers(workspace_slug, scenario_slug?)` | List layers for a workspace | Sync |
| `get_layer_schema(workspace_slug, layer_key)` | Get column schema for a layer | Sync |
| `query_layer_data(workspace_slug, layer_key, columns?, limit, offset, filters?)` | Query rows from a layer | Sync |
| `get_symbology(workspace_slug, layer_key)` | Get symbology configuration | Sync |
| `list_layer_filters(workspace_slug, layer_key)` | List saved filters | Sync |
| `update_symbology(workspace_slug, layer_key, ...)` | Update symbology config | Sync |
| `auto_generate_symbology_tool(workspace_slug, layer_key, method, num_classes, palette)` | Auto-generate symbology | Sync |
| `preview_symbology_style(workspace_slug, layer_key, symbology_type)` | Preview MapLibre style JSON | Sync |
| `create_layer(workspace_slug, name, table_schema, table_name, geometry_type, key?)` | Register a PostGIS table as a layer | Sync |
| `delete_layer_tool(workspace_slug, layer_key)` | Delete a layer | Sync |
| `create_filter(workspace_slug, layer_key, name, filter_json)` | Create a layer filter | Sync |
| `toggle_filter(workspace_slug, layer_key, filter_id, enabled)` | Enable/disable a filter | Sync |
| `delete_filter_tool(workspace_slug, layer_key, filter_id)` | Delete a filter | Sync |

### Paint Tools

| Tool | Description | Sync/Async |
|------|-------------|------------|
| `paint_features(workspace_slug, scenario_slug, feature_ids, column, value, note?)` | Paint values onto features | Sync |
| `clear_paint(workspace_slug, scenario_slug, feature_ids?, column?)` | Clear painted values | Sync |
| `get_painted_values(workspace_slug, scenario_slug, feature_ids?, columns?)` | Get painted values | Sync |
| `undo_paint(workspace_slug, scenario_slug, count?)` | Undo paint events | Sync |
| `list_paint_constraints(workspace_slug)` | List paint constraints | Sync |
| `validate_paint_batch(workspace_slug, scenario_slug, features)` | Validate paint batch | Sync |

### Analysis Tools

| Tool | Description | Sync/Async |
|------|-------------|------------|
| `list_analysis_modules(workspace_slug)` | List available analysis modules | Sync |
| `run_analysis(workspace_slug, scenario_slug, modules?, params?)` | Launch analysis pipeline | Async (Celery) |
| `get_analysis_status(workspace_slug, run_id)` | Get analysis run status | Sync |
| `get_analysis_results(workspace_slug, run_id)` | Get analysis results | Sync |

### Data Import Tools

| Tool | Description | Sync/Async |
|------|-------------|------------|
| `run_census_fetch_tool(workspace_slug, state_fips, tables?, year?, geography?)` | Fetch Census ACS data | Async (Celery) |
| `run_lehd_fetch_tool(workspace_slug, state_fips, job_types?, year?)` | Fetch LEHD/LODES employment data | Async (Celery) |
| `run_poi_fetch_tool(workspace_slug, geometry_wkt, categories?, radius_m?)` | Fetch OSM points of interest | Async (Celery) |
| `run_spatial_allocation_tool(workspace_slug, source_layer, target_layer, method, columns)` | Run spatial allocation | Async (Celery) |
| `run_column_stitching_tool(workspace_slug, target_table, mappings)` | Run column stitching/imputation | Async (Celery) |
| `get_import_status(workspace_slug, import_run_id)` | Get import operation status | Sync |

### Report Tools

| Tool | Description | Sync/Async |
|------|-------------|------------|
| `list_report_templates(workspace_slug)` | List available report types | Sync |
| `generate_report(workspace_slug, scenario_slug?, report_type, options?)` | Generate a report | Async (Celery) |
| `get_report_download_url(workspace_slug, report_id)` | Get report download URL | Sync |
| `list_reports(workspace_slug, limit?)` | List recent reports | Sync |

### Job Management Tools

| Tool | Description | Sync/Async |
|------|-------------|------------|
| `get_job_status(task_id)` | Get Celery task status | Sync |
| `cancel_job(task_id)` | Cancel a running task | Sync |

### GIS File Import

| Tool | Description | Sync/Async |
|------|-------------|------------|
| `import_gis_file(workspace_slug, file_data_base64, file_name, layer_name?, srid?)` | Import GIS file as a layer | Sync (small files) |

## Job Polling Pattern

Long-running tools (analysis, data import, report generation) return immediately
with a `task_id`. Poll the job status using `get_job_status(task_id)`:

```python
# Tool call returns immediately
result = session.call_tool("run_analysis", {
    "workspace_slug": "1",
    "scenario_slug": "2",
    "modules": ["core"]
})
task_id = result.content[0].text  # {"task_id": "...", "status": "PENDING", ...}

# Poll until complete
import time
while True:
    status = session.call_tool("get_job_status", {"task_id": task_id})
    status_data = json.loads(status.content[0].text)
    if status_data["status"] in ("SUCCESS", "FAILURE"):
        break
    time.sleep(2)
```

## Client Configuration

### Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "brewgis": {
      "command": "docker",
      "args": ["compose", "-f", "docker-compose.local.yml", "run", "--rm", "mcp"],
      "env": {
        "MCP_AUTH_TOKEN": "dev-token"
      }
    }
  }
}
```

### Host Mode (for local development)

```json
{
  "mcpServers": {
    "brewgis": {
      "command": "python",
      "args": ["manage.py", "run_mcp"],
      "env": {
        "DJANGO_SETTINGS_MODULE": "config.settings",
        "MCP_AUTH_TOKEN": "dev-token"
      }
    }
  }
}
```

## Architecture

The MCP server follows the same domain decomposition as `brewgis/workspace/views/`:

```
brewgis/workspace/mcp/
├── __init__.py          # empty
├── server.py            # Server instance, run_stdio()
├── auth.py              # Auth stub (Phase 5)
├── tools/
│   ├── __init__.py      # Tool registration aggregator
│   ├── workspace.py     # Workspace CRUD tools
│   ├── scenario.py      # Scenario CRUD + comparison tools
│   ├── layer.py         # Layer + symbology + filter tools
│   ├── paint.py         # Paint read/write tools
│   ├── analysis.py      # dbt analysis tools (Celery-backed)
│   ├── data_import.py   # Data import tools + job management
│   └── reports.py       # Report generation + GIS import
```

## Extending

To add a new tool:

1. Open the appropriate module in `brewgis/workspace/mcp/tools/`
2. Add a function decorated with `@server.tool()` inside `register_tools()`
3. The function name becomes the tool name, docstring becomes the description
4. Type annotations define the input schema
5. Return a dict or pydantic model for the output

```python
def register_tools(server: object) -> None:
    @server.tool()
    def my_new_tool(param1: str, param2: int = 10) -> dict:
        """Description shown to the AI assistant."""
        # Your logic here
        return {"result": "success"}
```

## Troubleshooting

| Problem | Likely Cause | Solution |
|---------|-------------|----------|
| `ModuleNotFoundError: mcp` | MCP SDK not installed | `pip install mcp>=1.0.0` |
| Server exits immediately | No stdin/stdout transport | Run via `python manage.py run_mcp` |
| `django.core.exceptions.ImproperlyConfigured` | DATABASE_URL not set | Check `.env` or environment variables |
| Tools return empty lists | Database has no data | Create data through the web UI first |
