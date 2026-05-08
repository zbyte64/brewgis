"""Constraint evaluation engine for paint operations.

Checks painted values against workspace-level PaintConstraint rules
and returns structured violation results.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import TYPE_CHECKING

from brewgis.workspace.models import ConstraintOperator
from brewgis.workspace.models import PaintConstraint
from brewgis.workspace.services.canvas_view_manager import PAINTABLE_COLUMNS

if TYPE_CHECKING:
    from brewgis.workspace.models import Workspace


@dataclass
class ConstraintViolation:
    """A single constraint that was violated by a paint operation."""

    feature_id: str
    column: str
    operator: str
    constraint_value: float | None
    painted_value: float | None
    message: str
    severity: str

    def to_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "column": self.column,
            "operator": self.operator,
            "constraint_value": self.constraint_value,
            "painted_value": self.painted_value,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class ConstraintResult:
    """Aggregated result of a constraint batch check."""

    blocked: bool = False
    violations: list[ConstraintViolation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "violations": [v.to_dict() for v in self.violations],
        }


def _evaluate(
    operator: str,
    constraint_value: float | None,
    painted_value: float | None,
) -> bool:
    """Return True if the painted value violates the constraint."""
    if operator == ConstraintOperator.NOT_NULL:
        return painted_value is not None

    # For all other operators, a None painted value never violates
    if painted_value is None or constraint_value is None:
        return False

    # Dispatch table: operator → comparison function
    op_map: dict[str, bool] = {
        ConstraintOperator.EQ: painted_value == constraint_value,
        ConstraintOperator.NEQ: painted_value != constraint_value,
        ConstraintOperator.LT: painted_value < constraint_value,
        ConstraintOperator.LTE: painted_value <= constraint_value,
        ConstraintOperator.GT: painted_value > constraint_value,
        ConstraintOperator.GTE: painted_value >= constraint_value,
    }
    return op_map.get(operator, False)


def check_paint_value(
    workspace: Workspace,
    column: str,
    value: float | None,
    *,
    feature_id: str = "",
) -> list[ConstraintViolation]:
    """Evaluate all constraints for a single column/value pair.

    Returns a list of violations (empty if none triggered).
    """
    constraints = PaintConstraint.objects.filter(
        workspace=workspace,
        column=column,
    )

    return [
        ConstraintViolation(
            feature_id=feature_id,
            column=column,
            operator=constraint.operator,
            constraint_value=constraint.value,
            painted_value=value,
            message=constraint.message,
            severity=constraint.severity,
        )
        for constraint in constraints
        if _evaluate(constraint.operator, constraint.value, value)
    ]


def check_paint_batch(
    workspace: Workspace,
    paint_map: dict[str, dict[str, float | None]],
) -> ConstraintResult:
    """Evaluate constraints for a batch of feature→{column→value} mappings.

    ``paint_map``: ``{feature_id: {column_name: painted_value}}``

    Returns a ``ConstraintResult`` with all violations and a ``blocked``
    flag that is True if *any* blocking constraint was violated.
    """
    all_violations = [
        v
        for feature_id, column_map in paint_map.items()
        for column, value in column_map.items()
        if column in PAINTABLE_COLUMNS
        for v in check_paint_value(workspace, column, value, feature_id=feature_id)
    ]

    blocked = any(v.severity == "block" for v in all_violations)

    return ConstraintResult(
        blocked=blocked,
        violations=all_violations,
    )
