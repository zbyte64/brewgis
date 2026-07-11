"""Export active BuiltFormDefinition rows to public.built_form_definitions table.

The table is used by SQLMesh models (parcel_bft_match) as a CROSS JOIN source
for nearest-prototype matching. Called before SQLMesh plan execution.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from brewgis.workspace.services._db import get_engine

logger = logging.getLogger(__name__)


def export_definitions_to_table() -> int:
    """Export active BuiltFormDefinition rows to public.built_form_definitions.

    Drops and recreates the table to mirror Django model state exactly.
    Returns row count inserted.
    """
    from brewgis.workspace.models import BuiltFormDefinition

    engine = get_engine()
    rows = list(
        BuiltFormDefinition.objects.filter(is_active=True).values(
            "key",
            "name",
            "built_form_category",
            "du_per_acre",
            "pop_per_acre",
            "hh_per_acre",
            "emp_per_acre",
            "du_detsf_sl_per_acre",
            "du_detsf_ll_per_acre",
            "du_attsf_per_acre",
            "du_mf2to4_per_acre",
            "du_mf5p_per_acre",
            "emp_ret_per_acre",
            "emp_off_per_acre",
            "emp_pub_per_acre",
            "emp_ind_per_acre",
            "emp_ag_per_acre",
            "intersection_density",
            "building_sqft_per_acre",
            "footprint_ratio",
            "max_levels",
            "area_parcel_res",
            "area_parcel_emp",
            "area_parcel_mixed_use",
            "is_active",
        )
    )

    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS public.built_form_definitions CASCADE"))
        conn.execute(
            text("""
                CREATE TABLE public.built_form_definitions (
                    key TEXT PRIMARY KEY,
                    name TEXT,
                    built_form_category TEXT,
                    du_per_acre DOUBLE PRECISION DEFAULT 0,
                    pop_per_acre DOUBLE PRECISION DEFAULT 0,
                    hh_per_acre DOUBLE PRECISION DEFAULT 0,
                    emp_per_acre DOUBLE PRECISION DEFAULT 0,
                    du_detsf_sl_per_acre DOUBLE PRECISION DEFAULT 0,
                    du_detsf_ll_per_acre DOUBLE PRECISION DEFAULT 0,
                    du_attsf_per_acre DOUBLE PRECISION DEFAULT 0,
                    du_mf2to4_per_acre DOUBLE PRECISION DEFAULT 0,
                    du_mf5p_per_acre DOUBLE PRECISION DEFAULT 0,
                    emp_ret_per_acre DOUBLE PRECISION DEFAULT 0,
                    emp_off_per_acre DOUBLE PRECISION DEFAULT 0,
                    emp_pub_per_acre DOUBLE PRECISION DEFAULT 0,
                    emp_ind_per_acre DOUBLE PRECISION DEFAULT 0,
                    emp_ag_per_acre DOUBLE PRECISION DEFAULT 0,
                    intersection_density DOUBLE PRECISION DEFAULT 0,
                    building_sqft_per_acre DOUBLE PRECISION DEFAULT 0,
                    footprint_ratio DOUBLE PRECISION DEFAULT 0,
                    max_levels INTEGER DEFAULT 1,
                    area_parcel_res DOUBLE PRECISION DEFAULT 0,
                    area_parcel_emp DOUBLE PRECISION DEFAULT 0,
                    area_parcel_mixed_use DOUBLE PRECISION DEFAULT 0,
                    is_active BOOLEAN DEFAULT TRUE
                )
            """)
        )

    if rows:
        import pandas as pd

        df = pd.DataFrame(rows)
        df.to_sql(
            "built_form_definitions",
            engine,
            schema="public",
            if_exists="append",
            index=False,
            method="multi",
        )

    logger.info(
        "Exported %d built_form_definitions to public.built_form_definitions", len(rows)
    )
    return len(rows)
