"""Tests for the Merge Module (paint edit copying between scenarios)."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.models import MergeAudit
from brewgis.workspace.models import PaintedCanvas
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import ScenarioType
from brewgis.workspace.models import Workspace


def _post_merge(
    client: Client,
    workspace_pk: int,
    source_pk: int,
    target_pk: int,
) -> dict:
    """POST to the merge endpoint and return parsed JSON."""
    url = reverse(
        "workspace:merge_paint_edits",
        kwargs={
            "workspace_pk": workspace_pk,
            "source_pk": source_pk,
            "target_pk": target_pk,
        },
    )
    response = client.post(url, HTTP_HOST="testserver")
    try:
        data = json.loads(response.content)
    except json.JSONDecodeError:
        data = {"error": response.content.decode()}
    data["status"] = response.status_code
    return data


@pytest.mark.integration
class TestMergeModule(TestCase):
    """Tests for merging PaintedCanvas edits between scenarios."""

    @classmethod
    def setUpTestData(cls) -> None:
        """Create test workspace, scenarios, and PaintedCanvas rows."""
        user_model = get_user_model()
        cls.user = user_model.objects.create_user(
            username="merge_tester",
            password="testpass123",
        )
        cls.client_obj = Client()
        cls.client_obj.force_login(cls.user)

        cls.workspace = Workspace.objects.create(name="Test Merge Workspace")
        cls.source = Scenario.objects.create(
            workspace=cls.workspace,
            name="Source Scenario",
            scenario_type=ScenarioType.ALTERNATIVE,
            base_year=2020,
            horizon_year=2050,
        )
        cls.target = Scenario.objects.create(
            workspace=cls.workspace,
            name="Target Scenario",
            scenario_type=ScenarioType.BASE,
            base_year=2020,
            horizon_year=2050,
        )

        # Create approved paint edits in source
        PaintedCanvas.objects.create(
            scenario=cls.source,
            feature_id="parcel-001",
            column_name="du_per_acre",
            painted_value=12.0,
            approval_status="approved",
        )
        PaintedCanvas.objects.create(
            scenario=cls.source,
            feature_id="parcel-002",
            column_name="far",
            painted_value=1.5,
            approval_status="approved",
        )

        # Create a pending paint edit (should NOT be copied)
        PaintedCanvas.objects.create(
            scenario=cls.source,
            feature_id="parcel-003",
            column_name="du_per_acre",
            painted_value=8.0,
            approval_status="pending",
        )

        # Pre-populate target with an existing row (to test duplicate skip)
        PaintedCanvas.objects.create(
            scenario=cls.target,
            feature_id="parcel-001",
            column_name="du_per_acre",
            painted_value=10.0,
            approval_status="approved",
        )

    def test_merge_copies_approved_rows(self) -> None:
        """Approved PaintedCanvas rows from source should be copied to target."""
        data = _post_merge(
            self.client_obj,
            self.workspace.pk,
            self.source.pk,
            self.target.pk,
        )

        assert data["success"] is True
        # 2 approved rows, 1 already exists -> 1 copied, 1 skipped
        assert data["rows_copied"] == 1
        assert data["rows_skipped"] == 1

        # Verify the new row was created in target
        assert PaintedCanvas.objects.filter(
            scenario=self.target,
            feature_id="parcel-002",
            column_name="far",
        ).exists()

        # Verify the existing row in target was preserved (not overwritten)
        existing = PaintedCanvas.objects.get(
            scenario=self.target,
            feature_id="parcel-001",
            column_name="du_per_acre",
        )
        assert existing.painted_value == 10.0  # kept original

    def test_merge_skips_non_approved(self) -> None:
        """Rows with approval_status != 'approved' should NOT be copied."""
        data = _post_merge(
            self.client_obj,
            self.workspace.pk,
            self.source.pk,
            self.target.pk,
        )

        assert data["success"] is True
        # pending paint should not be in target
        assert not PaintedCanvas.objects.filter(
            scenario=self.target,
            feature_id="parcel-003",
        ).exists()

    def test_merge_creates_audit_record(self) -> None:
        """A MergeAudit record should be created after merge."""
        data = _post_merge(
            self.client_obj,
            self.workspace.pk,
            self.source.pk,
            self.target.pk,
        )

        assert data["audit_id"] is not None
        audit = MergeAudit.objects.get(pk=data["audit_id"])
        assert audit.source_scenario == self.source
        assert audit.target_scenario == self.target
        assert audit.rows_copied == 1
        assert audit.rows_skipped == 1
        assert audit.workspace == self.workspace

    def test_merge_same_scenario_returns_error(self) -> None:
        """Merging a scenario into itself should return 400 error."""
        data = _post_merge(
            self.client_obj,
            self.workspace.pk,
            self.source.pk,
            self.source.pk,
        )

        assert data.get("status") == 400
        assert data.get("success") is False

    def test_merge_no_approved_rows_returns_zero(self) -> None:
        """Merging with no approved edits should return rows_copied=0."""
        empty_scenario = Scenario.objects.create(
            workspace=self.workspace,
            name="Empty Scenario",
            scenario_type=ScenarioType.ALTERNATIVE,
            base_year=2020,
            horizon_year=2050,
        )

        data = _post_merge(
            self.client_obj,
            self.workspace.pk,
            empty_scenario.pk,
            self.target.pk,
        )

        assert data["success"] is True
        assert data["rows_copied"] == 0
        assert data["rows_skipped"] == 0
