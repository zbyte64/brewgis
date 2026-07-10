"""Management command: generate test seed CSVs for BFT tier model unit testing.

Generates controlled test data for each tier of the parcel_bft classification
pipeline, with known classification outcomes for regression testing.

Usage:
    python manage.py generate_bft_test_seeds --all
    python manage.py generate_bft_test_seeds --tier tier0
    python manage.py generate_bft_test_seeds --tier tier4
"""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

SEEDS_DIR = Path("brewgis/sqlmesh/seeds")


def _write_csv(path: str, rows: list[dict[str, Any]]) -> None:
    """Write a list of dicts as a CSV file."""
    if not rows:
        raise ValueError("No rows for " + path)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(out.getvalue())


# ---- Tier0 test: landuse to BFT mapping edge cases ----------------------


def _gen_tier0_seeds() -> dict[str, str]:
    """Generate test seeds for Tier0 landuse classification.

    Scenarios:
    - A1 at varying lot sizes to SL/LL boundary at 0.15ac
    - A3 to attsf
    - A2 to NULL (falls through)
    - AT to NULL (falls through)
    - CE to NULL (unrecognized code)
    """
    parcels = [
        {
            "apn": "T0_A1_SL_001",
            "lot_size_acres": 0.05,
            "landuse": "A100A",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T0_A1_SL_002",
            "lot_size_acres": 0.14,
            "landuse": "A100A",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T0_A1_LL_001",
            "lot_size_acres": 0.15,
            "landuse": "A100A",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T0_A1_LL_002",
            "lot_size_acres": 0.16,
            "landuse": "A100A",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T0_A1_LL_003",
            "lot_size_acres": 2.0,
            "landuse": "A100A",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T0_A3_001",
            "lot_size_acres": 0.5,
            "landuse": "A300A",
            "zone": "R-2",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T0_A2_001",
            "lot_size_acres": 0.3,
            "landuse": "A200A",
            "zone": "R-3",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T0_AT_001",
            "lot_size_acres": 0.5,
            "landuse": "ATA00A",
            "zone": "R-3",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T0_CE_001",
            "lot_size_acres": 1.0,
            "landuse": "CE000A",
            "zone": "A",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
    ]
    expected = [
        {"apn": "T0_A1_SL_001", "built_form_key": "bt__medium_density_detached_residential"},
        {"apn": "T0_A1_SL_002", "built_form_key": "bt__medium_density_detached_residential"},
        {"apn": "T0_A1_LL_001", "built_form_key": "bt__low_density_detached_residential"},
        {"apn": "T0_A1_LL_002", "built_form_key": "bt__low_density_detached_residential"},
        {"apn": "T0_A1_LL_003", "built_form_key": "bt__low_density_detached_residential"},
        {"apn": "T0_A3_001", "built_form_key": "bt__medium_density_attached_residential"},
    ]
    path_p = str(SEEDS_DIR / "test_bft_tier0_parcels.csv")
    path_e = str(SEEDS_DIR / "test_bft_tier0_expected.csv")
    _write_csv(path_p, parcels)
    _write_csv(path_e, expected)
    return {"tier0_parcels": path_p, "tier0_expected": path_e}


# ---- Tier1 test: sales to BFT mapping -----------------------------------


def _gen_tier1_seeds() -> dict[str, str]:
    """Generate test seeds for Tier1 sales classification.

    Scenarios: SFR lot boundary, Condo to attsf, MF unit boundary,
    commercial, industrial, agricultural, civic, unknown to NULL.
    """
    parcels = [
        {
            "apn": "T1_SFR_SL_001",
            "lot_size_acres": 0.10,
            "landuse": "A100A",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T1_SFR_LL_001",
            "lot_size_acres": 0.20,
            "landuse": "A100A",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T1_CONDO_001",
            "lot_size_acres": 0.5,
            "landuse": "A300A",
            "zone": "R-2",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T1_MF_2TO4_001",
            "lot_size_acres": 1.0,
            "landuse": "A200A",
            "zone": "R-3",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T1_MF_5P_001",
            "lot_size_acres": 2.0,
            "landuse": "A200A",
            "zone": "R-4",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T1_COM_001",
            "lot_size_acres": 0.5,
            "landuse": "CAA00A",
            "zone": "C-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T1_IND_001",
            "lot_size_acres": 2.0,
            "landuse": "IAA00A",
            "zone": "I-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "industrial",
        },
        {
            "apn": "T1_AG_001",
            "lot_size_acres": 20.0,
            "landuse": "AG000A",
            "zone": "A",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "rural",
        },
        {
            "apn": "T1_CIV_001",
            "lot_size_acres": 5.0,
            "landuse": "GCA00A",
            "zone": "P",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T1_UNK_001",
            "lot_size_acres": 0.5,
            "landuse": "A100A",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
    ]
    sales = [
        {
            "apn": "T1_SFR_SL_001",
            "property_type": "SFR",
            "sales_lot_size_acres": 0.10,
            "units": 1,
            "actual_living_sqft": 1200,
            "actual_building_sqft": 1500,
        },
        {
            "apn": "T1_SFR_LL_001",
            "property_type": "SFR",
            "sales_lot_size_acres": 0.20,
            "units": 1,
            "actual_living_sqft": 1800,
            "actual_building_sqft": 2200,
        },
        {
            "apn": "T1_CONDO_001",
            "property_type": "Condo",
            "sales_lot_size_acres": 0.5,
            "units": 1,
            "actual_living_sqft": 900,
            "actual_building_sqft": 900,
        },
        {
            "apn": "T1_MF_2TO4_001",
            "property_type": "Multiple Family Residence",
            "sales_lot_size_acres": 1.0,
            "units": 3,
            "actual_living_sqft": 3000,
            "actual_building_sqft": 4000,
        },
        {
            "apn": "T1_MF_5P_001",
            "property_type": "Multiple Family Residence",
            "sales_lot_size_acres": 2.0,
            "units": 12,
            "actual_living_sqft": 12000,
            "actual_building_sqft": 15000,
        },
        {
            "apn": "T1_COM_001",
            "property_type": "Retail",
            "sales_lot_size_acres": 0.5,
            "units": 0,
            "actual_living_sqft": 0,
            "actual_building_sqft": 3000,
        },
        {
            "apn": "T1_IND_001",
            "property_type": "Warehouse",
            "sales_lot_size_acres": 2.0,
            "units": 0,
            "actual_living_sqft": 0,
            "actual_building_sqft": 10000,
        },
        {
            "apn": "T1_AG_001",
            "property_type": "Farm/Ranch",
            "sales_lot_size_acres": 20.0,
            "units": 0,
            "actual_living_sqft": 2000,
            "actual_building_sqft": 3000,
        },
        {
            "apn": "T1_CIV_001",
            "property_type": "School",
            "sales_lot_size_acres": 5.0,
            "units": 0,
            "actual_living_sqft": 0,
            "actual_building_sqft": 50000,
        },
        {
            "apn": "T1_UNK_001",
            "property_type": "Unknown",
            "sales_lot_size_acres": 0.5,
            "units": 0,
            "actual_living_sqft": 1000,
            "actual_building_sqft": 1200,
        },
    ]
    expected = [
        {"apn": "T1_SFR_SL_001", "built_form_key": "bt__medium_density_detached_residential"},
        {"apn": "T1_SFR_LL_001", "built_form_key": "bt__low_density_detached_residential"},
        {"apn": "T1_CONDO_001", "built_form_key": "bt__medium_density_attached_residential"},
        {"apn": "T1_MF_2TO4_001", "built_form_key": "bt__medium_density_attached_residential"},
        {"apn": "T1_MF_5P_001", "built_form_key": "bt__high_density_attached_residential"},
        {"apn": "T1_COM_001", "built_form_key": "bt__communityneighborhood_retail"},
        {"apn": "T1_IND_001", "built_form_key": "bt__light_industrial"},
        {"apn": "T1_AG_001", "built_form_key": "bt__agriculture"},
        {"apn": "T1_CIV_001", "built_form_key": "bt__publicquasi_public"},
    ]
    path_p = str(SEEDS_DIR / "test_bft_tier1_parcels.csv")
    path_s = str(SEEDS_DIR / "test_bft_tier1_sales.csv")
    path_e = str(SEEDS_DIR / "test_bft_tier1_expected.csv")
    _write_csv(path_p, parcels)
    _write_csv(path_s, sales)
    _write_csv(path_e, expected)
    return {"tier1_parcels": path_p, "tier1_sales": path_s, "tier1_expected": path_e}


# ---- Tier2 test: building footprint to BFT -------------------------------


def _gen_tier2_seeds() -> dict[str, str]:
    """Generate test seeds for Tier2 building footprint classification."""
    parcels = [
        {
            "apn": "T2_A2_MF2TO4_001",
            "lot_size_acres": 1.0,
            "landuse": "A200A",
            "zone": "R-3",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T2_A2_MF5P_001",
            "lot_size_acres": 2.0,
            "landuse": "A200A",
            "zone": "R-4",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T2_AT_MF2TO4_001",
            "lot_size_acres": 0.5,
            "landuse": "ATA00A",
            "zone": "R-3",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T2_DETSF_001",
            "lot_size_acres": 0.25,
            "landuse": "A100A",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T2_MF5P_001",
            "lot_size_acres": 1.0,
            "landuse": "A300A",
            "zone": "R-4",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T2_A2_NONRES_001",
            "lot_size_acres": 0.3,
            "landuse": "A200A",
            "zone": "R-3",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
    ]
    buildings = [
        {
            "apn": "T2_A2_MF2TO4_001",
            "total_footprint_sqft": 8000,
            "building_count": 1,
            "footprint_ratio": 0.18,
            "residential_building_sqft": 6000,
            "commercial_building_sqft": 0,
            "industrial_building_sqft": 0,
            "other_building_sqft": 2000,
            "max_levels": 2,
            "residential_building_count": 1,
            "non_residential_building_count": 0,
            "land_development_category": "urban",
        },
        {
            "apn": "T2_A2_MF5P_001",
            "total_footprint_sqft": 25000,
            "building_count": 1,
            "footprint_ratio": 0.28,
            "residential_building_sqft": 20000,
            "commercial_building_sqft": 0,
            "industrial_building_sqft": 0,
            "other_building_sqft": 5000,
            "max_levels": 5,
            "residential_building_count": 1,
            "non_residential_building_count": 0,
            "land_development_category": "urban",
        },
        {
            "apn": "T2_AT_MF2TO4_001",
            "total_footprint_sqft": 5000,
            "building_count": 1,
            "footprint_ratio": 0.22,
            "residential_building_sqft": 4000,
            "commercial_building_sqft": 0,
            "industrial_building_sqft": 0,
            "other_building_sqft": 1000,
            "max_levels": 2,
            "residential_building_count": 1,
            "non_residential_building_count": 0,
            "land_development_category": "urban",
        },
        {
            "apn": "T2_DETSF_001",
            "total_footprint_sqft": 2000,
            "building_count": 1,
            "footprint_ratio": 0.18,
            "residential_building_sqft": 1800,
            "commercial_building_sqft": 0,
            "industrial_building_sqft": 0,
            "other_building_sqft": 200,
            "max_levels": 1,
            "residential_building_count": 1,
            "non_residential_building_count": 0,
            "land_development_category": "urban",
        },
        {
            "apn": "T2_MF5P_001",
            "total_footprint_sqft": 30000,
            "building_count": 1,
            "footprint_ratio": 0.68,
            "residential_building_sqft": 28000,
            "commercial_building_sqft": 0,
            "industrial_building_sqft": 0,
            "other_building_sqft": 2000,
            "max_levels": 4,
            "residential_building_count": 1,
            "non_residential_building_count": 0,
            "land_development_category": "urban",
        },
        {
            "apn": "T2_A2_NONRES_001",
            "total_footprint_sqft": 4000,
            "building_count": 2,
            "footprint_ratio": 0.30,
            "residential_building_sqft": 0,
            "commercial_building_sqft": 0,
            "industrial_building_sqft": 0,
            "other_building_sqft": 4000,
            "max_levels": 1,
            "residential_building_count": 0,
            "non_residential_building_count": 2,
            "land_development_category": "urban",
        },
    ]
    expected = [
        {"apn": "T2_A2_MF2TO4_001", "built_form_key": "bt__medium_density_attached_residential"},
        {"apn": "T2_A2_MF5P_001", "built_form_key": "bt__high_density_attached_residential"},
        {"apn": "T2_AT_MF2TO4_001", "built_form_key": "bt__medium_density_attached_residential"},
        {"apn": "T2_DETSF_001", "built_form_key": "bt__medium_density_detached_residential"},
        {"apn": "T2_MF5P_001", "built_form_key": "bt__high_density_attached_residential"},
        {"apn": "T2_A2_NONRES_001", "built_form_key": "bt__medium_density_attached_residential"},
    ]
    path_p = str(SEEDS_DIR / "test_bft_tier2_parcels.csv")
    path_b = str(SEEDS_DIR / "test_bft_tier2_buildings.csv")
    path_e = str(SEEDS_DIR / "test_bft_tier2_expected.csv")
    _write_csv(path_p, parcels)
    _write_csv(path_b, buildings)
    _write_csv(path_e, expected)
    return {
        "tier2_parcels": path_p,
        "tier2_buildings": path_b,
        "tier2_expected": path_e,
    }


# ---- Tier4 test: catch-all heuristic -------------------------------------


def _gen_tier4_seeds() -> dict[str, str]:
    """Generate test seeds for Tier4 catch-all heuristic.

    Scenarios: large lot, zone-based, lot size categories, APN parity.
    """
    parcels = [
        {
            "apn": "T4_AG_001",
            "lot_size_acres": 15.0,
            "landuse": "A100A",
            "zone": "A-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "rural",
        },
        {
            "apn": "T4_AG_002",
            "lot_size_acres": 5.0,
            "landuse": "AG000A",
            "zone": "A-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "rural",
        },
        {
            "apn": "T4_DETSF_LL_001",
            "lot_size_acres": 0.5,
            "landuse": "A100A",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "T4_DETSF_SL_001",
            "lot_size_acres": 0.25,
            "landuse": "A100A",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "00000000000002",
            "lot_size_acres": 0.05,
            "landuse": "A300A",
            "zone": "R-2",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "00000000000003",
            "lot_size_acres": 0.05,
            "landuse": "A300A",
            "zone": "R-2",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
    ]
    expected = [
        {"apn": "T4_AG_001", "built_form_key": "bt__agriculture"},
        {"apn": "T4_AG_002", "built_form_key": "bt__agriculture"},
        {"apn": "T4_DETSF_LL_001", "built_form_key": "bt__low_density_detached_residential"},
        {"apn": "T4_DETSF_SL_001", "built_form_key": "bt__medium_density_detached_residential"},
        {"apn": "00000000000002", "built_form_key": "bt__medium_density_attached_residential"},
        {"apn": "00000000000003", "built_form_key": "bt__medium_density_attached_residential"},
    ]
    path_p = str(SEEDS_DIR / "test_bft_tier4_parcels.csv")
    path_e = str(SEEDS_DIR / "test_bft_tier4_expected.csv")
    _write_csv(path_p, parcels)
    _write_csv(path_e, expected)
    return {"tier4_parcels": path_p, "tier4_expected": path_e}


# ---- Resolver integration test -----------------------------------------


def _gen_resolver_seeds() -> dict[str, str]:
    """Generate test seeds for the resolver priority chain.

    Verifies COALESCE priority: tier1 > tier0 > tier2 > tier3 > tier3b > tier4.
    """
    parcels = [
        {
            "apn": "RES_TIER1_WINS_001",
            "lot_size_acres": 0.10,
            "landuse": "A100A",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "RES_TIER0_001",
            "lot_size_acres": 0.5,
            "landuse": "A300A",
            "zone": "R-2",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
        {
            "apn": "RES_NULL_001",
            "lot_size_acres": 0.5,
            "landuse": "BBB00B",
            "zone": "R-1",
            "geometry": "POLYGON((-121.5 38.5,-121.49 38.5,-121.49 38.51,-121.5 38.51,-121.5 38.5))",
            "land_development_category": "urban",
        },
    ]
    sales = [
        {
            "apn": "RES_TIER1_WINS_001",
            "property_type": "Condo",
            "sales_lot_size_acres": 0.10,
            "units": 1,
            "actual_living_sqft": 900,
            "actual_building_sqft": 900,
        },
    ]
    expected = [
        {
            "apn": "RES_TIER1_WINS_001",
            "built_form_key": "bt__medium_density_attached_residential",
            "built_form_key_source": "tier1",
        },
        {
            "apn": "RES_TIER0_001",
            "built_form_key": "bt__medium_density_attached_residential",
            "built_form_key_source": "tier0",
        },
        {"apn": "RES_NULL_001", "built_form_key": "", "built_form_key_source": ""},
    ]
    path_p = str(SEEDS_DIR / "test_bft_resolver_parcels.csv")
    path_s = str(SEEDS_DIR / "test_bft_resolver_sales.csv")
    path_e = str(SEEDS_DIR / "test_bft_resolver_expected.csv")
    _write_csv(path_p, parcels)
    _write_csv(path_s, sales)
    _write_csv(path_e, expected)
    return {
        "resolver_parcels": path_p,
        "resolver_sales": path_s,
        "resolver_expected": path_e,
    }


TIER_GENERATORS = {
    "tier0": _gen_tier0_seeds,
    "tier1": _gen_tier1_seeds,
    "tier2": _gen_tier2_seeds,
    "tier4": _gen_tier4_seeds,
    "resolver": _gen_resolver_seeds,
}


class Command(BaseCommand):
    help = "Generate BFT test seed CSVs for tier model unit testing."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--tier",
            type=str,
            choices=[*list(TIER_GENERATORS), "all"],
            default="all",
            help="Which tier's seeds to generate (default: all).",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Override output directory (default: brewgis/sqlmesh/seeds/).",
        )

    def handle(self, *_args: Any, **options: Any) -> None:
        seeds_dir = (
            SEEDS_DIR if options["output_dir"] is None else Path(options["output_dir"])
        )

        tier = options["tier"]
        tiers_to_run = list(TIER_GENERATORS) if tier == "all" else [tier]

        for t in tiers_to_run:
            generator = TIER_GENERATORS[t]
            files = generator()
            for name, path in files.items():
                self.stdout.write(self.style.SUCCESS(f"  {name}: {path}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nGenerated {len(tiers_to_run)} tier seed set(s) in {seeds_dir}"
            )
        )
