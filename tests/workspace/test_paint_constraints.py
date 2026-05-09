"""Tests for paint constraint evaluation engine."""

from __future__ import annotations

import pytest
from django.test import TestCase

from brewgis.workspace.models import ConstraintOperator
from brewgis.workspace.models import ConstraintSeverity
from brewgis.workspace.models import PaintConstraint
from brewgis.workspace.services.paint_constraints import check_paint_batch
from brewgis.workspace.services.paint_constraints import check_paint_value
from tests.factories import WorkspaceFactory


@pytest.mark.integration
class TestCheckPaintValue(TestCase):
    """Tests for :func:`check_paint_value` — single column/value evaluation.

    The ``_evaluate()`` function returns True (violation) when the comparison
    ``painted <op> constraint_value`` is True.  This gives each operator a
    specific semantic (documented in individual tests).
    """

    def setUp(self) -> None:
        self.workspace = WorkspaceFactory()
        self.column = "residential_units"

    def test_no_constraints_no_violations(self) -> None:
        """No PaintConstraint records → no violations."""
        violations = check_paint_value(self.workspace, self.column, 100.0)
        assert len(violations) == 0

    # ── LT  :: flags painted < threshold (minimum floor) ───────────────

    def test_lt_flags_below_threshold(self) -> None:
        """LT flags when painted < constraint_value (values below X are violations)."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.LT,
            value=200.0,
            severity=ConstraintSeverity.BLOCK,
        )
        violations = check_paint_value(self.workspace, self.column, 50.0)
        assert len(violations) == 1

    def test_lt_passes_when_at_or_above(self) -> None:
        """LT does NOT flag when painted >= constraint_value."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.LT,
            value=200.0,
            severity=ConstraintSeverity.BLOCK,
        )
        violations = check_paint_value(self.workspace, self.column, 300.0)
        assert len(violations) == 0

    # ── LTE :: flags painted <= threshold ─────────────────────────────

    def test_lte_flags_at_threshold(self) -> None:
        """LTE flags when painted == constraint_value."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.LTE,
            value=100.0,
            severity=ConstraintSeverity.WARN,
        )
        violations = check_paint_value(self.workspace, self.column, 100.0)
        assert len(violations) == 1

    def test_lte_does_not_flag_above(self) -> None:
        """LTE does NOT flag when painted > constraint_value."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.LTE,
            value=100.0,
            severity=ConstraintSeverity.WARN,
        )
        violations = check_paint_value(self.workspace, self.column, 150.0)
        assert len(violations) == 0

    # ── GT  :: flags painted > threshold (maximum ceiling) ─────────────

    def test_gt_flags_above_threshold(self) -> None:
        """GT flags when painted > constraint_value (values above X are violations)."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.GT,
            value=50.0,
            severity=ConstraintSeverity.BLOCK,
        )
        violations = check_paint_value(self.workspace, self.column, 70.0)
        assert len(violations) == 1

    def test_gt_passes_when_at_or_below(self) -> None:
        """GT does NOT flag when painted <= constraint_value."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.GT,
            value=50.0,
            severity=ConstraintSeverity.BLOCK,
        )
        violations = check_paint_value(self.workspace, self.column, 30.0)
        assert len(violations) == 0

    # ── GTE :: flags painted >= threshold ─────────────────────────────

    def test_gte_flags_at_threshold(self) -> None:
        """GTE flags when painted == constraint_value."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.GTE,
            value=100.0,
            severity=ConstraintSeverity.BLOCK,
        )
        violations = check_paint_value(self.workspace, self.column, 100.0)
        assert len(violations) == 1

    def test_gte_does_not_flag_below(self) -> None:
        """GTE does NOT flag when painted < constraint_value."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.GTE,
            value=100.0,
            severity=ConstraintSeverity.BLOCK,
        )
        violations = check_paint_value(self.workspace, self.column, 50.0)
        assert len(violations) == 0

    # ── EQ  :: flags painted == threshold (value blocklist) ────────────

    def test_eq_flags_exact_value(self) -> None:
        """EQ flags when painted == constraint_value (blocklist)."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.EQ,
            value=42.0,
            severity=ConstraintSeverity.BLOCK,
        )
        violations = check_paint_value(self.workspace, self.column, 42.0)
        assert len(violations) == 1

    def test_eq_does_not_flag_other_values(self) -> None:
        """EQ does NOT flag when painted != constraint_value."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.EQ,
            value=42.0,
            severity=ConstraintSeverity.BLOCK,
        )
        violations = check_paint_value(self.workspace, self.column, 43.0)
        assert len(violations) == 0

    # ── NOT_NULL :: flags any non-None value ──────────────────────────

    def test_not_null_flags_non_none(self) -> None:
        """NOT_NULL flags when painted is not None."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.NOT_NULL,
            severity=ConstraintSeverity.BLOCK,
        )
        violations = check_paint_value(self.workspace, self.column, 0.0)
        assert len(violations) == 1
        assert violations[0].operator == ConstraintOperator.NOT_NULL

    def test_not_null_passes_when_none(self) -> None:
        """NOT_NULL does NOT flag when painted is None."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.NOT_NULL,
            severity=ConstraintSeverity.BLOCK,
        )
        violations = check_paint_value(self.workspace, self.column, None)
        assert len(violations) == 0

    # ── Column / Workspace scoping ────────────────────────────────────

    def test_wrong_column_not_checked(self) -> None:
        """Constraint on different column → not triggered."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column="other_column",
            operator=ConstraintOperator.EQ,
            value=42.0,
            severity=ConstraintSeverity.BLOCK,
        )
        violations = check_paint_value(self.workspace, self.column, 42.0)
        assert len(violations) == 0

    def test_different_workspace_not_checked(self) -> None:
        """Constraint on different workspace → not triggered."""
        other_ws = WorkspaceFactory()
        PaintConstraint.objects.create(
            workspace=other_ws,
            column=self.column,
            operator=ConstraintOperator.EQ,
            value=42.0,
            severity=ConstraintSeverity.BLOCK,
        )
        violations = check_paint_value(self.workspace, self.column, 42.0)
        assert len(violations) == 0

    def test_violation_includes_details(self) -> None:
        """Violation records contain feature_id, column, operator, values."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.LT,
            value=100.0,
            severity=ConstraintSeverity.BLOCK,
            message="Too low!",
        )
        violations = check_paint_value(
            self.workspace, self.column, 50.0, feature_id="f1"
        )
        assert len(violations) == 1
        v = violations[0]
        assert v.feature_id == "f1"
        assert v.column == self.column
        assert v.operator == ConstraintOperator.LT
        assert v.constraint_value == 100.0
        assert v.painted_value == 50.0
        assert v.message == "Too low!"
        assert v.severity == ConstraintSeverity.BLOCK

    # ── Edge cases ────────────────────────────────────────────────────

    def test_none_painted_value_never_violates_comparison_ops(self) -> None:
        """None painted value never violates lt/lte/gt/gte/eq/neq constraints."""
        for op in [
            ConstraintOperator.LT,
            ConstraintOperator.LTE,
            ConstraintOperator.GT,
            ConstraintOperator.GTE,
            ConstraintOperator.EQ,
            ConstraintOperator.NEQ,
        ]:
            PaintConstraint.objects.create(
                workspace=self.workspace,
                column=self.column,
                operator=op,
                value=100.0,
                severity=ConstraintSeverity.BLOCK,
            )
        violations = check_paint_value(self.workspace, self.column, None)
        # Only NOT_NULL would trigger for None
        assert len(violations) == 0

    def test_multiple_constraints_both_violated(self) -> None:
        """Multiple constraints on the same column → all violations returned."""
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.LT,
            value=80.0,
            severity=ConstraintSeverity.BLOCK,
        )
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=self.column,
            operator=ConstraintOperator.GT,
            value=120.0,
            severity=ConstraintSeverity.WARN,
        )
        # 50 < 80 → TRUE (LT violation); 50 > 120 → FALSE (no GT violation)
        violations = check_paint_value(self.workspace, self.column, 50.0)
        assert len(violations) == 1
        assert violations[0].operator == ConstraintOperator.LT

        # 150 < 80 → FALSE (no LT violation); 150 > 120 → TRUE (GT violation)
        violations = check_paint_value(self.workspace, self.column, 150.0)
        assert len(violations) == 1
        assert violations[0].operator == ConstraintOperator.GT

        # 100 < 80 → FALSE (no LT violation); 100 > 120 → FALSE (no GT violation)
        violations = check_paint_value(self.workspace, self.column, 100.0)
        assert len(violations) == 0


@pytest.mark.integration
class TestCheckPaintBatch(TestCase):
    """Tests for :func:`check_paint_batch` — batch evaluation."""

    def setUp(self) -> None:
        self.workspace = WorkspaceFactory()

    def test_empty_batch_no_violations(self) -> None:
        """Empty paint_map → no violations, not blocked."""
        result = check_paint_batch(self.workspace, {})
        assert len(result.violations) == 0
        assert not result.blocked

    def test_batch_returns_all_violations(self) -> None:
        """Batch returns violating entries across features."""
        col = "area_parcel"
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=col,
            operator=ConstraintOperator.LT,
            value=100.0,
            severity=ConstraintSeverity.BLOCK,
        )
        paint_map = {
            "f1": {col: 50.0},
            "f2": {col: 200.0},
        }
        result = check_paint_batch(self.workspace, paint_map)
        assert len(result.violations) == 1
        assert result.violations[0].feature_id == "f1"
        assert result.blocked

    def test_blocking_severity_blocks(self) -> None:
        """BLOCK severity sets blocked=True."""
        col = "area_parcel"
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=col,
            operator=ConstraintOperator.LT,
            value=100.0,
            severity=ConstraintSeverity.BLOCK,
        )
        result = check_paint_batch(
            self.workspace, {"f1": {col: 50.0}}
        )
        assert result.blocked

    def test_warn_severity_does_not_block(self) -> None:
        """WARN severity does not set blocked=True."""
        col = "area_parcel"
        PaintConstraint.objects.create(
            workspace=self.workspace,
            column=col,
            operator=ConstraintOperator.LT,
            value=100.0,
            severity=ConstraintSeverity.WARN,
        )
        result = check_paint_batch(
            self.workspace, {"f1": {col: 50.0}}
        )
        assert not result.blocked
        assert len(result.violations) == 1
