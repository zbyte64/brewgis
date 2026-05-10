"""Management command: export story packet ZIP for an analysis run.

Phase 3b of ROADMAP_2 — generates CSV summaries usable in spreadsheets.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import zipfile
from datetime import datetime
from io import StringIO

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from brewgis.workspace.models import AnalysisRun

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Export a story packet ZIP for an analysis run."

    def add_arguments(self, parser):
        parser.add_argument(
            "--analysis-run",
            type=int,
            required=True,
            help="PK of the AnalysisRun to export.",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default="/tmp/story_packets",
            help="Directory to write the ZIP file.",
        )

    def handle(self, *args, **options):
        run_pk = options["analysis_run"]
        output_dir = options["output_dir"]

        try:
            run = AnalysisRun.objects.get(pk=run_pk)
        except AnalysisRun.DoesNotExist:
            raise CommandError(f"AnalysisRun #{run_pk} not found.")

        scenario = run.scenario
        workspace = run.workspace
        schema = scenario.target_schema
        scenario_id = scenario.slug

        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = os.path.join(
            output_dir,
            f"story_packet_{workspace.name}_{scenario.slug}_{timestamp}.zip",
        )

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1. Aggregate metrics from scenario_summary
            metrics_csv = self._export_table_to_csv(
                schema, f"scenario_summary_{scenario_id}"
            )
            if metrics_csv:
                zf.writestr("aggregate_metrics.csv", metrics_csv)

            # 2. Parcel-level deltas from increment table
            deltas_csv = self._export_table_to_csv(
                schema, f"increment_{scenario_id}"
            )
            if deltas_csv:
                zf.writestr("parcel_deltas.csv", deltas_csv)

            # 3. VMT fee data (available when Phase 2b models have run)
            vmt_fee_csv = self._export_table_to_csv(
                schema, f"vmt_fee_{scenario_id}"
            )
            if vmt_fee_csv:
                zf.writestr("vmt_fee.csv", vmt_fee_csv)

            # 4. Metadata JSON
            metadata = {
                "exported_at": timestamp,
                "workspace": workspace.name,
                "scenario": scenario.name,
                "scenario_id": scenario_id,
                "analysis_run_pk": run.pk,
                "analysis_status": run.status,
                "analysis_modules": run.modules,
                "analysis_vars": run.vars,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat()
                if run.completed_at
                else None,
            }
            zf.writestr("metadata.json", json.dumps(metadata, indent=2))

        self.stdout.write(self.style.SUCCESS(f"Story packet written to {zip_path}"))

    def _export_table_to_csv(self, schema: str, table: str) -> str | None:
        """Query a table and return its contents as CSV string.

        Returns None if the table does not exist or has no rows.
        """
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = %s AND table_name = %s
                )
                """,
                [schema, table],
            )
            if not cursor.fetchone()[0]:
                return None

            cursor.execute(f'SELECT * FROM "{schema}"."{table}"')
            rows = cursor.fetchall()
            if not rows:
                return None

            col_names = [desc[0] for desc in cursor.description]
            buf = StringIO()
            writer = csv.writer(buf)
            writer.writerow(col_names)
            writer.writerows(rows)
            return buf.getvalue()
