# SQLMesh Tunable Parameters & Magic Numbers

This document catalogs every tunable parameter, variable, hard-coded constant,
and magic number throughout the BrewGIS SQLMesh pipeline — organized by pipeline
stage and model module. Entries mark whether the value is a SQLMesh `@variable`
(config.py), a `@macro`, a seed-derived value, or a hard-coded literal in a SQL
or Python model.

Values we have historically tuned (confirmed by git log) are marked with
**History**.

---

## 1. Config Variables (`config.py`)

All `@variable(name, default)` references in models resolve here. Override any
via the `**variables` dict when calling `config_factory()` or via plan overrides.

### 1.1 Year & Geography

| Variable | Default | Used In | Notes |
|---|---|---|---|
| `lodes_year` | `2008` | wac_block_raw, wac_block | LEHD LODES vintage year |
| `acs_year` | `2013` | acs_block_group | ACS 5-year vintage |
| `state_fips` | `"06"` | multiple | California |
| `county_fips` | `"067"` | multiple | Sacramento County |
| `tiger_vintage` | `"2023"` | staging TIGER | TIGER/Line vintage |
| `tiger_block_vintage` | `2020` | staging | Census block vintage |
| `tiger_bg_vintage` | `2013` | staging | Block group vintage |

### 1.2 Spatial Reference Systems

| Variable | Default | Used In | Notes |
|---|---|---|---|
| `local_srid` | `3310` | geometry macro, many models | CA Albers (feet-based) |
| `wm_srid` | `3857` | spatial_ops macro | Web Mercator |
| `default_srid` | `4326` | multiple | WGS84 lon/lat |

### 1.3 DU Estimation

| Variable | Default | Used In | Notes |
|---|---|---|---|
| `min_sqft_per_unit` | `400` | parcel_du_estimation | Floor on MF sqft/unit calibration. **History**: was added by commit a82331b to prevent division by under-counted calibration from producing unrealistically low estimates. |

### 1.4 Overture Data

| Variable | Default | Notes |
|---|---|---|
| `overture_release_tag` | `"2026-05-20.0"` | S3 path template for Overture datasets |
| `overture_bbox_min_x` | `-121.87` | Sacramento County bounding box |
| `overture_bbox_max_x` | `-121.01` | |
| `overture_bbox_min_y` | `38.02` | |
| `overture_bbox_max_y` | `38.74` | |

### 1.5 Built Form

| Variable | Default | Notes |
|---|---|---|
| `res_far_default` | `0.5` | Residential floor-area ratio default when building data missing |

### 1.6 Development

| Variable | Default | Used In | Units | Notes |
|---|---|---|---|---|
| `dev_pct` | `100` | allocation macro | % | % of developable acres actually developed |
| `gross_net_pct` | `85` | allocation macro | % | Gross-to-net acreage ratio (roads, infrastructure) |
| `density_pct` | `100` | core_end_state | % | Density adjustment applied after gross→net |

### 1.7 Fiscal

| Variable | Default | Used In | Notes |
|---|---|---|---|
| `res_assessed_value_per_du` | `350000` | fiscal_property_tax | $/dwelling-unit |
| `nonres_assessed_value_per_sqft` | `150` | fiscal_property_tax | $/sqft |
| `cost_per_du` | `5000` | fiscal_service_costs | $/DU/year (schools & infrastructure) |
| `cost_per_capita` | `2000` | fiscal_service_costs | $/person/year (police, fire, libraries) |
| `cost_per_employee` | `1500` | fiscal_service_costs | $/employee/year (roads & transit) |
| `property_tax_rate` | `1.0` | fiscal_property_tax | % |
| `retail_employment_share` | `15` | fiscal_sales_tax | % of employment that is retail |
| `sales_per_employee` | `100000` | fiscal_sales_tax | $/retail employee/year |
| `sales_tax_rate` | `1.0` | fiscal_sales_tax | % |

### 1.8 Transportation

| Variable | Default | Used In | Notes |
|---|---|---|---|
| `transport_nonres_trip_rate` | `42.94` | trip_generation | Trips/1000 sqft/day (ITE trip gen rate) |
| `transport_pass_by_pct` | `0.0` | trip_generation | Pass-by trip reduction fraction |
| `transport_hbw_pct` | `0.18` | trip_generation | Home-based work trip share |
| `transport_hbo_pct` | `0.42` | trip_generation | Home-based other trip share |
| `transport_nhb_pct` | `0.40` | trip_generation | Non-home-based trip share |
| `transport_circuity_factor` | `1.2` | vmt | Road network directness factor |
| `transport_ghg_co2_per_mile` | `0.411` | transport_ghg | kg CO2e/mi (EPA fleet average) |
| `transport_ghg_speed_adjust` | `False` | transport_ghg | Enable speed-based emission adjustment (+15%) |
| `transport_intrazonal_friction` | `0.15` | internal_capture | Intrazonal trip friction (0=no penalty, 1=max) |
| `transport_km_to_mi` | `0.621371` | vmt | km→mi conversion (physical constant) |

### 1.9 GHG / Energy

| Variable | Default | Used In | Notes |
|---|---|---|---|
| `ghg_egrid_co2_per_kwh` | `0.417` | building_water_ghg | kg CO2e/kWh (eGRID subregion avg) |
| `ghg_gas_co2_per_kwh` | `0.181` | building_water_ghg | kg CO2e/kWh (natural gas) |
| `ghg_water_supply_kwh_per_mg` | `1427` | building_water_ghg | kWh/million gallons |
| `ghg_wastewater_kwh_per_mg` | `1911` | building_water_ghg | kWh/million gallons |
| `ghg_liters_per_million_gallons` | `3785411.78` | building_water_ghg | Unit conversion (physical constant) |

### 1.10 Health

| Variable | Default | Used In | Notes |
|---|---|---|---|
| `health_walk_met` | `3.5` | physical_activity | Metabolic equivalent of task (walking) |
| `health_bike_met` | `6.0` | physical_activity | MET (biking) |
| `health_walk_speed_kmh` | `4.8` | physical_activity | Walking speed km/h |
| `health_bike_speed_kmh` | `16.0` | physical_activity | Biking speed km/h |
| `health_heat_mortality_reduction_pct` | `8.0` | health_impacts | % reduction in heat mortality from physical activity |
| `health_heat_baseline_met_hours_per_week` | `11.25` | health_impacts | Baseline MET-hours/week |
| `health_pm25_intake_fraction` | `1.6e-6` | health_impacts | Fraction of PM2.5 intake from transport emissions |
| `health_pm25_concentration_response` | `0.0062` | health_impacts | Concentration-response coefficient |
| `health_background_dalys_per_capita` | `0.013` | health_impacts | Background DALYs/person/year |
| `health_background_death_rate` | `0.008` | health_impacts | Background death rate |
| `health_weeks_per_year` | `52` | health_impacts | Weeks/year (physical constant) |

### 1.11 Land Consumption / Parking

| Variable | Default | Used In | Notes |
|---|---|---|---|
| `parking_per_unit` | `0.5` | land_consumption | Parking spaces per dwelling unit |
| `parking_per_employee` | `0.2` | land_consumption | Parking spaces per employee |
| `ground_coverage_factor` | `0.6` | land_consumption | Building footprint as fraction of total building sqft |
| `parking_space_sqft` | `300` | land_consumption | Sqft per parking space |
| `row_fraction` | `0.15` | land_consumption | Right-of-way fraction of developed acres |

### 1.12 Stormwater

| Variable | Default | Used In | Notes |
|---|---|---|---|
| `stormwater_annual_precipitation_in` | `12.0` | stormwater_runoff | Annual precipitation inches |

### 1.13 Tree Canopy

| Variable | Default | Used In | Notes |
|---|---|---|---|
| `tree_canopy_baseline_temp` | `95.0` | tree_canopy | Baseline temperature °F |
| `tree_canopy_temp_per_10pct` | `1.0` | tree_canopy | °F reduction per 10% canopy increase |

### 1.14 VMT Mitigation Fee

| Variable | Default | Used In | Notes |
|---|---|---|---|
| `vmt_fee_rate_dollars_per_vmt` | `295.0` | vmt_fee | $/VMT |
| `vmt_exempt_pct` | `0.0` | vmt_fee | % VMT exempt |

### 1.15 Sprawl Cost

| Variable | Default | Used In | Notes |
|---|---|---|---|
| `sprawl_infrastructure_cost_per_du` | `15000` | sprawl_cost | $/DU/year |
| `sprawl_capital_cost_per_du` | `50000` | sprawl_cost | $/DU one-time |

### 1.16 Agriculture

| Variable | Default | Notes |
|---|---|---|
| `crop_yield_per_acre` | `8.0` | tons/acre |
| `crop_market_price_per_ton` | `200` | $/ton |
| `crop_production_cost_per_acre` | `800` | $/acre |
| `crop_water_per_acre_af` | `3.0` | acre-feet/acre |
| `crop_labor_hours_per_acre` | `15` | hours/acre |
| `crop_truck_trips_per_acre` | `2` | trucks/acre |

### 1.17 Housing / Displacement

| Variable | Default | Notes |
|---|---|---|
| `housing_cost_burden_rate` | `0.30` | Fraction of households cost-burdened |
| `housing_severe_burden_rate` | `0.50` | Fraction severely cost-burdened |
| `displacement_income_threshold` | `50000` | $/year |
| `displacement_minority_threshold` | `0.50` | % minority |
| `displacement_rent_burden_threshold` | `0.30` | % rent-burdened |
| `displacement_college_education_threshold` | `0.25` | % college-educated |

### 1.18 Other

| Variable | Default | Notes |
|---|---|---|
| `nonres_indoor_water_rate` | `0.0` | L/employee/day (set to 0 — no non-res water model yet) |

---

## 2. Hard-Coded Magic Numbers in SQL Models

These are **not** exposed as `@variable` and require model editing to tune.
Grouped by model file.

### 2.1 `parcel_bft_tier0_landuse.sql` — Sigmoid SL/LL Split

```sql
-- Intersection-density sigmoid for small-lot / large-lot SFR split
1.0 / (1.0 + EXP(-0.04 * (COALESCE(id.intersection_density, 225.0) - 225.0)))
```

| Constant | Purpose | **History** |
|---|---|---|
| `0.04` | Sigmoid steepness (logistic growth rate) | **Yes** — commit a473de7 |
| `225.0` | Sigmoid midpoint (intersection density inflection) | **Yes** — commit a473de7 |
| `0.08` (acres) | A1 small-lot exemption threshold → attsf instead of detsf_sl | **Yes** — commit e2101e3 |

### 2.2 `parcel_bft_tier2_footprints.sql` — Classification Thresholds

| Constant | Rule | **History** |
|---|---|---|
| `2000` sqft | MF5p when no level data but res bldg >= 2000 sqft | **Yes** — commit 352b004 (was 3000, lowered to 2000) |
| `1.0` acres | A2/AT max lot size for int-density MF5p promotion | **Yes** — commit 9a3e446 (was 0.5, raised to 1.0) |
| `100` (int density) | A2/AT min intersection density for MF5p promotion | **Yes** — commit 9a3e446 (was 200, lowered to 100) |
| `6000` sqft | Non-A2: large bldg on small lot → MF5p | **Yes** — commit e2101e3 |
| `0.5` acres | Non-A2: max lot for bldg≥6000 MF5p rule | Commit e2101e3 |
| `600` sqft | AttSF minimum residential sqft | Original |
| `2500` sqft | AttSF maximum residential sqft | Original |
| `0.3` acres | AttSF max lot size | Original |
| `3` (levels) | AttSF max levels | Original |
| `3` (levels) | MF5p min levels | Original |

### 2.3 `parcel_bft_tier4_catchall.sql` — Catchall

| Constant | Rule | **History** |
|---|---|---|
| `3000` sqft | A2/AT: res sqft >= 3000 → MF5p | Original |
| `100` (int density) | A2/AT: intersection density >= 100 → MF5p | **Yes** — commit 9a3e446 |
| `10.0` acres | Lot size > 10ac → agricultural | Original |
| `0.5` acres | Lot-boundary tier4 lot fraction threshold | Original |

### 2.4 `parcel_du_estimation.sql` — DU 6-Tier Cascade

| Constant | Rule | **History** |
|---|---|---|
| `0, 408, 50` | WIDTH_BUCKET(intersection_density, 0, 408, 50) — bucket range and count for sqft/unit calibration | **Yes** — commit 6299d86 (replaced k-NN) |
| `5` | Minimum calibration parcels per bucket | **Yes** — commit 6299d86 |
| `1259.0` | Global default sqft/unit (mf2to4) | **Yes** — commit a82331b |
| `950.0` | Global default sqft/unit (mf5p) | **Yes** — commit a82331b |
| `0.025` | Vacancy rate (detsf_sl, detsf_ll) | Original |
| `0.050` | Vacancy rate (attsf, mf2to4, urban/mixed, default) | Original |
| `0.080` | Vacancy rate (mf5p) | Original |
| `2.5` | Household size fallback (when ACS data missing) | Original |

### 2.5 `parcel_dasymetric_weights.sql` — Dasymetric Weights

| Constant | Rule | **History** |
|---|---|---|
| `43560 * 0.15` | Pop dasymetric fallback: 15% of lot area (sqft) | **Yes** — commit ea7cc76 |
| `43560 * 0.1` | Emp dasymetric fallback: 10% of lot area (sqft) | **Yes** — commit 0da5445, 1ab92ad |
| `200.0` | Emp weight intersection-density adjustment divisor | **Yes** — commit ea7cc76 |
| `0.0` | Building counts zero threshold for non-residential fallback | Original |

### 2.6 `parcel_bft_tier3_knn.sql` — KNN Imputation

| Constant | Rule | **History** |
|---|---|---|
| `200` | KNN neighbor limit | **Yes** — commit aa6da86 (perf optimization) |
| `3` (std devs) | Lot-size and footprint-ratio z-score filter | **Yes** — commit 0754548 (perf) |
| `5000` (meters) | ST_DWithin max search radius | **Yes** — commit 0754548 (perf) |

### 2.7 `parcel_footprint_imputed.sql` — Footprint KNN

| Constant | Rule | **History** |
|---|---|---|
| `200` | KNN neighbor limit | **Yes** — commit 0754548 (perf) |
| `3` (std devs) | Footprint-ratio z-score filter | **Yes** — commit 0754548 (perf) |
| `5000` (meters) | ST_DWithin max search radius | **Yes** — commit 0754548 (perf) |

### 2.8 `sacog_assessor_parcels.sql` — Parcel Consolidation

| Constant | Rule | **History** |
|---|---|---|
| `3` | Min sub-unit count for convex hull geometry | **Yes** — commit cc9b777 |
| `5.0` (meters) | Buffer for hull (>=3 sub-units) | **Yes** — commit cc9b777 |
| `30.0` (meters) | Buffer for centroid (1-2 sub-units) | **Yes** — commit cc9b777 |

### 2.9 `core_end_state.sql` — Scenario Defaults

| Constant | Rule | Notes |
|---|---|---|
| `2.5` | Household size default fallback | Original |
| `5.0` | Vacancy rate default fallback (%) | Original |
| `30.0` | Building coverage default (%) | Original |
| `43560.0` | Acres → sqft conversion | Physical constant |

### 2.10 `energy_demand.sql` — Unit Conversions

| Constant | Purpose | Notes |
|---|---|---|
| `0.092903` | sqft → m² conversion | Physical constant |
| `43560.0` | acres → sqft | Physical constant |

### 2.11 `land_consumption.sql` — Impervious Surface

| Constant | Purpose | Notes |
|---|---|---|
| `43560.0` | acres → sqft | Physical constant |

### 2.12 `stormwater_runoff.sql` — Simple Method

| Constant | Purpose | Notes |
|---|---|---|
| `0.05` | Runoff coefficient intercept (Simple Method) | Hydrology constant |
| `0.009` | Runoff coefficient slope (per impervious %) | Hydrology constant |
| `0.9` | Volumetric runoff coefficient (Simple Method) | Hydrology constant |
| `12.0` | in/yr → acre-ft/acre (÷12) | Unit conversion |

### 2.13 `overture_intersection_density.sql` — Buffer Radius

| Constant | Purpose | Notes |
|---|---|---|
| `402.0` (meters) | Intersection search radius (~¼ mile) | Micro-scale design parameter |
| `2589988.11` | m² → sq mi conversion (πr² normalization) | Unit: π * 402² m² per sq mi |

### 2.14 `sprawl_index.sql` — Score Weights

| Constant | Purpose | Notes |
|---|---|---|
| `1.0` | Density sub-score weight | Original |
| `1.0` | Connectivity sub-score weight | Original |
| `1.0` | Mixed-use sub-score weight | Original |
| `100.0` | Normalization factor (0-100 scale) | Original |

### 2.15 `sprawl_cost.sql` — Amortization

| Constant | Purpose |
|---|---|
| `30.0` (years) | Capital cost amortization period |

### 2.16 `displacement_risk.sql` — Vulnerability Score

| Constant | Purpose |
|---|---|
| `1, 2, 3, 4` | Vulnerability score thresholds for risk categories |

### 2.17 `internal_capture.sql` — Study Area Scaling

| Constant | Purpose |
|---|---|
| `10.0` | Heuristic scaling factor for study area radius |

### 2.18 `scenario_summary.sql` — Rounding

| Constant | Purpose |
|---|---|
| `2` | ROUND decimal places for monetary values |
| `1` | ROUND decimal places for percentages |

### 2.19 `base_canvas_imputed.sql` — Imputation Thresholds

The base_canvas model contains hard-coded imputation and GREATEST thresholds
that were historically the most frequently tuned values during validation.

| Model | Constant | Purpose | **History** |
|---|---|---|---|
| base_canvas_combined | `2200.0` (sqft_per_du) | Default residential sqft per dwelling unit (calibration_parameters) | **Yes** — iterative |
| base_canvas_combined | `0.9` | AttSF sqft multiplier (sqft_per_du × 0.9) | **Yes** — commit 9a3e446 |
| base_canvas_combined | `600.0` | AttSF building area minimum floor (sqft) | **Yes** — commit 9a3e446 |
| base_canvas_combined | `1.4` | MF5p sqft multiplier | **Yes** — commit e2101e3 |
| base_canvas_combined | `0.7` | MF2to4 sqft multiplier | **Yes** — commit e2101e3 |
| base_canvas_combined | `800.0` | MF building area minimum floor (sqft) | **Yes** — commit e2101e3 |

---

## 3. Python Model Parameters

### 3.1 `trip_distribution.py` — Gravity Model

| Parameter | Default | `_gravity_model()` | Purpose |
|---|---|---|---|
| `b` | `2.0` | keyword arg | Distance decay exponent |
| `emp_weight` | `1.0` | keyword arg | Employment attraction weight |
| `du_weight` | `0.5` | keyword arg | Dwelling unit attraction weight |
| `MIN_DIST` | `1e-10` | local constant | Minimum distance to avoid division-by-zero |
| `BATCH_SIZE` | `2000` | module constant | Batch processing size |

**History**: These were carried forward from the dbt-era Python model and have
not been formally calibrated. The `b=2.0` exponent is a standard gravity-model
default, and the `emp_weight`/`du_weight` ratio is derived from trip generation
attraction factors without local calibration.

### 3.2 `mode_choice.py` — Multinomial Logit

| Parameter | Default | `_multinomial_logit()` | Purpose |
|---|---|---|---|
| `asc_transit` | `-2.0` | keyword arg | Alternative-specific constant (transit) |
| `asc_walk` | `-1.5` | keyword arg | ASC (walk) |
| `asc_bike` | `-2.5` | keyword arg | ASC (bike) |
| `beta_density` | `0.15` | keyword arg | Density sensitivity coefficient |
| `beta_design_walk` | `0.05` | keyword arg | Walkability/intersection density sensitivity |
| `beta_transit_dist` | `0.02` | keyword arg | Transit access sensitivity |

**History**: These are **untuned literature defaults** from standard travel
demand models (not calibrated to Sacramento region). They are high-priority
candidates for sensitivity analysis.

---

## 4. Macro Parameters

### 4.1 `allocation.py`

| Macro | Parameter | Default | Purpose |
|---|---|---|---|
| `compute_applied_acres` | `dev_pct`, `gross_net_pct` | — | Passed through from `@variable` |
| `compute_households` | — | — | Uses `1.0 - vacancy_rate/100` |
| `compute_floor_area` | — | `43560` | acres → sqft (physical constant) |
| `classify_land_dev_category` | `urban_threshold` | `10.0` du/acre | **History**: SACOG-typical threshold |
| | `compact_threshold` | `5.0` du/acre | |
| | `standard_threshold` | `1.0` du/acre | |

### 4.2 `spatial_ops.py`

| Macro | Internal Constant | Purpose |
|---|---|---|
| `compute_allocation_weight` | `4046.86` | Square meters per acre |
| `apply_constraint_discount` | `discount_pct` | % to discount (from constraint_data table) |

### 4.3 `gen_scenario_blueprints.py`

Default built-form COALESCE values:

| Column | Default | Notes |
|---|---|---|
| `household_size` | `2.5` | Fallback when built_forms missing household_size |
| `vacancy_rate` | `5.0` | % |
| All others | `0.0` | |

### 4.4 `generic_tests.py`

| Macro | Parameter | Default | Purpose |
|---|---|---|---|
| `test_proportion_sum` | `tolerance` | `0.01` | Max deviation from 1.0 for proportion assertions |

---

## 5. Seed Calibration Parameters

### 5.1 `calibration_parameters.csv`

Per land-development-category default values used by `base_canvas_combined`:

| Category | sqft_per_du | sqft_per_emp | res_irrigation_frac | com_irrigation_frac | intersection_density |
|---|---|---|---|---|---|
| urban | 2200.0 | 400.0 | 0.064 | 0.035 | 25.0 |
| agricultural | 2200.0 | 300.0 | 0.10 | 0.03 | 2.0 |
| industrial | 2200.0 | 500.0 | 0.05 | 0.035 | 8.0 |
| undeveloped | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 |
| mixed_use | 1500.0 | 400.0 | 0.05 | 0.035 | 20.0 |

**History**: Frequent tuning target — especially `sqft_per_du` (2200 was adjusted
from dbt-era defaults) and per-category intersection_density defaults.

### 5.2 `dasymetric_weights.csv`

| Category | pop_mult | emp_mult | Notes |
|---|---|---|---|
| urban | 1.0 | 0.15 | **History**: emp_mult was 0.0 pre-git history, raised to 0.15 |
| mixed_use | 1.0 | 1.0 | |
| industrial | 0.0 | 2.0 | |
| agricultural | 0.05 | 0.5 | |
| undeveloped | 0.0 | 0.0 | |

### 5.3 `assessor_use_codes.csv`

Maps SACOG assessor use-code prefixes to land_development_category. This is
a fixed mapping and should not be considered tunable unless the jurisdiction's
use-code schema changes.

---

## 6. Audit Thresholds (Hard-Coded)

| Audit | Threshold | Notes |
|---|---|---|
| `assert_allocation_weights_non_negative` | `> 1.0001` | Weight ≤ 1 (+epsilon) acceptance |
| `assert_assessor_building_area` | `> 0.01` | Computation match tolerance |
| `assert_census_block_coverage` | `>= 0.5` DU | **History**: Commit db6b803 raised from hard-coded minimum |
| `assert_bft_sales_mf_unit_boundary` | 2-4 = mf2to4, ≥5 = mf5p | NAHB standard |
| `assert_bft_sales_sfr_lot_boundary` | 0.15 acres threshold | **History**: Defines SL/LL boundary |
| `assert_bft_tier2_sfr_lot_bound` | 0.15 acres | Same boundary |
| `assert_bft_landuse_A1_to_detsf` | sigmoid > 0.5, lot >= 0.08ac | Uses same 0.04/225 sigmoid params |
| `assert_aggregate_consistency` | `> 0.5` | Employment sector sum tolerance |
| `test_proportion_sum` tolerance | `0.01` | Mode share sum tolerance |

---

## 7. Tuning History Summary

From git log, the values we have most frequently tuned to improve model accuracy,
in rough descending order of frequency:

### Most Frequently Tuned

1. **Tier 2 classification thresholds** (sqft boundaries, intersection density,
   lot size thresholds) — 5+ commits directly modifying these numbers, iterative
   improvement through comparison with SACOG reference data.

2. **Building area defaults & GREATEST floors** (sqft_per_du, per-subtype
   multipliers, minimum floor sqft in `base_canvas_combined`) — 4+ commits.

3. **Dasymetric weight fallbacks** (lot-size-based pop/emp fallback fractions
   and intersection-density adjustment) — 3+ commits.

4. **DU calibration bucket parameters** (WIDTH_BUCKET range, count, min parcels
   per bucket, global defaults) — 3+ commits (k-NN → bucket-based transition).

5. **Sigmoid SL/LL split** parameters (steepness, midpoint) — replaced
   fixed 0.15ac lot-size boundary with intersection-density-based sigmoid.

6. **CBP employment proportion variables** (`cbp_11`, `cbp_21`, etc.) —
   parameterized from hard-coded zeros to `@VAR()` references (commit 689af81).

### Tuning Strategy

When tuning, the reference dataset is the SACOG 2016 base map (~508K parcels).
The comparison pipeline (`compare_sacog_basemap` command + SQLMesh comparison
models under `models/comparison/`) computes per-field percentage differences
at aggregate and distributional levels. Key diagnostic metrics:

- **Building area**: Target within ±15% of SACOG reference (category subtype)
- **DU counts**: Target within ±5% of reference
- **Employment**: Target within ±10% of reference (sector-level)
- **Population**: Target within ±5% of Census block totals
- **Vacancy rates**: Should match ACS block-group means for each subtype

---

## 8. Quick Reference: Where to Tune What

| What you want to change | File(s) to edit |
|---|---|
| Scenario development assumptions | Config: `dev_pct`, `gross_net_pct`, `density_pct` |
| Trip generation rates | Config: `transport_nonres_trip_rate`, `transport_hbw/hbo/nhb_pct` |
| GHG emission factors | Config: `ghg_egrid_co2_per_kwh`, `transport_ghg_co2_per_mile` |
| Health impact coefficients | Config: `health_*` variables |
| Fiscal parameters | Config: `res_assessed_value_per_du`, `property_tax_rate`, etc. |
| Parking / land consumption | Config: `parking_*`, `ground_coverage_factor`, `row_fraction` |
| DU estimation calibration | `parcel_du_estimation.sql` (WIDTH_BUCKET range, defaults, vacancy) |
| Building type classification | `parcel_bft_tier2_footprints.sql` (sqft/lot thresholds) |
| Building area imputation | `base_canvas_combined.sql` (GREATEST floors, multipliers) |
| Dasymetric weight fallbacks | `parcel_dasymetric_weights.sql` (lot fractions, int-density divisor) |
| Sigmoid SL/LL split | `parcel_bft_tier0_landuse.sql` (0.04 steepness, 225 midpoint) |
| Gravity model parameters | `models/python/trip_distribution.py` (b, emp_weight, du_weight) |
| Mode choice coefficients | `models/python/mode_choice.py` (asc_*, beta_*) |
| Per-category defaults | `seeds/calibration_parameters.csv` |
| Dasymetric weights per category | `seeds/dasymetric_weights.csv` |
| KNN imputation parameters | `parcel_bft_tier3_knn.sql`, `parcel_footprint_imputed.sql` |
| Employment sector breakdown | Config or wac_block_raw.sql (cbp_* variables) |
