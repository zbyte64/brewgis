"""Base test class for dbt model SQL template tests.

Shared template-level checks that apply to all dbt SQL models:
- File existence
- Jinja brace balance
- ``ref('core_end_state')`` FROM clause
- ``config(alias=...)`` with scenario_id
- geom column
- Expected output columns
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest


class DbtModelTemplateTest:
    """Mixin / base for dbt model template verification.

    Subclasses **must** set:
        model_path: ClassVar[Path] — path to the SQL file.
        expected_cols: ClassVar[Sequence[str]] — column names expected in output.
        model_name: ClassVar[str] — dbt model name (for ref() and alias checks).

    Override ``extra_template_checks`` to add per-model assertions.
    """

    model_path: Path
    expected_cols: Sequence[str]
    model_name: str
    uses_ref_core_end_state: bool = True
    uses_config_alias: bool = True

    # ── Fixtures ──────────────────────────────────────────────

    @pytest.fixture
    def sql_template(self) -> str:
        """Read the SQL template for this model."""
        return self.model_path.read_text()

    # ── Core template checks ──────────────────────────────────

    def test_file_exists(self) -> None:
        """Model file must exist."""
        assert self.model_path.exists(), f"Missing {self.model_path}"

    def test_jinja_braces_balanced(self, sql_template: str) -> None:
        """Jinja {{ and {% must be balanced."""
        assert sql_template.count("{{") == sql_template.count("}}"), "Unbalanced {{ }}"
        assert sql_template.count("{%") == sql_template.count("%}"), "Unbalanced {% %}"

    def test_templated_from_statement(self, sql_template: str) -> None:
        """FROM should reference the upstream dbt model via ref()."""
        if self.uses_ref_core_end_state:
            assert "{{ ref('core_end_state') }}" in sql_template
        else:
            # For models referencing other upstreams (e.g. fiscal_net_impact
            # refs fiscal_property_tax), we check for ref(model_name).
            pytest.skip(f"No standard FROM check for {self.model_name}")

    def test_materialized_as_templated(self, sql_template: str) -> None:
        """config(alias=...) should reference scenario_id so multiple
        scenarios can coexist in the same schema."""
        if self.uses_config_alias:
            assert "{{ var('scenario_id') }}" in sql_template, (
                f"{self.model_name} missing scenario_id in config alias"
            )

    def test_has_geom_column(self, sql_template: str) -> None:
        """Must include geom for spatial registration."""
        assert "geom" in sql_template

    @pytest.mark.parametrize("col", [])
    def test_has_output_columns(self, sql_template: str, col: str) -> None:
        """Must include expected output columns."""
        pytest.fail("Override expected_cols and parametrize in subclass")

    # ── Hook for subclass-specific checks ─────────────────────

    def extra_template_checks(self, sql_template: str) -> None:
        """Override to add model-specific assertions."""
