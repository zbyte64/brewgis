"""Tests for Phase 3b: Data Journalism Export (export_story_packet)."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from brewgis.workspace.management.commands.export_story_packet import Command
from brewgis.workspace.models import AnalysisRun
from brewgis.workspace.models import Scenario
from brewgis.workspace.models import Workspace


class TestExportStoryPacketCommand(TestCase):
    """Tests for the export_story_packet management command."""

    def setUp(self):
        self.workspace = Workspace.objects.create(name="Test Workspace")
        self.scenario = Scenario.objects.create(
            name="Test Scenario",
            slug="test-scenario",
            workspace=self.workspace,
            base_year=2020,
            horizon_year=2050,
        )
        self.analysis_run = AnalysisRun.objects.create(
            workspace=self.workspace,
            scenario=self.scenario,
            modules=["core", "vmt"],
            status="completed",
            vars={
                "target_schema": "public",
                "scenario_id": "test-scenario",
            },
        )
        # Patch _export_table_to_csv so tests don't need Postgres-specific schema
        self._export_table_patcher = patch.object(
            Command, "_export_table_to_csv", return_value=None
        )
        self._export_table_patcher.start()

    def tearDown(self):
        self._export_table_patcher.stop()

    def test_export_creates_zip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = StringIO()
            call_command(
                "export_story_packet",
                analysis_run=self.analysis_run.pk,
                output_dir=tmpdir,
                stdout=out,
            )
            zip_files = [f for f in os.listdir(tmpdir) if f.endswith(".zip")]
            assert len(zip_files) == 1, f"Expected 1 ZIP, got {zip_files}"

    def test_export_zip_contains_expected_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            call_command(
                "export_story_packet",
                analysis_run=self.analysis_run.pk,
                output_dir=tmpdir,
            )
            zip_files = [f for f in os.listdir(tmpdir) if f.endswith(".zip")]
            zip_path = os.path.join(tmpdir, zip_files[0])
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                assert "metadata.json" in names, f"Expected metadata.json in {names}"

    def test_export_metadata_contains_scenario_info(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            call_command(
                "export_story_packet",
                analysis_run=self.analysis_run.pk,
                output_dir=tmpdir,
            )
            zip_files = [f for f in os.listdir(tmpdir) if f.endswith(".zip")]
            zip_path = os.path.join(tmpdir, zip_files[0])
            with zipfile.ZipFile(zip_path, "r") as zf:
                metadata = json.loads(zf.read("metadata.json"))
                assert metadata["scenario"] == "Test Scenario"
                assert metadata["workspace"] == "Test Workspace"
                assert metadata["analysis_run_pk"] == self.analysis_run.pk

    def test_export_requires_analysis_run_arg(self):
        """Test that missing --analysis-run argument raises error."""
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("export_story_packet", stdout=out)

    def test_export_nonexistent_run_raises_error(self):
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("export_story_packet", analysis_run=99999, stdout=out)
