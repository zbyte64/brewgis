"""Create ``BaseCanvasColumn`` metadata model.

Column metadata is now stored in the ``BaseCanvasColumn`` Django model rather
than hardcoded in ``base_canvas_schema.py``.  The ``public.base_canvas`` data
table is created by a separate ``CreateModel`` migration for ``BaseCanvas``.
"""

# ruff: noqa: ANN001, ARG001

from __future__ import annotations

from django.db import migrations, models


# ── Seed data for BaseCanvasColumn ────────────────────────────────────
# 83 column definitions that populate the metadata model.

SEED_COLUMNS = [
    # (name, display_order, category, label, pg_type, unit, metatype, aggregation_hint, behavior_category, nullable, default_value)
    # -- Identification & Geometry --
    ("id", 0, "Identification & Geometry", "Feature ID", "SERIAL", "\u2014", "identity", "first", "static", False, None),
    ("id_source", 1, "Identification & Geometry", "ID Source", "VARCHAR(64)", "\u2014", "identity", "first", "static", True, None),
    ("geography_id", 2, "Identification & Geometry", "Geography ID", "INTEGER", "\u2014", "identity", "first", "static", True, None),
    ("geometry_key", 3, "Identification & Geometry", "Geometry Key", "VARCHAR(128)", "\u2014", "identity", "first", "static", True, None),
    ("geometry", 4, "Identification & Geometry", "Geometry", "GEOMETRY(MultiPolygon, 4326)", "\u2014", "geometry", "first", "static", False, None),
    # -- Land Use & Built Form --
    ("land_development_category", 5, "Land Use & Built Form", "Land Development Category", "VARCHAR(64)", "\u2014", "classification", "first", "static", False, ""),
    ("built_form_key", 6, "Land Use & Built Form", "Built Form Key", "VARCHAR(128)", "\u2014", "classification", "first", "static", True, None),
    ("intersection_density", 7, "Land Use & Built Form", "Intersection Density", "DOUBLE PRECISION", "intersections/km\u00b2", "density", "avg", "static", False, 0.0),
    # -- Area & Parcel Geometry --
    ("area_gross", 8, "Area & Parcel Geometry", "Gross Area", "DOUBLE PRECISION", "acres", "area", "sum", "static", False, 0.0),
    ("area_parcel", 9, "Area & Parcel Geometry", "Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_dev_condition", 10, "Area & Parcel Geometry", "Development Condition Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_row", 11, "Area & Parcel Geometry", "Right-of-Way Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_res_detsf", 12, "Area & Parcel Geometry", "Residential Detached SF Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_res_detsf_sl", 13, "Area & Parcel Geometry", "Residential Detached SF Small Lot Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_res_detsf_ll", 14, "Area & Parcel Geometry", "Residential Detached SF Large Lot Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_res_attsf", 15, "Area & Parcel Geometry", "Residential Attached SF Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_res_mf", 16, "Area & Parcel Geometry", "Residential Multi-Family Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_res", 17, "Area & Parcel Geometry", "Total Residential Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_emp", 18, "Area & Parcel Geometry", "Total Employment Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_emp_ret", 19, "Area & Parcel Geometry", "Retail Employment Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_emp_off", 20, "Area & Parcel Geometry", "Office Employment Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_emp_pub", 21, "Area & Parcel Geometry", "Public Employment Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_emp_ind", 22, "Area & Parcel Geometry", "Industrial Employment Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_emp_ag", 23, "Area & Parcel Geometry", "Agricultural Employment Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_emp_military", 24, "Area & Parcel Geometry", "Military Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_mixed_use", 25, "Area & Parcel Geometry", "Mixed Use Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("area_parcel_no_use", 26, "Area & Parcel Geometry", "No Use Parcel Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    # -- Demographics --
    ("pop", 27, "Demographics", "Population", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("pop_groupquarter", 28, "Demographics", "Group Quarters Population", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("hh", 29, "Demographics", "Households", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("du", 30, "Demographics", "Dwelling Units", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    # -- Equity & Environmental Quality --
    ("median_income", 31, "Equity & Environmental Quality", "Median Household Income", "DOUBLE PRECISION", "$/yr", "currency", "avg", "paintable", False, 0.0),
    ("rent_burden_pct", 32, "Equity & Environmental Quality", "Rent Burden (HH >30% income on rent)", "DOUBLE PRECISION", "%", "percentage", "avg", "paintable", False, 0.0),
    ("pct_minority", 33, "Equity & Environmental Quality", "Percent People of Color", "DOUBLE PRECISION", "%", "percentage", "avg", "paintable", False, 0.0),
    ("pct_college_educated", 34, "Equity & Environmental Quality", "Percent College-Educated", "DOUBLE PRECISION", "%", "percentage", "avg", "paintable", False, 0.0),
    ("cost_burden_pct", 35, "Equity & Environmental Quality", "Cost-Burdened Households", "DOUBLE PRECISION", "%", "percentage", "avg", "paintable", False, 0.0),
    # -- Housing by Type --
    ("du_detsf", 36, "Housing by Type", "Detached SF Dwelling Units", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("du_detsf_sl", 37, "Housing by Type", "Detached SF Small Lot Dwelling Units", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("du_detsf_ll", 38, "Housing by Type", "Detached SF Large Lot Dwelling Units", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("du_attsf", 39, "Housing by Type", "Attached SF Dwelling Units", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("du_mf", 40, "Housing by Type", "Multi-Family Dwelling Units", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("du_mf2to4", 41, "Housing by Type", "Multi-Family 2-4 Unit Dwelling Units", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("du_mf5p", 42, "Housing by Type", "Multi-Family 5+ Unit Dwelling Units", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    # -- Employment --
    ("emp", 43, "Employment", "Total Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_ret", 44, "Employment", "Retail Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_retail_services", 45, "Employment", "Retail Services Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_restaurant", 46, "Employment", "Restaurant Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_accommodation", 47, "Employment", "Accommodation Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_arts_entertainment", 48, "Employment", "Arts & Entertainment Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_other_services", 49, "Employment", "Other Services Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_off", 50, "Employment", "Office Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_office_services", 51, "Employment", "Office Services Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_medical_services", 52, "Employment", "Medical Services Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_pub", 53, "Employment", "Public Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_public_admin", 54, "Employment", "Public Administration Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_education", 55, "Employment", "Education Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_ind", 56, "Employment", "Industrial Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_manufacturing", 57, "Employment", "Manufacturing Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_wholesale", 58, "Employment", "Wholesale Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_transport_warehousing", 59, "Employment", "Transport & Warehousing Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_utilities", 60, "Employment", "Utilities Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_construction", 61, "Employment", "Construction Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_ag", 62, "Employment", "Agricultural Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_agriculture", 63, "Employment", "Agriculture Employment (Detailed)", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_extraction", 64, "Employment", "Extraction Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    ("emp_military", 65, "Employment", "Military Employment", "DOUBLE PRECISION", "count", "count", "sum", "paintable", False, 0.0),
    # -- Building Area --
    ("bldg_area_detsf_sl", 66, "Building Area", "Detached SF Small Lot Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_detsf_ll", 67, "Building Area", "Detached SF Large Lot Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_attsf", 68, "Building Area", "Attached SF Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_mf", 69, "Building Area", "Multi-Family Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_retail_services", 70, "Building Area", "Retail Services Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_restaurant", 71, "Building Area", "Restaurant Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_accommodation", 72, "Building Area", "Accommodation Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_arts_entertainment", 73, "Building Area", "Arts & Entertainment Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_other_services", 74, "Building Area", "Other Services Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_office_services", 75, "Building Area", "Office Services Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_public_admin", 76, "Building Area", "Public Administration Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_education", 77, "Building Area", "Education Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_medical_services", 78, "Building Area", "Medical Services Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_transport_warehousing", 79, "Building Area", "Transport & Warehousing Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    ("bldg_area_wholesale", 80, "Building Area", "Wholesale Building Area", "DOUBLE PRECISION", "sq_ft", "area", "sum", "paintable", False, 0.0),
    # -- Irrigation --
    ("residential_irrigated_area", 81, "Irrigation", "Residential Irrigated Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
    ("commercial_irrigated_area", 82, "Irrigation", "Commercial Irrigated Area", "DOUBLE PRECISION", "acres", "area", "sum", "paintable", False, 0.0),
]


def seed_base_canvas_columns(apps, schema_editor) -> None:  # noqa: ARG001
    """Populate the BaseCanvasColumn table from the seed data above."""
    BaseCanvasColumn = apps.get_model("workspace", "BaseCanvasColumn")  # noqa: N806
    objs = [
        BaseCanvasColumn(
            name=name,
            display_order=order,
            category=category,
            label=label,
            pg_type=pg_type,
            unit=unit,
            metatype=metatype,
            aggregation_hint=agg_hint,
            behavior_category=behav,
            nullable=nullable,
            default_value=str(default_val) if default_val is not None else None,
        )
        for name, order, category, label, pg_type, unit, metatype, agg_hint, behav, nullable, default_val in SEED_COLUMNS
    ]
    BaseCanvasColumn.objects.bulk_create(objs)


def unseed_base_canvas_columns(apps, schema_editor) -> None:  # noqa: ARG001
    """Remove all BaseCanvasColumn rows (reverse of seed)."""
    BaseCanvasColumn = apps.get_model("workspace", "BaseCanvasColumn")  # noqa: N806
    BaseCanvasColumn.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("workspace", "0008_painted_canvas"),
    ]

    operations = [
        migrations.CreateModel(
            name="BaseCanvasColumn",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=64, unique=True)),
                ("display_order", models.IntegerField()),
                (
                    "category",
                    models.CharField(
                        blank=True,
                        default="",
                        help_text="Column category (e.g. 'Identification & Geometry', 'Demographics')",
                        max_length=64,
                    ),
                ),
                ("label", models.CharField(blank=True, default="", max_length=255)),
                (
                    "pg_type",
                    models.CharField(
                        blank=True, default="DOUBLE PRECISION", max_length=64
                    ),
                ),
                ("unit", models.CharField(blank=True, default="", max_length=32)),
                (
                    "metatype",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("identity", "Identity"),
                            ("geometry", "Geometry"),
                            ("classification", "Classification"),
                            ("density", "Density"),
                            ("area", "Area"),
                            ("count", "Count"),
                            ("currency", "Currency"),
                            ("percentage", "Percentage"),
                        ],
                        default="count",
                        max_length=32,
                    ),
                ),
                (
                    "aggregation_hint",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("first", "First"),
                            ("sum", "Sum"),
                            ("avg", "Average"),
                        ],
                        default="sum",
                        max_length=16,
                    ),
                ),
                (
                    "behavior_category",
                    models.CharField(
                        blank=True,
                        choices=[("static", "Static"), ("paintable", "Paintable")],
                        default="paintable",
                        max_length=16,
                    ),
                ),
                ("nullable", models.BooleanField(default=False)),
                (
                    "default_value",
                    models.CharField(
                        blank=True, default="", max_length=64, null=True
                    ),
                ),
            ],
            options={
                "ordering": ("display_order",),
                "verbose_name": "base canvas column",
                "verbose_name_plural": "base canvas columns",
            },
        ),
        migrations.RunPython(
            code=seed_base_canvas_columns,
            reverse_code=unseed_base_canvas_columns,
        ),
    ]
