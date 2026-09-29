# ruff: noqa: PT009 — unittest-style TestCase assertions.
"""Tests for built-forms CRUD views and the map shell's Built Forms panel."""

from __future__ import annotations

import pytest
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix
from tests.factories import UserFactory
from tests.factories import WorkspaceFactory


@pytest.mark.views
class TestBuildingTypeViews(TestCase):
    """BuildingType create/edit/delete views."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()

    def test_create_get(self) -> None:
        """GET on create should return 200."""
        self.client.force_login(self.user)
        url = reverse("workspace:building_type_create", args=[self.workspace.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_create_get_htmx_returns_drawer_fragment(self) -> None:
        """hx-get on create should return the form fragment, not the page."""
        self.client.force_login(self.user)
        url = reverse("workspace:building_type_create", args=[self.workspace.pk])
        response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="form-content"')
        self.assertNotContains(response, "<nav")

    def test_create_post_saves(self) -> None:
        """POST with valid data should create a BuildingType."""
        self.client.force_login(self.user)
        url = reverse("workspace:building_type_create", args=[self.workspace.pk])
        response = self.client.post(
            url,
            {
                "name": "Test BT",
                "du_per_acre": "10.0",
                "emp_per_acre": "0",
                "far": "0.8",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            BuildingType.objects.filter(
                name="Test BT", workspace=self.workspace
            ).exists(),
        )

    def test_create_post_plain_redirects_to_map(self) -> None:
        """A non-htmx save lands on the map, where the library now lives."""
        self.client.force_login(self.user)
        url = reverse("workspace:building_type_create", args=[self.workspace.pk])
        response = self.client.post(url, {"name": "BT Redirect Test"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            reverse("workspace:workspace_map", args=[self.workspace.pk]),
        )

    def test_create_post_htmx_stays_in_drawer(self) -> None:
        """An htmx save re-renders the drawer and announces the change."""
        self.client.force_login(self.user)
        url = reverse("workspace:building_type_create", args=[self.workspace.pk])
        response = self.client.post(
            url,
            {"name": "Drawer BT", "du_per_acre": "9"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)

        created = BuildingType.objects.get(name="Drawer BT")
        self.assertContains(response, "Drawer BT")
        # Re-rendered against the row it just made, so a second save updates
        # it instead of trying to create a duplicate name.
        edit_url = reverse(
            "workspace:building_type_edit", args=[self.workspace.pk, created.pk]
        )
        self.assertContains(response, f'action="{edit_url}"')
        self.assertIn("built-forms-changed", response["HX-Trigger"])

    def test_edit_get(self) -> None:
        """GET on edit should return 200."""
        self.client.force_login(self.user)
        bt = BuildingType.objects.create(workspace=self.workspace, name="Editable BT")
        url = reverse("workspace:building_type_edit", args=[self.workspace.pk, bt.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_edit_post(self) -> None:
        """POST should update the BuildingType."""
        self.client.force_login(self.user)
        bt = BuildingType.objects.create(workspace=self.workspace, name="Original")
        url = reverse("workspace:building_type_edit", args=[self.workspace.pk, bt.pk])
        self.client.post(
            url,
            {
                "name": "Updated",
                "du_per_acre": "15.0",
            },
        )
        bt.refresh_from_db()
        self.assertEqual(bt.name, "Updated")
        self.assertEqual(bt.du_per_acre, 15.0)

    def test_create_post_empty_name(self) -> None:
        """POST with empty name should re-render with form error."""
        self.client.force_login(self.user)
        url = reverse("workspace:building_type_create", args=[self.workspace.pk])
        response = self.client.post(
            url,
            {
                "name": "",
                "du_per_acre": "10.0",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")

    def test_create_post_negative_du(self) -> None:
        """POST with negative du_per_acre is accepted (no MinValueValidator on model)."""
        self.client.force_login(self.user)
        url = reverse("workspace:building_type_create", args=[self.workspace.pk])
        response = self.client.post(
            url,
            {
                "name": "Neg BT",
                "du_per_acre": "-5.0",
            },
        )
        assert response.status_code == 302
        assert BuildingType.objects.filter(name="Neg BT", du_per_acre=-5.0).exists()


@pytest.mark.views
class TestPlaceTypeViews(TestCase):
    """PlaceType create/edit/delete views."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()

    def test_create_post(self) -> None:
        """POST with valid data should create a PlaceType."""
        self.client.force_login(self.user)
        url = reverse("workspace:place_type_create", args=[self.workspace.pk])
        response = self.client.post(
            url,
            {
                "name": "Test PT",
                "row_allocation_pct": "30.0",
            },
        )
        self.assertIn(response.status_code, [302, 200])
        self.assertTrue(
            PlaceType.objects.filter(name="Test PT", workspace=self.workspace).exists(),
        )

    def test_edit_post(self) -> None:
        """POST should update the PlaceType."""
        self.client.force_login(self.user)
        pt = PlaceType.objects.create(workspace=self.workspace, name="Original PT")
        url = reverse("workspace:place_type_edit", args=[self.workspace.pk, pt.pk])
        self.client.post(
            url,
            {
                "name": "Updated PT",
                "row_allocation_pct": "35.0",
            },
        )
        pt.refresh_from_db()
        self.assertEqual(pt.name, "Updated PT")
        self.assertEqual(pt.row_allocation_pct, 35.0)

    def test_create_post_empty_name(self) -> None:
        """POST with empty name should re-render with form error."""
        self.client.force_login(self.user)
        url = reverse("workspace:place_type_create", args=[self.workspace.pk])
        response = self.client.post(
            url,
            {
                "name": "",
                "row_allocation_pct": "30.0",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This field is required")


@pytest.mark.views
class TestBuiltFormDelete(TestCase):
    """Deleting a built form from the map's Built Forms panel.

    Regression: the deleted library used standalone DeleteView pages whose
    confirmation template never existed, so every delete click answered 500
    (``TemplateDoesNotExist``) — reported as "attempting to delete a building
    type produces an error". Delete is now a plain POST and the panel
    re-fetches itself off the ``built-forms-changed`` event.
    """

    def setUp(self) -> None:
        self.user = UserFactory()
        self.client.force_login(self.user)
        self.workspace = WorkspaceFactory()

    def test_building_type_delete(self) -> None:
        """POST to delete should remove the BuildingType."""
        bt = BuildingType.objects.create(workspace=self.workspace, name="Deletable BT")
        url = reverse("workspace:building_type_delete", args=[self.workspace.pk, bt.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(BuildingType.objects.filter(pk=bt.pk).exists())

    def test_building_type_delete_htmx_refreshes_panel(self) -> None:
        """An htmx delete removes the row and tells the panel to re-fetch."""
        bt = BuildingType.objects.create(workspace=self.workspace, name="Htmx BT")
        url = reverse("workspace:building_type_delete", args=[self.workspace.pk, bt.pk])
        response = self.client.post(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(BuildingType.objects.filter(pk=bt.pk).exists())
        self.assertIn("built-forms-changed", response["HX-Trigger"])

    def test_building_type_delete_get_is_rejected(self) -> None:
        """GET no longer renders a (missing) confirmation page — it is a 405."""
        bt = BuildingType.objects.create(workspace=self.workspace, name="Get BT")
        url = reverse("workspace:building_type_delete", args=[self.workspace.pk, bt.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)
        self.assertTrue(BuildingType.objects.filter(pk=bt.pk).exists())

    def test_building_type_delete_requires_auth(self) -> None:
        """An anonymous delete is bounced to the login page."""
        self.client.logout()
        bt = BuildingType.objects.create(workspace=self.workspace, name="Auth BT")
        url = reverse("workspace:building_type_delete", args=[self.workspace.pk, bt.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(BuildingType.objects.filter(pk=bt.pk).exists())

    def test_building_type_delete_cascades_place_type_mix(self) -> None:
        """The type's PlaceType mixes go with it."""
        bt = BuildingType.objects.create(workspace=self.workspace, name="Mix BT")
        pt = PlaceType.objects.create(workspace=self.workspace, name="Mix PT")
        PlaceTypeBuildingTypeMix.objects.create(
            place_type=pt, building_type=bt, percentage=100.0
        )
        url = reverse("workspace:building_type_delete", args=[self.workspace.pk, bt.pk])
        self.client.post(url, HTTP_HX_REQUEST="true")
        self.assertFalse(
            PlaceTypeBuildingTypeMix.objects.filter(place_type=pt).exists()
        )

    def test_building_type_delete_scoped_to_workspace(self) -> None:
        """Another workspace's type cannot be deleted through this workspace."""
        other = WorkspaceFactory()
        bt = BuildingType.objects.create(workspace=other, name="Other BT")
        url = reverse("workspace:building_type_delete", args=[self.workspace.pk, bt.pk])
        response = self.client.post(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(BuildingType.objects.filter(pk=bt.pk).exists())

    def test_place_type_delete(self) -> None:
        """POST to delete should remove the PlaceType."""
        pt = PlaceType.objects.create(workspace=self.workspace, name="Deletable PT")
        url = reverse("workspace:place_type_delete", args=[self.workspace.pk, pt.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(PlaceType.objects.filter(pk=pt.pk).exists())

    def test_place_type_delete_htmx_refreshes_panel(self) -> None:
        """An htmx delete removes the row and tells the panel to re-fetch."""
        pt = PlaceType.objects.create(workspace=self.workspace, name="Htmx PT")
        url = reverse("workspace:place_type_delete", args=[self.workspace.pk, pt.pk])
        response = self.client.post(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(PlaceType.objects.filter(pk=pt.pk).exists())
        self.assertIn("built-forms-changed", response["HX-Trigger"])


@pytest.mark.views
class TestBuiltFormsPanel(TestCase):
    """The map shell's Built Forms panel — the library's only browse surface."""

    def setUp(self) -> None:
        self.user = UserFactory()
        self.workspace = WorkspaceFactory()
        self.building_type = BuildingType.objects.create(
            workspace=self.workspace, name="Panel BT", du_per_acre=10.0
        )
        self.place_type = PlaceType.objects.create(
            workspace=self.workspace, name="Panel PT"
        )

    def test_panel_requires_auth(self) -> None:
        """The panel redirects unauthenticated users."""
        url = reverse("workspace:panel_built_forms", args=[self.workspace.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_panel_lists_both_libraries(self) -> None:
        """Both lists render, each with its own create action."""
        self.client.force_login(self.user)
        url = reverse("workspace:panel_built_forms", args=[self.workspace.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Panel BT")
        self.assertContains(response, "Panel PT")
        self.assertContains(
            response,
            reverse("workspace:building_type_create", args=[self.workspace.pk]),
        )
        self.assertContains(
            response,
            reverse("workspace:place_type_create", args=[self.workspace.pk]),
        )

    def test_panel_only_lists_this_workspaces_types(self) -> None:
        """Another workspace's library never shows up in this panel."""
        self.client.force_login(self.user)
        other = WorkspaceFactory()
        BuildingType.objects.create(workspace=other, name="Foreign BT")
        url = reverse("workspace:panel_built_forms", args=[self.workspace.pk])
        response = self.client.get(url)
        self.assertNotContains(response, "Foreign BT")

    def test_panel_empty_state(self) -> None:
        """A workspace with no library says so, on both lists."""
        self.client.force_login(self.user)
        empty = WorkspaceFactory()
        url = reverse("workspace:panel_built_forms", args=[empty.pk])
        response = self.client.get(url)
        self.assertContains(response, "No building types yet.")
        self.assertContains(response, "No place types yet.")

    def test_built_form_options_lists_library(self) -> None:
        """The paint picker's options come from the same library."""
        self.client.force_login(self.user)
        url = reverse("workspace:panel_built_form_options", args=[self.workspace.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Panel BT")
        self.assertContains(response, "Panel PT")
        self.assertContains(response, 'id="bf-optgroup-building"')
        self.assertContains(response, 'id="bf-optgroup-place"')
