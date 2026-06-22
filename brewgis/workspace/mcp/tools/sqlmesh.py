"""MCP tools for read-only SQLMesh inspection — lineage, environments, audits."""

import logging
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# Allow sync Django ORM calls from async MCP context
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

from sqlalchemy import text

from brewgis.workspace.analysis.sqlmesh_runner import SQLMESH_PROJECT_DIR
from brewgis.workspace.analysis.sqlmesh_runner import get_context
from brewgis.workspace.management.commands.explain_sqlmesh_models import analyze_plan
from brewgis.workspace.services._db import get_engine

logger = logging.getLogger(__name__)


# ── Mtime-Aware Context Cache ─────────────────────────────────


class _ContextCache:
    """File-mtime–aware cache for the SQLMesh Context.

    The cache stores the (context, load_time) pair.  On every access it
    walks ``brewgis/sqlmesh/`` to compute the most recent file mtime.
    If any file has been modified since the context was loaded, it
    creates a fresh Context — eliminating staleness without external
    signals or cross-container IPC.

    The ``stat()`` walk adds ~5-15ms on local SSD (negligible compared
    to the MCP roundtrip) and avoids reloading ~69 models on every call
    when nothing has changed.
    """

    def __init__(self) -> None:
        self._context: Any = None
        self._load_time: float = 0.0

    def get(self, **variables: str | int) -> Any:
        """Return a fresh-enough context, reloading if any source file changed."""
        latest_mtime = self._compute_latest_mtime()
        if self._context is None or latest_mtime > self._load_time:
            ctx = get_context(**dict(sorted(variables.items())))
            self._context = ctx
            self._load_time = latest_mtime
        return self._context

    def refresh(self) -> None:
        """Force the next ``get()`` to reload (escape hatch for edge cases)."""
        self._load_time = 0.0

    @staticmethod
    def _compute_latest_mtime() -> float:
        """Walk ``brewgis/sqlmesh/`` and return the latest file mtime."""
        project_dir = str(SQLMESH_PROJECT_DIR)
        latest: float = 0.0
        for dirpath, dirnames, filenames in os.walk(project_dir):
            # Skip __pycache__ directories for speed
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                try:
                    mtime = os.stat(filepath).st_mtime
                    latest = max(latest, mtime)
                except OSError:
                    continue  # skip inaccessible files
        return latest


_context_cache = _ContextCache()


def _context(**variables: str | int) -> Any:
    """Shortcut — cached context with default variables, auto-refreshed.

    Kwargs allow overriding SQLMesh variables for specialised callers.
    """
    return _context_cache.get(**variables)


# ── Output Schemas ──────────────────────────────────────────────


class ModelSummary(BaseModel):
    fqn: str
    kind: str
    source_type: str
    tags: list[str]
    description: str | None


class ModelDetail(BaseModel):
    fqn: str
    name: str
    kind: str
    source_type: str
    tags: list[str]
    description: str | None
    owner: str | None
    dialect: str
    columns: list[dict[str, str]]
    audits: list[str]
    grains: list[str]
    depends_on: list[str]
    indexes: list[str] = []


class ModelLineage(BaseModel):
    model_name: str
    upstream: list[str]
    downstream: list[str]
    lineage: list[str]


class EnvironmentSummary(BaseModel):
    name: str
    finalized_ts: int | None
    expiration_ts: int | None
    suffix_target: str


class EnvironmentDetail(BaseModel):
    name: str
    start_at: str
    end_at: str | None
    plan_id: str
    finalized_ts: int | None
    expiration_ts: int | None
    suffix_target: str
    snapshot_count: int


class ModelVersion(BaseModel):
    model_name: str
    version: str | None
    kind: str | None


class AuditSummary(BaseModel):
    name: str
    model_name: str | None
    description: str | None


class TableDiffResult(BaseModel):
    model_name: str
    source_table: str
    target_table: str
    schema_diff: list[dict[str, object]]
    summary: dict[str, object] | None


class PlanStats(BaseModel):
    model_name: str
    total_cost: float | None = None
    startup_cost: float | None = None
    plan_rows: float | None = None
    node_count: int | None = None
    max_depth: int | None = None
    seq_scans: list[str] = []
    nested_loops: int | None = None
    actual_total_time: float | None = None
    error: str | None = None


# ── Helpers ──────────────────────────────────────────────────────


class ModelNotResolvedError(Exception):
    """Raised when model name resolution fails."""


def _resolve_model_name(name: str, models: dict) -> str:
    """Resolve a model name (bare/FQN/quoted) to its ctx.models dict key.

    Resolution order:
      1. Exact match (existing behavior)
      2. Strip SQL quotes and retry exact match
      3. Match against model.name (short FQN like 'assessor.foo')
      4. Substring match on normalized FQN (single unambiguous result)

    Raises ModelNotResolvedError with actionable message on failure.
    """
    # 1. Exact match
    if name in models:
        return name

    # 2. Strip SQL quotes and retry
    stripped = name.replace('"', "").replace("`", "")
    if stripped in models:
        return stripped

    total = len(models)

    # 3. Match against model.name (short name or 2-part FQN suffix)
    name_lower = stripped.lower()
    candidates: list[str] = []
    for fqn in models:
        # model.name is the short name (last component)
        short = fqn.rsplit(".", 1)[-1]
        if short.lower() == name_lower:
            candidates.append(fqn)
        # 2-part suffix like "assessor.foo"
        if (
            len(fqn.split(".")) >= 2  # noqa: PLR2004
            and ".".join(fqn.rsplit(".", 2)[-2:]).lower() == name_lower
        ):
            candidates.append(fqn)

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        ambiguous = sorted(set(candidates))
        msg = (
            f"Model '{name}' is ambiguous. Matching models: {ambiguous}. "
            f"Use the fully qualified name (e.g. '{ambiguous[0]}')."
        )
        raise ModelNotResolvedError(msg)

    # 4. Substring match on normalized FQN
    substring_matches: list[str] = [fqn for fqn in models if name_lower in fqn.lower()]
    if len(substring_matches) == 1:
        return substring_matches[0]
    if len(substring_matches) > 1:
        msg = (
            f"Model '{name}' is ambiguous. Matching models: {sorted(substring_matches)}. "
            "Use the fully qualified name."
        )
        raise ModelNotResolvedError(msg)

    # No match found
    msg = f"Model '{name}' not found across {total} models. Try search_models to discover available models."
    raise ModelNotResolvedError(msg)


def _model_kind_name(model: object) -> str:
    """Return model kind as a readable string, e.g. ``"VIEW"``, ``"FULL"``."""
    kind = getattr(model, "kind", None)
    if kind is None:
        return "UNKNOWN"
    name = getattr(kind, "name", None)
    return str(name) if name is not None else "UNKNOWN"


def _model_source_type(model: object) -> str:
    """Return ``"sql"``, ``"python"``, ``"seed"``, or ``"external"``."""
    name = type(model).__name__
    if name == "SqlModel":
        return "sql"
    if name == "PythonModel":
        return "python"
    if name == "SeedModel":
        return "seed"
    if name == "ExternalModel":
        return "external"
    return name.lower()


def _model_name(model: object) -> str:
    """Return the model's short name."""
    return getattr(model, "name", "") or ""


def _columns_to_list(model: object) -> list[dict[str, str]]:
    """Return columns as ``[{name, type}]``."""
    cols = getattr(model, "columns_to_types", None)
    if cols is None:
        cols = getattr(model, "columns_to_types_", None)
    if cols is None:
        return []
    return [{"name": str(k), "type": str(v)} for k, v in cols.items()]


def _audit_names(model: object) -> list[str]:
    """Return list of audit names attached to a model."""
    audits = getattr(model, "audits", None) or []
    return [str(a[0]) if isinstance(a, tuple) else str(a) for a in audits]


def _grain_names(model: object) -> list[str]:
    """Return list of grain expression strings."""
    grains = getattr(model, "grains", None) or []
    return [str(g) for g in grains]


def _depends_on_list(model: object) -> list[str]:
    """Return list of upstream model FQNs."""
    deps = getattr(model, "depends_on", None)
    if deps is None:
        deps = getattr(model, "depends_on_", None)
    return sorted(str(d) for d in (deps or []))


def _extract_post_statement_indexes(fqn: str) -> list[str]:
    """Extract CREATE INDEX statements from a model file's post_statements block.

    Given a normalized FQN like ``brewgis.assessor.parcel_dasymetric_weights``,
    derives the source file path and parses ``-- post_statements`` section for
    ``CREATE INDEX`` lines.
    """
    parts = fqn.replace('"', "").split(".")
    if len(parts) < 3:  # noqa: PLR2004
        return []
    schema = parts[1]
    model_name = parts[2]

    # Try .sql first, then .py
    for ext in (".sql", ".py"):
        path = Path(f"brewgis/sqlmesh/models/{schema}/{model_name}{ext}")
        if path.exists():
            break
    else:
        return []

    indexes: list[str] = []
    in_post_statements = False
    try:
        text_content = path.read_text()
    except OSError:
        return []

    for line in text_content.splitlines():
        stripped = line.strip()
        if stripped == "-- post_statements":
            in_post_statements = True
            continue
        if in_post_statements:
            # Stop at next model definition or blank-line boundary
            if stripped.startswith(("MODEL (", "@@")):
                break
            if "CREATE INDEX" in stripped.upper():
                indexes.append(stripped)
    return indexes


# ── Tool Registration ─────────────────────────────────────────


def register_tools(server: object) -> None:  # noqa: C901, PLR0915
    """Register SQLMesh inspection tools with the MCP server."""

    @server.tool()  # type: ignore[attr-defined]
    def refresh_sqlmesh_context() -> dict[str, object]:
        """Force the SQLMesh Context to reload on the next tool call.

        Use this escape hatch when external files change (e.g. external
        model YAML, seeds) and the automatic file-mtime check is not fast
        enough for your immediate next call.  Normally the context is
        auto-refreshed when any file under ``brewgis/sqlmesh/`` is
        modified.
        """
        _context_cache.refresh()
        return {
            "status": "ok",
            "message": "SQLMesh context cache invalidated. Next tool call will reload.",
        }

    @server.tool()  # type: ignore[attr-defined]
    def list_sqlmesh_models(
        tags: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, object]]:
        """List all SQLMesh models, optionally filtered by tags or kind."""
        ctx = _context()
        results: list[dict[str, object]] = []
        for fqn, model in ctx.models.items():
            if tags:
                model_tags = set(getattr(model, "tags", None) or [])
                if not any(t.strip() in model_tags for t in tags.split(",")):
                    continue
            model_kind = _model_kind_name(model)
            if kind and model_kind.lower() != kind.lower():
                continue
            results.append(
                ModelSummary(
                    fqn=fqn,
                    kind=model_kind,
                    source_type=_model_source_type(model),
                    tags=list(getattr(model, "tags", None) or []),
                    description=getattr(model, "description", None),
                ).model_dump()
            )
        results.sort(key=lambda r: str(r["fqn"]))
        return results

    @server.tool()  # type: ignore[attr-defined]
    def get_model_lineage(  # noqa: C901, PLR0912
        model_name: str,
        direction: str = "upstream",
    ) -> dict[str, object]:
        """Show upstream, downstream, or full lineage for a model.

        Args:
            model_name: Fully qualified model name.
            direction: ``"upstream"``, ``"downstream"``, or ``"full"``.
        """
        ctx = _context()
        models = ctx.models
        try:
            key = _resolve_model_name(model_name, models)
        except ModelNotResolvedError as e:
            return {"error": str(e)}

        model = models[key]
        upstream = _depends_on_list(model)

        # Compute downstream: models whose depends_on includes this model
        downstream: list[str] = []
        for fqn, m in models.items():
            deps = _depends_on_list(m)
            if model_name in deps:
                downstream.append(fqn)
        downstream.sort()

        # Full lineage: BFS upstream + BFS downstream, merged topo-sorted
        if direction == "full":
            lineage_set: set[str] = set()
            visit = list(upstream)
            while visit:
                m_name = visit.pop()
                if m_name in lineage_set:
                    continue
                lineage_set.add(m_name)
                if m_name in models:
                    visit.extend(_depends_on_list(models[m_name]))

            visit = list(downstream)
            while visit:
                m_name = visit.pop()
                if m_name in lineage_set:
                    continue
                lineage_set.add(m_name)
                if m_name in models:
                    for fqn, m in models.items():
                        if m_name in _depends_on_list(m):
                            if fqn not in lineage_set:
                                visit.append(fqn)

            lineage = sorted(
                lineage_set,
                key=lambda n: list(models.keys()).index(n) if n in models else 0,
            )
        elif direction == "upstream":
            lineage = sorted(upstream)
        elif direction == "downstream":
            lineage = sorted(downstream)
        else:
            return {
                "error": f"Invalid direction '{direction}'. Use 'upstream', 'downstream', or 'full'."
            }

        return ModelLineage(
            model_name=key,
            upstream=sorted(upstream),
            downstream=sorted(downstream),
            lineage=lineage,
        ).model_dump()

    @server.tool()  # type: ignore[attr-defined]
    def get_model_detail(
        model_name: str,
    ) -> dict[str, object]:
        """Get detailed info about a model: columns, audits, kind, tags, grains, depends_on."""
        ctx = _context()
        models = ctx.models
        try:
            key = _resolve_model_name(model_name, models)
        except ModelNotResolvedError as e:
            return {"error": str(e)}
        model = models[key]

        return ModelDetail(
            fqn=key,
            name=_model_name(model),
            kind=_model_kind_name(model),
            source_type=_model_source_type(model),
            tags=list(getattr(model, "tags", None) or []),
            description=getattr(model, "description", None),
            owner=getattr(model, "owner", None),
            dialect=getattr(model, "dialect", "postgres"),
            columns=_columns_to_list(model),
            audits=_audit_names(model),
            grains=_grain_names(model),
            depends_on=_depends_on_list(model),
            indexes=_extract_post_statement_indexes(key),
        ).model_dump()

    @server.tool()  # type: ignore[attr-defined]
    def render_model_sql(
        model_name: str,
        environment: str | None = None,
    ) -> dict[str, object]:
        """Render a model's SQL with macros expanded."""
        ctx = _context()
        models = ctx.models
        try:
            key = _resolve_model_name(model_name, models)
        except ModelNotResolvedError as e:
            return {"error": str(e)}

        try:
            rendered = ctx.render(
                key,
                environment=environment,
                start=None,
                end=None,
                execution_time=None,
                expand=None,
            )
            return {"model_name": key, "sql": str(rendered)}
        except Exception as exc:
            logger.exception("Failed to render model '%s'", key)
            return {"error": f"Failed to render model '{key}': {exc}"}

    @server.tool()  # type: ignore[attr-defined]
    def list_environments() -> list[dict[str, object]]:
        """List all SQLMesh environments."""
        ctx = _context()
        envs = ctx.state_reader.get_environments()
        return [
            EnvironmentSummary(
                name=e.name,
                finalized_ts=e.finalized_ts,
                expiration_ts=e.expiration_ts,
                suffix_target=str(e.suffix_target) if e.suffix_target else "",
            ).model_dump()
            for e in envs
        ]

    @server.tool()  # type: ignore[attr-defined]
    def get_environment(
        env_name: str,
    ) -> dict[str, object]:
        """Get details for a single SQLMesh environment."""
        ctx = _context()
        env = ctx.state_reader.get_environment(env_name)
        if env is None:
            return {"error": f"Environment '{env_name}' not found"}

        snapshots = getattr(env, "promoted_snapshots", None) or []
        return EnvironmentDetail(
            name=env.name,
            start_at=str(env.start_at),
            end_at=str(env.end_at) if env.end_at else None,
            plan_id=env.plan_id,
            finalized_ts=env.finalized_ts,
            expiration_ts=env.expiration_ts,
            suffix_target=str(env.suffix_target) if env.suffix_target else "",
            snapshot_count=len(snapshots),
        ).model_dump()

    @server.tool()  # type: ignore[attr-defined]
    def list_model_versions(
        env_name: str,
        pattern: str | None = None,
    ) -> list[dict[str, object]]:
        """List current version per model in an environment."""
        ctx = _context()
        env = ctx.state_reader.get_environment(env_name)
        if env is None:
            return [{"error": f"Environment '{env_name}' not found"}]

        snapshots = getattr(env, "promoted_snapshots", None) or []
        results: list[dict[str, object]] = []
        for snap in snapshots:
            display_name = getattr(snap, "display_name", None) or getattr(
                snap, "name", ""
            )
            if callable(display_name):
                display_name = display_name()
            model_name_str = str(display_name)

            if pattern and pattern.lower() not in model_name_str.lower():
                continue

            version = getattr(snap, "version", None)
            kind = getattr(snap, "model_kind_name", None)
            results.append(
                ModelVersion(
                    model_name=model_name_str,
                    version=str(version) if version else None,
                    kind=str(kind) if kind else None,
                ).model_dump()
            )
        results.sort(key=lambda r: str(r["model_name"]))
        return results

    @server.tool()  # type: ignore[attr-defined]
    def diff_environments(
        source: str,
        target: str,
        model_name: str | None = None,
    ) -> list[dict[str, object]]:
        """Compare schema and row summary between two SQLMesh environments.

        Uses ``context.table_diff()`` to produce schema diffs and row-count summaries.
        """
        ctx = _context()
        try:
            diffs = ctx.table_diff(
                source=source,
                target=target,
                select_models=[model_name] if model_name else None,
                show=False,
                show_sample=False,
            )
        except Exception as exc:
            logger.exception("table_diff failed for %s → %s", source, target)
            return [{"error": str(exc)}]

        results: list[dict[str, object]] = []
        for td in diffs:
            model_name_used = getattr(td, "model_name", "") or ""
            source_table = str(getattr(td, "source", ""))
            target_table = str(getattr(td, "target", ""))

            # Extract schema diff and summary
            schema_diff: list[dict[str, object]] = []
            summary: dict[str, object] | None = None

            if hasattr(td, "schema_diff"):
                schema_diff = [
                    {"column": str(c), "source_type": str(st), "target_type": str(tt)}
                    for c, st, tt in getattr(td, "schema_diff", [])
                ]

            if hasattr(td, "summary"):
                s = getattr(td, "summary", None)
                if s is not None:
                    summary = {str(k): str(v) for k, v in s.items()}

            results.append(
                TableDiffResult(
                    model_name=model_name_used,
                    source_table=source_table,
                    target_table=target_table,
                    schema_diff=schema_diff,
                    summary=summary,
                ).model_dump()
            )
        return results

    @server.tool()  # type: ignore[attr-defined]
    def list_audits(
        model_name: str | None = None,
    ) -> list[dict[str, object]]:
        """List SQLMesh audits. When ``model_name`` is given, scope to audits for that model."""
        ctx = _context()

        if model_name:
            models = ctx.models
            try:
                key = _resolve_model_name(model_name, models)
            except ModelNotResolvedError as e:
                return [{"error": str(e)}]
            model = models[key]
            audit_names = _audit_names(model)
            return [
                AuditSummary(
                    name=an,
                    model_name=key,
                    description=an,
                ).model_dump()
                for an in audit_names
            ]

        # All standalone audits
        standalone = getattr(ctx, "standalone_audits", None) or {}
        results: list[dict[str, object]] = []
        for audit_name, audit in standalone.items():
            desc = getattr(audit, "description", None)
            results.append(
                AuditSummary(
                    name=str(audit_name),
                    model_name=None,
                    description=desc,
                ).model_dump()
            )
        results.sort(key=lambda r: str(r["name"]))
        return results

    @server.tool()  # type: ignore[attr-defined]
    def search_models(
        query: str,
    ) -> list[dict[str, object]]:
        """Search SQLMesh models by FQN or tag substring match."""
        ctx = _context()
        q = query.lower()
        results: list[dict[str, object]] = []
        for fqn, model in ctx.models.items():
            if q in fqn.lower():
                results.append(
                    ModelSummary(
                        fqn=fqn,
                        kind=_model_kind_name(model),
                        source_type=_model_source_type(model),
                        tags=list(getattr(model, "tags", None) or []),
                        description=getattr(model, "description", None),
                    ).model_dump()
                )
                continue
            # Check tags
            tags = getattr(model, "tags", None) or []
            if any(q in str(t).lower() for t in tags):
                results.append(
                    ModelSummary(
                        fqn=fqn,
                        kind=_model_kind_name(model),
                        source_type=_model_source_type(model),
                        tags=list(tags),
                        description=getattr(model, "description", None),
                    ).model_dump()
                )
        results.sort(key=lambda r: str(r["fqn"]))
        return results

    @server.tool()  # type: ignore[attr-defined]
    def get_model_plan_stats(
        model_name: str,
        analyze: bool = False,  # noqa: FBT001, FBT002
    ) -> dict[str, object]:
        """Run EXPLAIN on a model and return cost/plan analysis.

        Renders the model SQL, wraps it in EXPLAIN (COSTS, VERBOSE, FORMAT JSON),
        executes the query, and extracts diagnostics via analyze_plan.

        When *analyze* is True, uses EXPLAIN (ANALYZE, COSTS, VERBOSE, FORMAT JSON)
        to actually execute the query and return real execution timings.
        """
        ctx = _context()
        models = ctx.models
        try:
            key = _resolve_model_name(model_name, models)
        except ModelNotResolvedError as e:
            return {"error": str(e)}

        try:
            rendered = ctx.render(
                key,
                environment=None,
                start=None,
                end=None,
                execution_time=None,
                expand=None,
            )
        except Exception as exc:  # noqa: BLE001
            return PlanStats(
                model_name=key,
                error=f"Failed to render model '{key}': {exc}",
            ).model_dump()

        analyze_clause = "ANALYZE true, " if analyze else ""
        explain_sql = (
            f"EXPLAIN ({analyze_clause}COSTS true, VERBOSE true, FORMAT JSON)"
            f" {rendered.sql(dialect='postgres')}"
        )

        engine = get_engine()
        try:
            with engine.connect() as conn, conn.begin():
                result = conn.execute(text(explain_sql))
                row = result.fetchone()
        except Exception as exc:  # noqa: BLE001
            return PlanStats(
                model_name=key,
                error=f"EXPLAIN failed: {exc}",
            ).model_dump()

        if not (row and row[0]):
            return PlanStats(
                model_name=key,
                error="No plan returned",
            ).model_dump()

        try:
            analysis = analyze_plan(row[0])
        except Exception as exc:  # noqa: BLE001
            return PlanStats(
                model_name=key,
                error=f"analyze_plan failed: {exc}",
            ).model_dump()

        return PlanStats(
            model_name=key,
            total_cost=analysis.total_cost,
            startup_cost=analysis.startup_cost,
            plan_rows=analysis.plan_rows,
            node_count=analysis.node_count,
            max_depth=analysis.max_depth,
            seq_scans=analysis.seq_scans,
            nested_loops=analysis.nested_loops,
            actual_total_time=analysis.actual_total_time,
        ).model_dump()
