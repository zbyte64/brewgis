"""Tests for the ``explain_sqlmesh_models`` management command.

Covers plan analysis, dependency resolution, and report formatting.
The EXPLAIN runner and SQLMesh discovery functions require a live database.
"""

from __future__ import annotations

from brewgis.workspace.management.commands.explain_sqlmesh_models import ModelInfo
from brewgis.workspace.management.commands.explain_sqlmesh_models import analyze_plan
from brewgis.workspace.management.commands.explain_sqlmesh_models import (
    find_terminal_refs,
)
from brewgis.workspace.management.commands.explain_sqlmesh_models import topology_order

# ═══════════════════════════════════════════════════════════════════════
#  Helper
# ═══════════════════════════════════════════════════════════════════════


def _make_model(
    name: str,
    schema: str = "comparison",
    deps: set[str] | None = None,
) -> ModelInfo:
    return ModelInfo(
        name=name,
        schema=schema,
        kind="FULL",
        qualified=f"brewgis.{schema}.{name}",
        deps=deps or set(),
    )


# ═══════════════════════════════════════════════════════════════════════
#  Dependency resolution
# ═══════════════════════════════════════════════════════════════════════


class TestTopologyOrder:
    """Verify topological sort of model dependencies."""

    def test_single_model(self) -> None:
        models = {"brewgis.comparison.leaf": _make_model("leaf")}
        ordered = topology_order(models, {"brewgis.comparison.leaf"})
        assert len(ordered) == 1
        assert ordered[0].name == "leaf"

    def test_simple_chain(self) -> None:
        models = {
            "brewgis.comparison.base": _make_model("base"),
            "brewgis.comparison.mid": _make_model(
                "mid", deps={"brewgis.comparison.base"}
            ),
            "brewgis.comparison.top": _make_model(
                "top", deps={"brewgis.comparison.mid"}
            ),
        }
        ordered = topology_order(models, {"brewgis.comparison.top"})
        names = [m.name for m in ordered]
        assert names.index("base") < names.index("mid")
        assert names.index("mid") < names.index("top")

    def test_diamond(self) -> None:
        models = {
            "brewgis.comp.root": _make_model("root", schema="comp"),
            "brewgis.comp.left": _make_model(
                "left", schema="comp", deps={"brewgis.comp.root"}
            ),
            "brewgis.comp.right": _make_model(
                "right", schema="comp", deps={"brewgis.comp.root"}
            ),
            "brewgis.comp.top": _make_model(
                "top",
                schema="comp",
                deps={"brewgis.comp.left", "brewgis.comp.right"},
            ),
        }
        ordered = topology_order(models, {"brewgis.comp.top"})
        names = [m.name for m in ordered]
        assert "root" in names
        assert names.index("root") < names.index("left")
        assert names.index("root") < names.index("right")
        assert names.index("left") < names.index("top")
        assert names.index("right") < names.index("top")

    def test_cycle_detected(self) -> None:
        models = {
            "brewgis.comp.a": _make_model("a", schema="comp", deps={"brewgis.comp.b"}),
            "brewgis.comp.b": _make_model("b", schema="comp", deps={"brewgis.comp.a"}),
        }
        ordered = topology_order(models, {"brewgis.comp.a", "brewgis.comp.b"})
        assert len(ordered) == 2

    def test_unreachable_excluded(self) -> None:
        models = {
            "brewgis.comp.a": _make_model("a", schema="comp"),
            "brewgis.comp.b": _make_model("b", schema="comp"),
        }
        ordered = topology_order(models, {"brewgis.comp.a"})
        names = [m.name for m in ordered]
        assert "a" in names
        assert "b" not in names


class TestFindTerminalRefs:
    """Verify detection of external table references."""

    def test_public_refs_are_terminal(self) -> None:
        models = {
            "brewgis.comp.a": _make_model(
                "a", schema="comp", deps={"public.some_table"}
            ),
        }
        terminal = find_terminal_refs(models)
        assert "public.some_table" in terminal

    def test_known_model_not_terminal(self) -> None:
        models = {
            "brewgis.comp.a": _make_model("a", schema="comp", deps={"brewgis.comp.b"}),
            "brewgis.comp.b": _make_model("b", schema="comp"),
        }
        terminal = find_terminal_refs(models)
        assert "brewgis.comp.b" not in terminal

    def test_mixed(self) -> None:
        models = {
            "brewgis.comp.a": _make_model(
                "a",
                schema="comp",
                deps={"brewgis.comp.b", "public.external_tbl"},
            ),
            "brewgis.comp.b": _make_model("b", schema="comp"),
        }
        terminal = find_terminal_refs(models)
        assert "public.external_tbl" in terminal
        assert "brewgis.comp.b" not in terminal


# ═══════════════════════════════════════════════════════════════════════
#  Plan analysis
# ═══════════════════════════════════════════════════════════════════════


class TestAnalyzePlan:
    """Verify EXPLAIN JSON plan parsing and diagnostics."""

    def test_simple_seq_scan(self) -> None:
        plan = {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "test_table",
                "Alias": "test_table",
                "Startup Cost": 0.0,
                "Total Cost": 12450.0,
                "Plan Rows": 500_000,
                "Plan Width": 48,
            },
        }
        pa = analyze_plan(plan)
        assert pa.total_cost == 12450.0
        assert pa.node_count == 1
        assert pa.max_depth == 1
        assert len(pa.seq_scans) == 1
        assert "test_table" in pa.seq_scans[0]
        assert pa.nested_loops == 0

    def test_hash_join_with_index_scan(self) -> None:
        plan = {
            "Plan": {
                "Node Type": "Hash Join",
                "Join Type": "INNER",
                "Startup Cost": 100.0,
                "Total Cost": 5000.0,
                "Plan Rows": 1000,
                "Plan Width": 200,
                "Plans": [
                    {
                        "Node Type": "Index Scan",
                        "Relation Name": "small_table",
                        "Alias": "st",
                        "Index Name": "idx_small_pk",
                        "Startup Cost": 0.0,
                        "Total Cost": 50.0,
                        "Plan Rows": 100,
                        "Plan Width": 100,
                    },
                    {
                        "Node Type": "Hash",
                        "Startup Cost": 30.0,
                        "Total Cost": 30.0,
                        "Plan Rows": 50,
                        "Plan Width": 100,
                        "Plans": [
                            {
                                "Node Type": "Index Only Scan",
                                "Relation Name": "other_table",
                                "Alias": "ot",
                                "Index Name": "idx_other_pk",
                                "Startup Cost": 0.0,
                                "Total Cost": 20.0,
                                "Plan Rows": 50,
                                "Plan Width": 100,
                            },
                        ],
                    },
                ],
            },
        }
        pa = analyze_plan(plan)
        assert pa.total_cost == 5000.0
        assert pa.node_count == 4
        assert pa.max_depth == 3
        assert len(pa.seq_scans) == 0
        assert pa.nested_loops == 0

    def test_nested_loop_detected(self) -> None:
        plan = {
            "Plan": {
                "Node Type": "Nested Loop",
                "Join Type": "INNER",
                "Startup Cost": 100.0,
                "Total Cost": 50000.0,
                "Plan Rows": 10000,
                "Plan Width": 100,
                "Plans": [
                    {
                        "Node Type": "Seq Scan",
                        "Relation Name": "big_table",
                        "Alias": "bt",
                        "Startup Cost": 0.0,
                        "Total Cost": 10000.0,
                        "Plan Rows": 100_000,
                        "Plan Width": 50,
                    },
                    {
                        "Node Type": "Seq Scan",
                        "Relation Name": "other_table",
                        "Alias": "ot",
                        "Startup Cost": 0.0,
                        "Total Cost": 5000.0,
                        "Plan Rows": 50_000,
                        "Plan Width": 50,
                    },
                ],
            },
        }
        pa = analyze_plan(plan)
        assert pa.nested_loops == 1
        assert len(pa.seq_scans) == 2
        assert pa.total_cost == 50000.0

    def test_aggregate_plan(self) -> None:
        plan = {
            "Plan": {
                "Node Type": "Aggregate",
                "Strategy": "Plain",
                "Startup Cost": 1000.0,
                "Total Cost": 1001.0,
                "Plan Rows": 1,
                "Plan Width": 100,
                "Plans": [
                    {
                        "Node Type": "Seq Scan",
                        "Relation Name": "source",
                        "Alias": "s",
                        "Startup Cost": 0.0,
                        "Total Cost": 500.0,
                        "Plan Rows": 5000,
                        "Plan Width": 100,
                    },
                ],
            },
        }
        pa = analyze_plan(plan)
        assert pa.total_cost == 1001.0
        assert pa.node_count == 2
        assert pa.max_depth == 2

    def test_handles_list_plan(self) -> None:
        plan = [
            {
                "Plan": {
                    "Node Type": "Seq Scan",
                    "Relation Name": "t",
                    "Alias": "t",
                    "Startup Cost": 0.0,
                    "Total Cost": 100.0,
                    "Plan Rows": 1000,
                    "Plan Width": 8,
                },
            },
        ]
        pa = analyze_plan(plan)
        assert pa.total_cost == 100.0
        assert pa.node_count == 1

    def test_seq_scan_below_threshold_no_warning(self) -> None:
        plan = {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "tiny",
                "Alias": "tiny",
                "Startup Cost": 0.0,
                "Total Cost": 50.0,
                "Plan Rows": 100,
                "Plan Width": 8,
            },
        }
        pa = analyze_plan(plan)
        assert len(pa.seq_scans) == 0  # below 10k row threshold

    def test_analyze_plan_extracts_actual_timing(self) -> None:
        """ANALYZE output includes Actual Total Time, Actual Rows, Actual Loops."""
        plan = {
            "Plan": {
                "Node Type": "Hash Join",
                "Join Type": "INNER",
                "Startup Cost": 100.0,
                "Total Cost": 5000.0,
                "Plan Rows": 1000,
                "Plan Width": 200,
                "Actual Total Time": 45.2,
                "Actual Rows": 950,
                "Actual Loops": 1,
                "Plans": [
                    {
                        "Node Type": "Seq Scan",
                        "Relation Name": "big_table",
                        "Alias": "bt",
                        "Startup Cost": 0.0,
                        "Total Cost": 1000.0,
                        "Plan Rows": 100_000,
                        "Plan Width": 50,
                        "Actual Total Time": 12.0,
                        "Actual Rows": 95000,
                        "Actual Loops": 1,
                    },
                    {
                        "Node Type": "Hash",
                        "Startup Cost": 80.0,
                        "Total Cost": 80.0,
                        "Plan Rows": 500,
                        "Plan Width": 100,
                        "Actual Total Time": 10.5,
                        "Actual Rows": 480,
                        "Actual Loops": 1,
                        "Plans": [
                            {
                                "Node Type": "Index Scan",
                                "Relation Name": "small_table",
                                "Alias": "st",
                                "Index Name": "idx_small_pk",
                                "Startup Cost": 0.0,
                                "Total Cost": 50.0,
                                "Plan Rows": 500,
                                "Plan Width": 100,
                                "Actual Total Time": 8.2,
                                "Actual Rows": 480,
                                "Actual Loops": 1,
                            },
                        ],
                    },
                ],
            },
        }
        pa = analyze_plan(plan)
        # Root node timing propagated to analysis
        assert pa.actual_total_time == 45.2
        # Root PlanNode has timing
        assert pa.plan_tree is not None
        assert pa.plan_tree.actual_total_time == 45.2
        assert pa.plan_tree.actual_rows == 950
        assert pa.plan_tree.actual_loops == 1
        # Child nodes retain their timing
        seq_node = pa.plan_tree.subplans[0]
        assert seq_node.node_type == "Seq Scan"
        assert seq_node.actual_total_time == 12.0
        assert seq_node.actual_rows == 95000
        # Without ANALYZE, actual timing fields are None
        plan_non_analyze = {
            "Plan": {
                "Node Type": "Seq Scan",
                "Relation Name": "t",
                "Alias": "t",
                "Startup Cost": 0.0,
                "Total Cost": 100.0,
                "Plan Rows": 1000,
                "Plan Width": 8,
            },
        }
        pa2 = analyze_plan(plan_non_analyze)
        assert pa2.actual_total_time is None
        assert pa2.plan_tree is not None
        assert pa2.plan_tree.actual_total_time is None
        assert pa2.plan_tree.actual_rows is None
        assert pa2.plan_tree.actual_loops is None
