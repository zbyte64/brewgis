MODEL (
  name brewgis.seeds.commercial_energy_baseline,
  kind SEED (
    path '../../seeds/commercial_energy_baseline.csv'
  ),
  description 'Non-residential site energy intensity per CEC Building Climate Zone and building use, from the CPUC DEER commercial prototype simulations.',
  column_descriptions (
    zone = 'CEC Title-24 Building Climate Zone (1-16) the intensities apply to, matching core_end_state.title24_zone.',
    use_type = 'Non-residential use class, one of the eleven bldg_area_* categories core_end_state carries (retail_services, restaurant, accommodation, arts_entertainment, other_services, office_services, public_admin, education, medical_services, transport_warehousing, wholesale).',
    elec_kwh_per_sqft_yr = 'Annual site electricity intensity of the use class (kWh per square foot per year).',
    gas_therm_per_sqft_yr = 'Annual site natural gas intensity of the use class (therms per square foot per year).'
  ),
  columns (
    zone INTEGER,
    use_type TEXT,
    elec_kwh_per_sqft_yr DOUBLE PRECISION,
    gas_therm_per_sqft_yr DOUBLE PRECISION
  )
);

-- Commercial energy baseline — kWh and therms per square foot per year, per
-- CEC Building Climate Zone, by building use.
--
-- energy_demand.sql applies these where a parcel has a climate zone (every
-- California parcel does) and falls back to the built form's flat EUI
-- (electricity_eui / gas_eui) where it does not.
--
-- Source: CPUC CEDARS, DEER Resources → Tools → EnergyPlus, workbook
-- `DOE2_EnergyPlus_Com.xlsx` (posted 2024-05-21, resource id 26):
--   https://cedars.cpuc.ca.gov/deer-resources/tools/energy-plus/file/3116/download
-- It publishes the annual EnergyPlus simulation results of the CPUC's DEER
-- commercial prototype buildings — 26 prototypes × CZ01..CZ16 × two vintages
-- (`Ex` existing, `New` new construction). Workbook sha256
-- c6f43312ba5ba46622d4cba1c7d329b030f4d3fa484fd4d6d5e587a55d110809; each
-- results sheet stacks five tables of 401 rows (site energy first, then source
-- energy, end uses, potable water, unmet hours), so the site table is rows
-- 1-401 of `results-summary_ex` and its own identity
-- (Net Site Energy = Electricity + Natural Gas) is what identifies it. Verified
-- spot check: cell B2 = 165.4 kWh/m², the CZ01 Assembly prototype (C2 =
-- 1044978.24 kWh, D2 = 470823.45 kWh electricity, E2 = 574154.8 kWh gas).
--
-- The SEED holds the `Ex` (existing-conditions) vintage: the base canvas and
-- the end state describe the existing stock, so its intensities are the
-- existing prototypes'. `New` is the code-compliant counterpart and is the
-- right vintage for a future-construction rate, which this model does not
-- distinguish.
--
-- Published units are whole-prototype kWh per year plus a site EUI in
-- kWh/m²/yr; no floor area is published. Area is recovered from the two
-- quantities that define it (area_m2 = net_site_energy_kwh / net_site_eui),
-- and each intensity is then electricity / area and (gas / 29.3071) / area,
-- 1 therm = 29.3071 kWh, 1 ft² = 0.092903 m². The workbook's own transform
-- script divides its gas column by 29.3 to get therms, so the therm here is
-- the source's unit, not this model's invention.
--
-- Zone keying: DEER prototypes are defined per *building* climate zone (CZ1-16,
-- the Title-24 zones), not per CEC forecasting (utility planning) zone, so this
-- seed is keyed on the zone core_end_state.assigns as title24_zone. DEER
-- publishes no per-forecasting-zone EUI, so fcz_zone — assigned on every parcel
-- for reference — keys no rate here.
--
-- Use-class mapping (one or more prototypes averaged per use class, because
-- our canvas carries one floor-area column per use where DEER has several
-- prototypes):
--   retail_services        RtS, RtL, Rt3, Gro                   (Retail small /
--                                                                 single-story large /
--                                                                 multistory large, Grocery)
--   restaurant             RFF, RSD                              (Restaurant fast-food, sit-down)
--   accommodation          Htl, Mtl                              (Lodging hotel, motel)
--   arts_entertainment     Asm, Rel                              (Assembly, Religious assembly)
--   other_services         Fin, Lib                              (Financial incl. banks, Libraries)
--   office_services        OfL, OfS                              (Office large, small)
--   public_admin           OfL                                   (no public-administration prototype:
--                                                                 public administration is office space)
--   education              EPr, ESe, ECC, EUn, ERC               (Primary, Secondary, Community College,
--                                                                 University, Relocatable Classroom)
--   medical_services       Hsp, Nrs                              (Hospital, Nursing home)
--   transport_warehousing  SCn, SUn                              (Storage conditioned, unconditioned)
--   wholesale              SCn, SUn, WRf                         (the two storage prototypes plus
--                                                                 Warehouse refrigerated, DEER's only
--                                                                 dedicated warehouse prototype)
-- MBT (Manufacturing biotech) and MLI (Manufacturing light industrial) are
-- unused: our canvas has no manufacturing floor-area column (manufacturing
-- appears only as an employment sector). The average is unweighted because the
-- mix within a parcel's use-class floor area is unknown; each use class's
-- intensities are the mean of its prototypes' intensities in that zone.
--
-- Regenerate by re-running the harvest against the URL above (the workbook's
-- sha256 is recorded with the provenance) and re-averaging with this mapping.
