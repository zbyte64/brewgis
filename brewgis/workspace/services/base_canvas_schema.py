"""Base Canvas Schema — single source of truth for all ~82 base canvas columns.

Provides column metadata, category groupings, and classification sets used by
the canvas view manager, ETL pipeline, dbt models, and symbology system.

Column categories (per ``planning/v2/09-base-canvas.md``):

    1. Identification & Geometry
    2. Land Use & Built Form
    3. Area & Parcel Geometry
    4. Demographics
    5. Housing by Type
    6. Employment
    7. Building Area
    8. Irrigation
    9. Equity & Environmental Quality

**Static columns** (passed through verbatim by the painting system):
    id, id_source, geometry_key, geometry, land_development_category,
    built_form_key, intersection_density, area_gross

All other columns are **paintable/summable**.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ColumnDef:
    """Definition of a single base canvas column."""

    name: str
    label: str
    pg_type: str
    unit: str
    metatype: str
    aggregation_hint: str
    behavior_category: str
    nullable: bool = False
    default_value: float | str | None = 0.0


class BaseCanvasSchema:
    """Single source of truth for base canvas table structure."""

    # ── Identification & Geometry ──────────────────────────────────────
    ID = ColumnDef(
        name="id",
        label="Feature ID",
        pg_type="SERIAL",
        unit="—",
        metatype="identity",
        aggregation_hint="first",
        behavior_category="static",
        nullable=False,
        default_value=None,
    )
    ID_SOURCE = ColumnDef(
        name="id_source",
        label="ID Source",
        pg_type="VARCHAR(64)",
        unit="—",
        metatype="identity",
        aggregation_hint="first",
        behavior_category="static",
        nullable=True,
        default_value=None,
    )
    GEOMETRY_KEY = ColumnDef(
        name="geometry_key",
        label="Geometry Key",
        pg_type="VARCHAR(128)",
        unit="—",
        metatype="identity",
        aggregation_hint="first",
        behavior_category="static",
        nullable=True,
        default_value=None,
    )
    GEOMETRY = ColumnDef(
        name="geometry",
        label="Geometry",
        pg_type="GEOMETRY(POLYGON, 4326)",
        unit="—",
        metatype="geometry",
        aggregation_hint="first",
        behavior_category="static",
        nullable=False,
        default_value=None,
    )

    # ── Land Use & Built Form ──────────────────────────────────────────
    LAND_DEVELOPMENT_CATEGORY = ColumnDef(
        name="land_development_category",
        label="Land Development Category",
        pg_type="VARCHAR(64)",
        unit="—",
        metatype="classification",
        aggregation_hint="first",
        behavior_category="static",
        nullable=False,
        default_value="",
    )
    BUILT_FORM_KEY = ColumnDef(
        name="built_form_key",
        label="Built Form Key",
        pg_type="VARCHAR(128)",
        unit="—",
        metatype="classification",
        aggregation_hint="first",
        behavior_category="static",
        nullable=True,
        default_value=None,
    )
    INTERSECTION_DENSITY = ColumnDef(
        name="intersection_density",
        label="Intersection Density",
        pg_type="DOUBLE PRECISION",
        unit="intersections/km²",
        metatype="density",
        aggregation_hint="avg",
        behavior_category="static",
        nullable=False,
        default_value=0.0,
    )

    # ── Area & Parcel Geometry ─────────────────────────────────────────
    AREA_GROSS = ColumnDef(
        name="area_gross",
        label="Gross Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="static",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL = ColumnDef(
        name="area_parcel",
        label="Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_DEV_CONDITION = ColumnDef(
        name="area_dev_condition",
        label="Development Condition Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_ROW = ColumnDef(
        name="area_row",
        label="Right-of-Way Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_RES_DETSF = ColumnDef(
        name="area_parcel_res_detsf",
        label="Residential Detached SF Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_RES_DETSF_SL = ColumnDef(
        name="area_parcel_res_detsf_sl",
        label="Residential Detached SF Small Lot Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_RES_DETSF_LL = ColumnDef(
        name="area_parcel_res_detsf_ll",
        label="Residential Detached SF Large Lot Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_RES_ATTSF = ColumnDef(
        name="area_parcel_res_attsf",
        label="Residential Attached SF Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_RES_MF = ColumnDef(
        name="area_parcel_res_mf",
        label="Residential Multi-Family Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_RES = ColumnDef(
        name="area_parcel_res",
        label="Total Residential Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_EMP = ColumnDef(
        name="area_parcel_emp",
        label="Total Employment Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_EMP_RET = ColumnDef(
        name="area_parcel_emp_ret",
        label="Retail Employment Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_EMP_OFF = ColumnDef(
        name="area_parcel_emp_off",
        label="Office Employment Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_EMP_PUB = ColumnDef(
        name="area_parcel_emp_pub",
        label="Public Employment Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_EMP_IND = ColumnDef(
        name="area_parcel_emp_ind",
        label="Industrial Employment Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_EMP_AG = ColumnDef(
        name="area_parcel_emp_ag",
        label="Agricultural Employment Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_EMP_MILITARY = ColumnDef(
        name="area_parcel_emp_military",
        label="Military Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_MIXED_USE = ColumnDef(
        name="area_parcel_mixed_use",
        label="Mixed Use Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    AREA_PARCEL_NO_USE = ColumnDef(
        name="area_parcel_no_use",
        label="No Use Parcel Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )

    # ── Demographics ───────────────────────────────────────────────────
    POP = ColumnDef(
        name="pop",
        label="Population",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    POP_GROUPQUARTER = ColumnDef(
        name="pop_groupquarter",
        label="Group Quarters Population",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    HH = ColumnDef(
        name="hh",
        label="Households",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    DU = ColumnDef(
        name="du",
        label="Dwelling Units",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )

    # ── Equity & Environmental Quality ──────────────────────────────────
    MEDIAN_INCOME = ColumnDef(
        name="median_income",
        label="Median Household Income",
        pg_type="DOUBLE PRECISION",
        unit="$/yr",
        metatype="currency",
        aggregation_hint="avg",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    RENT_BURDEN_PCT = ColumnDef(
        name="rent_burden_pct",
        label="Rent Burden (HH >30% income on rent)",
        pg_type="DOUBLE PRECISION",
        unit="%",
        metatype="percentage",
        aggregation_hint="avg",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    PCT_MINORITY = ColumnDef(
        name="pct_minority",
        label="Percent People of Color",
        pg_type="DOUBLE PRECISION",
        unit="%",
        metatype="percentage",
        aggregation_hint="avg",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    PCT_COLLEGE_EDUCATED = ColumnDef(
        name="pct_college_educated",
        label="Percent College-Educated",
        pg_type="DOUBLE PRECISION",
        unit="%",
        metatype="percentage",
        aggregation_hint="avg",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    COST_BURDEN_PCT = ColumnDef(
        name="cost_burden_pct",
        label="Cost-Burdened Households",
        pg_type="DOUBLE PRECISION",
        unit="%",
        metatype="percentage",
        aggregation_hint="avg",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )

    # ── Housing by Type ────────────────────────────────────────────────
    DU_DETSF = ColumnDef(
        name="du_detsf",
        label="Detached SF Dwelling Units",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    DU_DETSF_SL = ColumnDef(
        name="du_detsf_sl",
        label="Detached SF Small Lot Dwelling Units",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    DU_DETSF_LL = ColumnDef(
        name="du_detsf_ll",
        label="Detached SF Large Lot Dwelling Units",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    DU_ATTSF = ColumnDef(
        name="du_attsf",
        label="Attached SF Dwelling Units",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    DU_MF = ColumnDef(
        name="du_mf",
        label="Multi-Family Dwelling Units",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    DU_MF2TO4 = ColumnDef(
        name="du_mf2to4",
        label="Multi-Family 2-4 Unit Dwelling Units",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    DU_MF5P = ColumnDef(
        name="du_mf5p",
        label="Multi-Family 5+ Unit Dwelling Units",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )

    # ── Employment ─────────────────────────────────────────────────────
    EMP = ColumnDef(
        name="emp",
        label="Total Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_RET = ColumnDef(
        name="emp_ret",
        label="Retail Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_RETAIL_SERVICES = ColumnDef(
        name="emp_retail_services",
        label="Retail Services Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_RESTAURANT = ColumnDef(
        name="emp_restaurant",
        label="Restaurant Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_ACCOMMODATION = ColumnDef(
        name="emp_accommodation",
        label="Accommodation Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_ARTS_ENTERTAINMENT = ColumnDef(
        name="emp_arts_entertainment",
        label="Arts & Entertainment Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_OTHER_SERVICES = ColumnDef(
        name="emp_other_services",
        label="Other Services Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_OFF = ColumnDef(
        name="emp_off",
        label="Office Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_OFFICE_SERVICES = ColumnDef(
        name="emp_office_services",
        label="Office Services Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_MEDICAL_SERVICES = ColumnDef(
        name="emp_medical_services",
        label="Medical Services Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_PUB = ColumnDef(
        name="emp_pub",
        label="Public Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_PUBLIC_ADMIN = ColumnDef(
        name="emp_public_admin",
        label="Public Administration Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_EDUCATION = ColumnDef(
        name="emp_education",
        label="Education Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_IND = ColumnDef(
        name="emp_ind",
        label="Industrial Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_MANUFACTURING = ColumnDef(
        name="emp_manufacturing",
        label="Manufacturing Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_WHOLESALE = ColumnDef(
        name="emp_wholesale",
        label="Wholesale Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_TRANSPORT_WAREHOUSING = ColumnDef(
        name="emp_transport_warehousing",
        label="Transport & Warehousing Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_UTILITIES = ColumnDef(
        name="emp_utilities",
        label="Utilities Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_CONSTRUCTION = ColumnDef(
        name="emp_construction",
        label="Construction Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_AG = ColumnDef(
        name="emp_ag",
        label="Agricultural Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_AGRICULTURE = ColumnDef(
        name="emp_agriculture",
        label="Agriculture Employment (Detailed)",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_EXTRACTION = ColumnDef(
        name="emp_extraction",
        label="Extraction Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    EMP_MILITARY = ColumnDef(
        name="emp_military",
        label="Military Employment",
        pg_type="DOUBLE PRECISION",
        unit="count",
        metatype="count",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )

    # ── Building Area ──────────────────────────────────────────────────
    BLDG_AREA_DETSF_SL = ColumnDef(
        name="bldg_area_detsf_sl",
        label="Detached SF Small Lot Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_DETSF_LL = ColumnDef(
        name="bldg_area_detsf_ll",
        label="Detached SF Large Lot Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_ATTSF = ColumnDef(
        name="bldg_area_attsf",
        label="Attached SF Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_MF = ColumnDef(
        name="bldg_area_mf",
        label="Multi-Family Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_RETAIL_SERVICES = ColumnDef(
        name="bldg_area_retail_services",
        label="Retail Services Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_RESTAURANT = ColumnDef(
        name="bldg_area_restaurant",
        label="Restaurant Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_ACCOMMODATION = ColumnDef(
        name="bldg_area_accommodation",
        label="Accommodation Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_ARTS_ENTERTAINMENT = ColumnDef(
        name="bldg_area_arts_entertainment",
        label="Arts & Entertainment Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_OTHER_SERVICES = ColumnDef(
        name="bldg_area_other_services",
        label="Other Services Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_OFFICE_SERVICES = ColumnDef(
        name="bldg_area_office_services",
        label="Office Services Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_PUBLIC_ADMIN = ColumnDef(
        name="bldg_area_public_admin",
        label="Public Administration Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_EDUCATION = ColumnDef(
        name="bldg_area_education",
        label="Education Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_MEDICAL_SERVICES = ColumnDef(
        name="bldg_area_medical_services",
        label="Medical Services Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_TRANSPORT_WAREHOUSING = ColumnDef(
        name="bldg_area_transport_warehousing",
        label="Transport & Warehousing Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    BLDG_AREA_WHOLESALE = ColumnDef(
        name="bldg_area_wholesale",
        label="Wholesale Building Area",
        pg_type="DOUBLE PRECISION",
        unit="sq_ft",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )

    # ── Irrigation ─────────────────────────────────────────────────────
    RESIDENTIAL_IRRIGATED_AREA = ColumnDef(
        name="residential_irrigated_area",
        label="Residential Irrigated Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )
    COMMERCIAL_IRRIGATED_AREA = ColumnDef(
        name="commercial_irrigated_area",
        label="Commercial Irrigated Area",
        pg_type="DOUBLE PRECISION",
        unit="acres",
        metatype="area",
        aggregation_hint="sum",
        behavior_category="paintable",
        nullable=False,
        default_value=0.0,
    )

    # ── Aggregated column collections ──────────────────────────────────

    # Ordered list of all column keys (in DDL order — id first, geometry last)
    COLUMN_NAMES: tuple[str, ...] = (
        "id",
        "id_source",
        "geometry_key",
        "geometry",
        "land_development_category",
        "built_form_key",
        "intersection_density",
        "area_gross",
        "area_parcel",
        "area_dev_condition",
        "area_row",
        "area_parcel_res_detsf",
        "area_parcel_res_detsf_sl",
        "area_parcel_res_detsf_ll",
        "area_parcel_res_attsf",
        "area_parcel_res_mf",
        "area_parcel_res",
        "area_parcel_emp",
        "area_parcel_emp_ret",
        "area_parcel_emp_off",
        "area_parcel_emp_pub",
        "area_parcel_emp_ind",
        "area_parcel_emp_ag",
        "area_parcel_emp_military",
        "area_parcel_mixed_use",
        "area_parcel_no_use",
        "pop",
        "pop_groupquarter",
        "hh",
        "du",
        "du_detsf",
        "du_detsf_sl",
        "du_detsf_ll",
        "du_attsf",
        "du_mf",
        "du_mf2to4",
        "du_mf5p",
        "emp",
        "emp_ret",
        "emp_retail_services",
        "emp_restaurant",
        "emp_accommodation",
        "emp_arts_entertainment",
        "emp_other_services",
        "emp_off",
        "emp_office_services",
        "emp_medical_services",
        "emp_pub",
        "emp_public_admin",
        "emp_education",
        "emp_ind",
        "emp_manufacturing",
        "emp_wholesale",
        "emp_transport_warehousing",
        "emp_utilities",
        "emp_construction",
        "emp_ag",
        "emp_agriculture",
        "emp_extraction",
        "emp_military",
        "bldg_area_detsf_sl",
        "bldg_area_detsf_ll",
        "bldg_area_attsf",
        "bldg_area_mf",
        "bldg_area_retail_services",
        "bldg_area_restaurant",
        "bldg_area_accommodation",
        "bldg_area_arts_entertainment",
        "bldg_area_other_services",
        "bldg_area_office_services",
        "bldg_area_public_admin",
        "bldg_area_education",
        "bldg_area_medical_services",
        "bldg_area_transport_warehousing",
        "bldg_area_wholesale",
        "cost_burden_pct",
        "median_income",
        "pct_college_educated",
        "pct_minority",
        "rent_burden_pct",
        "residential_irrigated_area",
        "commercial_irrigated_area",
    )

    # ── Classification sets (computed after class body) ────────────────
    # These are populated at module level after the class definition
    # because generator expressions cannot access class-level names.
    SUMMABLE_COLUMNS: frozenset[str] = frozenset()
    PAINTABLE_COLUMNS: frozenset[str] = frozenset()
    NON_NULL_COLUMNS: frozenset[str] = frozenset()

    # Static columns: passed through verbatim, never painted
    STATIC_COLUMNS: frozenset[str] = frozenset(
        {
            "id",
            "id_source",
            "geometry_key",
            "geometry",
            "land_development_category",
            "built_form_key",
            "intersection_density",
            "area_gross",
        }
    )

    # ── Column metadata lookup ─────────────────────────────────────────

    # Build lookup from attribute name to ColumnDef at import time
    _COLUMNS: dict[str, ColumnDef] = {}

    @classmethod
    def __init_subclass__(cls, **kwargs: object) -> None: ...

    @staticmethod
    def _build_column_map() -> dict[str, ColumnDef]:
        """Build ``name → ColumnDef`` mapping from class attributes."""
        result: dict[str, ColumnDef] = {}
        for attr_name in dir(BaseCanvasSchema):
            attr = getattr(BaseCanvasSchema, attr_name)
            if isinstance(attr, ColumnDef):
                result[attr.name] = attr
        return result

    @classmethod
    def columns(cls) -> dict[str, ColumnDef]:
        """Return ``{column_name: ColumnDef}`` for all base canvas columns."""
        if not cls._COLUMNS:
            cls._COLUMNS = cls._build_column_map()
        return dict(cls._COLUMNS)

    @classmethod
    def get(cls, name: str) -> ColumnDef | None:
        """Get ``ColumnDef`` for *name*, or ``None`` if not found."""
        return cls.columns().get(name)

    @classmethod
    def default_value(cls, name: str) -> float | str | None:
        """Return the default value for *name*, or 0.0 if unknown."""
        col = cls.get(name)
        return col.default_value if col is not None else 0.0

    @classmethod
    def create_table_sql(cls) -> str:
        """Generate the ``CREATE TABLE`` DDL for ``public.base_canvas``."""
        col_defs: list[str] = []
        for name in cls.COLUMN_NAMES:
            col = cls.get(name)
            if col is None:
                continue
            if name == "id":
                col_defs.append("    id SERIAL PRIMARY KEY")
                continue
            if name == "geometry":
                col_defs.append("    geometry GEOMETRY(POLYGON, 4326) NOT NULL")
                continue
            nullable = " NOT NULL" if name in cls.NON_NULL_COLUMNS else ""
            col_defs.append(f"    {name} {col.pg_type}{nullable}")

        joined = ",\n".join(col_defs)
        return f"""CREATE TABLE IF NOT EXISTS public.base_canvas (
{joined}
);
"""

    @classmethod
    def create_indexes_sql(cls) -> list[str]:
        """Return SQL statements for recommended indexes."""
        gist_idx = (
            "CREATE INDEX IF NOT EXISTS idx_base_canvas_geometry "
            "ON public.base_canvas USING GIST (geometry)"
        )
        btree_idx = (
            "CREATE INDEX IF NOT EXISTS idx_base_canvas_land_development_category "
            "ON public.base_canvas (land_development_category)"
        )
        return [gist_idx, btree_idx]

    @classmethod
    def group_by_aggregation_hint(cls) -> dict[str, list[str]]:
        """Return ``{hint: [column_names]}`` for all non-geometry, non-identity columns."""
        groups: dict[str, list[str]] = {}
        for col_def in cls.columns().values():
            if col_def.metatype in ("identity", "geometry"):
                continue
            groups.setdefault(col_def.aggregation_hint, []).append(col_def.name)
        return groups

    @classmethod
    def sum_columns(cls) -> list[str]:
        """Columns that should be area-weighted summed during spatial allocation."""
        return cls.group_by_aggregation_hint().get("sum", [])

    @classmethod
    def avg_columns(cls) -> list[str]:
        """Columns that should be area-weighted averaged during spatial allocation."""
        return cls.group_by_aggregation_hint().get("avg", [])

    @classmethod
    def by_metatype(cls, metatype: str) -> list[str]:
        """Return column names matching the given metatype."""
        return [
            col_def.name
            for col_def in cls.columns().values()
            if col_def.metatype == metatype
        ]


# ── Computed classification sets ────────────────────────────────────
# Generator expressions in the class body can't reference class-level
# names, so we populate these after the class is fully defined.

BaseCanvasSchema.SUMMABLE_COLUMNS = frozenset(
    name
    for name in BaseCanvasSchema.COLUMN_NAMES
    if name not in BaseCanvasSchema.STATIC_COLUMNS
)
BaseCanvasSchema.PAINTABLE_COLUMNS = frozenset(
    name
    for name in BaseCanvasSchema.COLUMN_NAMES
    if name not in BaseCanvasSchema.STATIC_COLUMNS
)
BaseCanvasSchema.NON_NULL_COLUMNS = frozenset(
    name
    for name in BaseCanvasSchema.COLUMN_NAMES
    if name not in {"id_source", "geometry_key", "built_form_key"}
)
