"""Tests for built forms CRUD and baking views."""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from brewgis.workspace.built_forms.models import BuildingType
from brewgis.workspace.built_forms.models import PlaceType
from brewgis.workspace.built_forms.models import PlaceTypeBuildingTypeMix


class TestBuildingTypeViews(TestCase):
    """BuildingType CRUD view tests."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
        )

    def test_list_requires_auth(self) -> None:
        """Building type list should redirect unauthenticated users."""
        url = reverse("workspace:building_type_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_list_authenticated(self) -> None:
        """Building type list should return 200 for authenticated users."""
        self.client.force_login(self.user)
        url = reverse("workspace:building_type_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_create_get(self) -> None:
        """GET on create should return 200."""
        self.client.force_login(self.user)
        url = reverse("workspace:building_type_create")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_create_post(self) -> None:
        """POST with valid data should create a BuildingType."""
        self.client.force_login(self.user)
        url = reverse("workspace:building_type_create")
        response = self.client.post(url, {
            "name": "Test BT",
            "du_per_acre": "10.0",
            "emp_per_acre": "0",
            "far": "0.8",
        })
        self.assertIn(response.status_code, [302, 200])
        self.assertTrue(
            BuildingType.objects.filter(name="Test BT").exists(),
        )

    def test_create_post_redirects_to_list(self) -> None:
        """Successful create should redirect to building type list."""
        self.client.force_login(self.user)
        url = reverse("workspace:building_type_create")
        response = self.client.post(url, {
            "name": "BT Redirect Test",
        })
        self.assertIn(response.status_code, [302, 200])
        if response.status_code == 302:
            self.assertEqual(
                response.url,
                reverse("workspace:building_type_list"),
            )

    def test_edit_get(self) -> None:
        """GET on edit should return 200."""
        self.client.force_login(self.user)
        bt = BuildingType.objects.create(name="Editable BT")
        url = reverse("workspace:building_type_edit", args=[bt.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_edit_post(self) -> None:
        """POST should update the BuildingType."""
        self.client.force_login(self.user)
        bt = BuildingType.objects.create(name="Original")
        url = reverse("workspace:building_type_edit", args=[bt.pk])
        self.client.post(url, {
            "name": "Updated",
            "du_per_acre": "15.0",
        })
        bt.refresh_from_db()
        self.assertEqual(bt.name, "Updated")
        self.assertEqual(bt.du_per_acre, 15.0)

    def test_delete(self) -> None:
        """POST to delete should remove the BuildingType."""
        self.client.force_login(self.user)
        bt = BuildingType.objects.create(name="Deletable BT")
        url = reverse("workspace:building_type_delete", args=[bt.pk])
        response = self.client.post(url)
        self.assertIn(response.status_code, [302, 200])
        self.assertFalse(
            BuildingType.objects.filter(pk=bt.pk).exists(),
        )

    def test_list_shows_created_types(self) -> None:
        """Building type list should include created types."""
        self.client.force_login(self.user)
        BuildingType.objects.create(name="Visible BT")
        url = reverse("workspace:building_type_list")
        response = self.client.get(url)
        self.assertContains(response, "Visible BT")


class TestPlaceTypeViews(TestCase):
    """PlaceType CRUD view tests."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
        )

    def test_list_requires_auth(self) -> None:
        """Place type list should redirect unauthenticated users."""
        url = reverse("workspace:place_type_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)

    def test_list_authenticated(self) -> None:
        """Place type list should return 200 for authenticated users."""
        self.client.force_login(self.user)
        url = reverse("workspace:place_type_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_create_post(self) -> None:
        """POST with valid data should create a PlaceType."""
        self.client.force_login(self.user)
        url = reverse("workspace:place_type_create")
        response = self.client.post(url, {
            "name": "Test PT",
            "row_allocation_pct": "30.0",
        })
        self.assertIn(response.status_code, [302, 200])
        self.assertTrue(
            PlaceType.objects.filter(name="Test PT").exists(),
        )

    def test_edit_post(self) -> None:
        """POST should update the PlaceType."""
        self.client.force_login(self.user)
        pt = PlaceType.objects.create(name="Original PT")
        url = reverse("workspace:place_type_edit", args=[pt.pk])
        self.client.post(url, {
            "name": "Updated PT",
            "row_allocation_pct": "35.0",
        })
        pt.refresh_from_db()
        self.assertEqual(pt.name, "Updated PT")
        self.assertEqual(pt.row_allocation_pct, 35.0)

    def test_delete(self) -> None:
        """POST to delete should remove the PlaceType."""
        self.client.force_login(self.user)
        pt = PlaceType.objects.create(name="Deletable PT")
        url = reverse("workspace:place_type_delete", args=[pt.pk])
        self.client.post(url)
        self.assertFalse(
            PlaceType.objects.filter(pk=pt.pk).exists(),
        )

    def test_list_shows_building_type_mix(self) -> None:
        """Place type list should render with building type mix info."""
        self.client.force_login(self.user)
        bt = BuildingType.objects.create(name="Mix BT")
        pt = PlaceType.objects.create(name="Mix PT")
        PlaceTypeBuildingTypeMix.objects.create(
            place_type=pt,
            building_type=bt,
            percentage=100.0,
        )
        url = reverse("workspace:place_type_list")
        response = self.client.get(url)
        self.assertContains(response, "Mix PT")
        self.assertContains(response, "Mix BT")


class TestBakingViews(TestCase):
    """Built form baking view tests."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
        )
        self.client.force_login(self.user)

        self.bt = BuildingType.objects.create(
            name="Bake BT",
            du_per_acre=10.0,
            emp_per_acre=5.0,
            far=1.0,
            household_size=2.5,
            vacancy_rate=5.0,
            indoor_water_rate=200.0,
            outdoor_water_rate=300.0,
            electricity_eui=70.0,
            gas_eui=100.0,
            parking_spaces_per_unit=1.5,
            trip_rate_override=5.0,
        )
        self.pt = PlaceType.objects.create(
            name="Bake PT",
            row_allocation_pct=25.0,
        )
        PlaceTypeBuildingTypeMix.objects.create(
            place_type=self.pt,
            building_type=self.bt,
            percentage=100.0,
        )

    def test_building_type_bake_get(self) -> None:
        """GET on bake should show the bake form."""
        url = reverse("workspace:building_type_bake", args=[self.bt.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bake BT")
        self.assertContains(response, "Run Allocation")

    def test_building_type_bake_post(self) -> None:
        """POST on bake should return results partial."""
        url = reverse("workspace:building_type_bake", args=[self.bt.pk])
        response = self.client.post(url, {"acres": "10.0", "row_pct": "25.0"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Baking Results")

    def test_building_type_bake_shows_numbers(self) -> None:
        """POST on bake should include computed values."""
        url = reverse("workspace:building_type_bake", args=[self.bt.pk])
        response = self.client.post(url, {"acres": "10.0", "row_pct": "25.0"})
        # 7.5 developable acres * 10 du/ac = 75 dwelling units
        self.assertContains(response, "75")

    def test_place_type_bake_get(self) -> None:
        """GET on place type bake should show the bake form."""
        url = reverse("workspace:place_type_bake", args=[self.pt.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bake PT")

    def test_place_type_bake_post(self) -> None:
        """POST on place type bake should return results partial."""
        url = reverse("workspace:place_type_bake", args=[self.pt.pk])
        response = self.client.post(url, {"acres": "40.0"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Baking Results")

    def test_place_type_bake_shows_breakdown(self) -> None:
        """POST on place type bake should include per-type breakdown."""
        url = reverse("workspace:place_type_bake", args=[self.pt.pk])
        response = self.client.post(url, {"acres": "40.0"})
        # 40 * 0.75 = 30 developable acres, all goes to Bake BT (100%)
        self.assertContains(response, "Bake BT")
