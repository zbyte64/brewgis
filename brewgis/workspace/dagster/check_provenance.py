"""Static column provenance checker for Dagster asset graphs.

Reads existing contract files (Soda YAML, dbt ``_schema.yml``,
BaseCanvasSchema, inline annotations) and walks the Dagster asset
dependency graph to verify column provenance.

Stateless — no database required. Pure Python + YAML parsing + one
optional ``dbt docs generate`` call.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import django
import yaml

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from dagster import AssetKey
    from dagster import Definitions

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths — resolved relative to this module
# ---------------------------------------------------------------------------

_CHECKER_DIR = Path(__file__).resolve().parent  # .../workspace/dagster/
_APPS_DIR = _CHECKER_DIR.parent.parent  # brewgis/ (Django app root)
_PROJECT_DIR = _APPS_DIR.parent  # repo root

_SODA_CONTRACTS_DIR = _APPS_DIR / "soda" / "contracts"
_DBT_PROJECT_DIR = _APPS_DIR / "dbt_project"
_DBT_SCHEMA_PATH = _DBT_PROJECT_DIR / "models" / "_schema.yml"
_DBT_TARGET_DIR = _DBT_PROJECT_DIR / "target"
_DBT_MANIFEST_PATH = _DBT_TARGET_DIR / "manifest.json"

# ---------------------------------------------------------------------------
# Metadata keys used on asset definitions
# ---------------------------------------------------------------------------

METADATA_CONTRACT_SOURCE = "dagster/contract/source"
# str: metadata key for the contract source type (soda, dbt, baseschema, inline).

METADATA_CONTRACT_PATH = "dagster/contract/path"
# str: metadata key for the contract source path/name (e.g. contract name, dbt model name).

METADATA_CONTRACT_INLINE_COLUMNS = "dagster/contract/inline_columns"
# list[str]: metadata key for inline column names.

# ═══════════════════════════════════════════════════════════════════════════
# Phase 1: Contract Resolution Layer
# ═══════════════════════════════════════════════════════════════════════════


def resolve_soda_contract(name: str) -> frozenset[str]:
    """Read a Soda contract YAML and return column names as a frozenset.

    Parameters
    ----------
    name:
        Contract name (without ``.yml`` extension), e.g. ``"census_acs"``.

    Returns
    -------
    frozenset[str]
        Column names declared in the contract. Empty set if the file is
        missing or has no ``columns`` section.
    """
    path = _SODA_CONTRACTS_DIR / f"{name}.yml"
    if not path.exists():
        logger.warning("Soda contract not found: %s", path)
        return frozenset()

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "columns" not in data:
        return frozenset()

    return frozenset(col["name"] for col in data["columns"] if "name" in col)


def resolve_dbt_schema(model_name: str) -> frozenset[str]:
    """Read the dbt ``_schema.yml`` and return column names for *model_name*.

    Parameters
    ----------
    model_name:
        The ``name:`` value of a model in ``_schema.yml``, e.g.
        ``"core_end_state"``.

    Returns
    -------
    frozenset[str]
        Column names for the matching model. Empty set if the model has no
        entry or the schema file is not found.
    """
    if not _DBT_SCHEMA_PATH.exists():
        logger.warning("dbt _schema.yml not found at %s", _DBT_SCHEMA_PATH)
        return frozenset()

    with _DBT_SCHEMA_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "models" not in data:
        return frozenset()

    for model in data["models"]:
        if model.get("name") == model_name:
            cols = model.get("columns", [])
            return frozenset(col["name"] for col in cols if "name" in col)

    logger.warning("dbt model '%s' not found in _schema.yml", model_name)
    return frozenset()


def resolve_baseschema() -> frozenset[str]:
    """Return ``BaseCanvasSchema.COLUMN_NAMES`` as a frozenset.

    This is the 82-column canon of the base canvas schema.
    """
    from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema  # noqa: I001

    return frozenset(BaseCanvasSchema.COLUMN_NAMES)


def resolve_inline(columns: frozenset[str]) -> frozenset[str]:
    """Identity function for ad-hoc Python column sets.

    Parameters
    ----------
    columns:
        Columns declared inline on an asset's metadata.
    """
    return columns


def resolve_dbt_manifest(
    manifest_path: str | Path | None = None,
    *,
    auto_generate: bool = False,
) -> dict[str, frozenset[str]]:
    """Parse dbt's ``manifest.json`` and return column-level dependency info.

    Returns a mapping ``(downstream_node_id, upstream_node_id) →
    frozenset[column_name]`` representing which columns each dbt model
    reads from its upstream refs.

    Parameters
    ----------
    manifest_path:
        Path to ``manifest.json``. Defaults to
        ``brewgis/dbt_project/target/manifest.json``.
    auto_generate:
        If ``True`` and the manifest is stale or missing, runs
        ``dbt docs generate --no-populate-cache`` to produce it.

    Returns
    -------
    dict[str, frozenset[str]]
        Empty dict if the manifest is not found.
    """
    manifest_path = _DBT_MANIFEST_PATH if manifest_path is None else Path(manifest_path)

    if not manifest_path.exists():
        if auto_generate:
            logger.info("Generating dbt manifest via `dbt docs generate`...")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "dbt",
                    "docs",
                    "generate",
                    "--no-populate-cache",
                ],
                cwd=str(_DBT_PROJECT_DIR),
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if result.returncode != 0:
                logger.warning(
                    "dbt docs generate failed (rc=%d): %s",
                    result.returncode,
                    result.stderr[:500],
                )
                return {}
        else:
            logger.info(
                "dbt manifest not found at %s; pass auto_generate=True or run "
                "`dbt docs generate` first",
                manifest_path,
            )
            return {}

    with manifest_path.open(encoding="utf-8") as f:
        manifest = yaml.safe_load(f)

    if not manifest or "nodes" not in manifest:
        return {}

    # Build: node_id → frozenset of column names (output columns)
    node_columns: dict[str, frozenset[str]] = {}
    for node_id, node in manifest["nodes"].items():
        if node.get("resource_type") == "model":
            cols = node.get("columns", {})
            node_columns[node_id] = frozenset(cols.keys())

    # Build: (downstream_node_id, upstream_ref_name) → frozenset of column deps
    # For simplicity: if model A refs model B and A's compiled SQL references
    # column B.x, that's a column dep.  The manifest's "depends_on" includes
    # node-level deps; column-level deps live in "depends_on.columns".
    column_deps: dict[str, frozenset[str]] = {}
    # Not implemented fully — see Phase 5 for full manifest integration.
    # For now, return the node-level column map.
    _ = column_deps  # placeholder
    _ = node_columns  # placeholder

    return node_columns


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: Provenance Checker Core
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ColumnContract:
    """A resolved column contract for a single asset.

    Attributes
    ----------
    asset_key:
        The Dagster asset key this contract applies to.
    columns:
        The set of column names this asset declares as its output.
    source:
        Human-readable label indicating where the contract came from,
        e.g. ``"soda:census_acs"``, ``"dbt:core_end_state"``,
        ``"baseschema"``, ``"inline"``.
    """

    asset_key: AssetKey
    columns: frozenset[str]
    source: str


@dataclass(frozen=True)
class ProvenanceError:
    """A column provenance violation.

    Attributes
    ----------
    downstream:
        The asset that expects a column from upstream.
    upstream:
        The asset that is missing the expected column.
    missing:
        The specific column names that are missing in upstream's contract.
    upstream_source:
        Source label of the upstream contract
        (e.g. ``"baseschema"``, ``"soda:census_acs"``).
    downstream_source:
        Source label of the downstream contract, if any.
    suggestion:
        Optional human-readable suggestion for the fix.
    """

    downstream: AssetKey
    upstream: AssetKey
    missing: frozenset[str]
    upstream_source: str
    downstream_source: str | None = None
    suggestion: str | None = None


# ---------------------------------------------------------------------------
# Contract resolvers registry
# ---------------------------------------------------------------------------

_CONTRACT_RESOLVERS: dict[str, Callable[..., frozenset[str]]] = {
    "soda": resolve_soda_contract,
    "dbt": resolve_dbt_schema,
    "baseschema": resolve_baseschema,
    "inline": resolve_inline,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_contract_from_metadata(
    asset_key: AssetKey,
    metadata: dict,
) -> ColumnContract | None:
    """Resolve a ``ColumnContract`` for an asset based on its metadata.

    Returns ``None`` when no contract metadata is present (pass-through asset).
    """
    source: str | None = metadata.get(METADATA_CONTRACT_SOURCE)
    if source is None:
        return None  # No contract annotation — pass-through

    resolver = _CONTRACT_RESOLVERS.get(source)
    if resolver is None:
        msg = (
            f"Unknown contract source '{source}' for asset {asset_key}. "
            f"Expected one of: {', '.join(_CONTRACT_RESOLVERS)}"
        )
        raise ValueError(msg)

    if source == "inline":
        inline_cols: list[str] | None = metadata.get(METADATA_CONTRACT_INLINE_COLUMNS)
        if inline_cols is None:
            msg = (
                f"Inline contract for {asset_key} has no "
                f"'{METADATA_CONTRACT_INLINE_COLUMNS}' metadata"
            )
            raise ValueError(msg)
        columns = resolve_inline(frozenset(inline_cols))
        source_label = "inline"

    elif source == "baseschema":
        columns = resolver()
        source_label = "baseschema"

    elif source == "soda":
        path: str | None = metadata.get(METADATA_CONTRACT_PATH)
        if path is None:
            msg = (
                f"Soda contract for {asset_key} has no "
                f"'{METADATA_CONTRACT_PATH}' metadata"
            )
            raise ValueError(msg)
        columns = resolver(path)
        source_label = f"soda:{path}"

    elif source == "dbt":
        model_name: str | None = metadata.get(METADATA_CONTRACT_PATH)
        if model_name is None:
            model_name = str(asset_key)
        columns = resolver(model_name)
        source_label = f"dbt:{model_name}"

    else:
        msg = f"Unhandled contract source '{source}' for asset {asset_key}"
        raise ValueError(msg)

    return ColumnContract(
        asset_key=asset_key,
        columns=columns,
        source=source_label,
    )


def _unpack_metadata(metadata: dict) -> dict:
    """Unpack an asset's metadata dict to plain values.

    ``AssetSpec.metadata`` values may be ``MetadataValue`` objects.
    This unwraps them to plain Python types.
    """
    from dagster import MetadataValue

    plain: dict = {}
    for mk, mv in metadata.items():
        if isinstance(mv, MetadataValue):
            plain[mk] = mv.value
        else:
            plain[mk] = mv
    return plain


def _build_suggestion(
    missing: frozenset[str],
    downstream: str,
    upstream: str,
    upstream_source: str,
) -> str | None:
    """Generate a human-readable fix suggestion."""
    missing_list = ", ".join(sorted(missing))
    if upstream_source.startswith("baseschema"):
        # Suggest looking for renamed columns in upstream
        return (
            f"column(s) {{{missing_list}}} not found in {upstream} "
            f"(BaseCanvasSchema). Check if the column was renamed "
            f"(e.g. area_gross → gross_acres) in {downstream}.sql"
        )
    if upstream_source.startswith("soda"):
        return (
            f"column(s) {{{missing_list}}} missing from upstream Soda contract "
            f"for {upstream}. The ACS variable or data source may have changed."
        )
    if upstream_source.startswith("dbt"):
        return (
            f"column(s) {{{missing_list}}} not found in upstream dbt model "
            f"{upstream} ({upstream_source}). Check the model's _schema.yml "
            f"or verify the column is produced upstream."
        )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def make_contract_registry(defs: Definitions) -> dict[AssetKey, ColumnContract]:
    """Build a mapping from every asset key to its column contract.

    Parameters
    ----------
    defs:
        A fully populated ``Definitions`` object.

    Returns
    -------
    dict[AssetKey, ColumnContract]
        Only assets with contract metadata annotations are included.
        Assets without annotations (bulk pass-through) are omitted.
    """
    contracts: dict[AssetKey, ColumnContract] = {}

    for item in (defs.assets or []):
        if hasattr(item, "metadata_by_key") and hasattr(item, "asset_keys"):
            for asset_key, md_map in item.metadata_by_key.items():
                metadata = _unpack_metadata(dict(md_map))
                contract = _resolve_contract_from_metadata(asset_key, metadata)
                if contract is not None:
                    contracts[asset_key] = contract
        elif hasattr(item, "metadata") and hasattr(item, "key"):
            metadata = _unpack_metadata(dict(item.metadata))
            contract = _resolve_contract_from_metadata(item.key, metadata)
            if contract is not None:
                contracts[item.key] = contract

    return contracts


def check_provenance(defs: Definitions) -> list[ProvenanceError]:
    """Walk the Dagster asset graph and verify column provenance.

    For every edge in the asset graph (``downstream → upstream``):
      1. Determine what columns the downstream asset requires from upstream.
      2. Assert that every required column exists in upstream's output
         contract.
      3. Collect any violations as ``ProvenanceError``.

    Parameters
    ----------
    defs:
        A fully populated ``Definitions`` object.

    Returns
    -------
    list[ProvenanceError]
        Empty list when every edge passes.
    """
    graph = defs.resolve_asset_graph()
    contracts = make_contract_registry(defs)

    errors: list[ProvenanceError] = []
    checked_edges: set[tuple[AssetKey, AssetKey]] = set()

    for asset_key in graph.get_all_asset_keys():
        contract = contracts.get(asset_key)
        if contract is None:
            continue  # Pass-through asset, no contract

        for parent_key in graph.get(asset_key).parent_keys:
            edge = (asset_key, parent_key)
            if edge in checked_edges:
                continue
            checked_edges.add(edge)

            parent_contract = contracts.get(parent_key)
            if parent_contract is None:
                continue  # Upstream has no contract

            # What columns does this asset need from upstream?
            # Fallback: the downstream's own output columns must exist
            # upstream (catches alias/drift mismatches).
            # When Phase 5 manifest deps are available, this narrows to
            # only the columns the downstream actually reads.
            needed = _columns_needed_from(
                asset_key,
                parent_key,
                contract,
                parent_contract,
            )

            if not needed:
                continue

            missing = needed - parent_contract.columns
            if missing:
                suggestion = _build_suggestion(
                    missing=missing,
                    downstream=str(asset_key),
                    upstream=str(parent_key),
                    upstream_source=parent_contract.source,
                )
                errors.append(
                    ProvenanceError(
                        downstream=asset_key,
                        upstream=parent_key,
                        missing=missing,
                        upstream_source=parent_contract.source,
                        downstream_source=contract.source,
                        suggestion=suggestion,
                    )
                )

    return errors


def _columns_needed_from(
    _down_key: AssetKey,
    up_key: AssetKey,
    down_contract: ColumnContract,
    _up_contract: ColumnContract,
) -> frozenset[str]:
    """Determine what columns *down_key* needs from *up_key*.

    Resolution order:
      1. dbt manifest column deps (Phase 5) — not yet wired.
      2. ``TableColumnLineage`` annotation on Python assets — not yet wired.
      3. **Fallback**: return the downstream's own output columns. This
         catches alias mismatches (``gross_acres`` declared downstream but
         only ``area_gross`` exists upstream).
    """
    # TODO(jkraus): Wire Phase 5 manifest.json column deps here for dbt→dbt
    # edges. Until then, use the fallback.
    #
    # TODO: Wire TableColumnLineage metadata for Python assets with explicit
    # column mapping.
    _ = up_key  # placeholder (needed for manifest lookup)

    return down_contract.columns


def render_errors(errors: list[ProvenanceError]) -> str:
    """Render provenance errors as human-readable text."""
    lines: list[str] = []
    for err in errors:
        missing_list = ", ".join(sorted(err.missing))
        lines.append(
            f"FAIL: {err.downstream} expects column(s) {{{missing_list}}}\n"
            f"      from upstream {err.upstream} ({err.upstream_source})\n"
            f"      but that source does NOT declare {{{missing_list}}}."
        )
        if err.downstream_source:
            lines.append(f"      downstream contract: {err.downstream_source}")
        if err.suggestion:
            lines.append(f"      suggestion: {err.suggestion}")
        lines.append("")
    if not lines:
        lines.append("PASS: All column provenance checks passed.")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════


def main() -> int:
    """CLI entrypoint: run ``check_provenance`` and print errors.

    Exit codes:
      0 — all checks passed
      1 — one or more provenance errors found
      2 — configuration/import error
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Static column provenance checker for Brew GIS asset graph",
    )
    parser.add_argument(
        "--definitions",
        default="brewgis.workspace.dagster.definitions.defs",
        help="Dotted module path to the Dagster Definitions object (default: "
        "%(default)s)",
    )
    parser.add_argument(
        "--changed-files",
        help="Comma-separated list of changed file paths for incremental mode "
        "(not yet implemented)",
    )
    parser.add_argument(
        "--render",
        action="store_true",
        default=True,
        help="Render errors to stdout (default: true)",
    )
    args = parser.parse_args()
    # Ensure Django is configured before importing asset modules
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")

    django.setup()

    # Import the Definitions object
    import importlib

    module_path, _, obj_name = args.definitions.rpartition(".")
    if not obj_name:
        module_path, obj_name = args.definitions, "defs"

    try:
        mod = importlib.import_module(module_path)
    except ImportError:
        logger.exception("Failed to import %s", module_path)
        return 2

    defs: Definitions = getattr(mod, obj_name)

    errors = check_provenance(defs)

    if args.render:
        print(render_errors(errors))  # noqa: T201

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
