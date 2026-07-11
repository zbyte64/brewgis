"""Management command: seed BuiltFormDefinition table from CSV."""

from __future__ import annotations

import csv
import os

from django.core.management.base import BaseCommand

from brewgis.workspace.models import BuiltFormDefinition


class Command(BaseCommand):
    help = "Seed BuiltFormDefinition table from built_form_definitions.csv"

    def handle(self, *args, **options):
        csv_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "..",
            "brewgis",
            "sqlmesh",
            "seeds",
            "built_form_definitions.csv",
        )
        csv_path = os.path.normpath(csv_path)

        if not os.path.exists(csv_path):
            self.stderr.write(f"Seed file not found: {csv_path}")
            return

        count = 0
        with open(csv_path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row.pop("building_sqft_per_acre", None)  # model field name
                BuiltFormDefinition.objects.update_or_create(
                    key=row["key"],
                    defaults={
                        "name": row["name"],
                        "built_form_category": row["built_form_category"],
                        "du_per_acre": float(row.get("du_per_acre", 0) or 0),
                        "pop_per_acre": float(row.get("pop_per_acre", 0) or 0),
                        "hh_per_acre": float(row.get("hh_per_acre", 0) or 0),
                        "emp_per_acre": float(row.get("emp_per_acre", 0) or 0),
                        "du_detsf_sl_per_acre": float(
                            row.get("du_detsf_sl_per_acre", 0) or 0
                        ),
                        "du_detsf_ll_per_acre": float(
                            row.get("du_detsf_ll_per_acre", 0) or 0
                        ),
                        "du_attsf_per_acre": float(
                            row.get("du_attsf_per_acre", 0) or 0
                        ),
                        "du_mf2to4_per_acre": float(
                            row.get("du_mf2to4_per_acre", 0) or 0
                        ),
                        "du_mf5p_per_acre": float(row.get("du_mf5p_per_acre", 0) or 0),
                        "emp_ret_per_acre": float(row.get("emp_ret_per_acre", 0) or 0),
                        "emp_off_per_acre": float(row.get("emp_off_per_acre", 0) or 0),
                        "emp_pub_per_acre": float(row.get("emp_pub_per_acre", 0) or 0),
                        "emp_ind_per_acre": float(row.get("emp_ind_per_acre", 0) or 0),
                        "emp_ag_per_acre": float(row.get("emp_ag_per_acre", 0) or 0),
                        "intersection_density": float(
                            row.get("intersection_density", 0) or 0
                        ),
                        "building_sqft_per_acre": float(
                            row.get("building_sqft_per_acre", 0) or 0
                        ),
                        "footprint_ratio": float(row.get("footprint_ratio", 0) or 0),
                        "max_levels": int(float(row.get("max_levels", 1) or 1)),
                        "area_parcel_res": float(row.get("area_parcel_res", 0) or 0),
                        "area_parcel_emp": float(row.get("area_parcel_emp", 0) or 0),
                        "area_parcel_mixed_use": float(
                            row.get("area_parcel_mixed_use", 0) or 0
                        ),
                        "is_active": row.get("is_active", "TRUE").upper() == "TRUE",
                    },
                )
                count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Seeded {count} BuiltFormDefinition rows")
        )
