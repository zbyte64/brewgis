MODEL (
  name brewgis.seeds.residential_energy_baseline,
  kind SEED (
    path '../../seeds/residential_energy_baseline.csv'
  ),
  description 'Residential site energy per dwelling unit per CEC Building Climate Zone and housing class, from the CalBEM California prototype results.',
  column_descriptions (
    zone = 'CEC Title-24 Building Climate Zone (1-16) the intensities apply to, matching core_end_state.title24_zone.',
    du_type = 'Housing class of core_end_state.du_type the rate applies to (detsf_ll, detsf_sl, attsf, mf).',
    elec_kwh_per_du_yr = 'Annual site electricity per dwelling unit (kWh per dwelling unit per year).',
    gas_therm_per_du_yr = 'Annual site natural gas per dwelling unit (therms per dwelling unit per year).'
  ),
  columns (
    zone INTEGER,
    du_type TEXT,
    elec_kwh_per_du_yr DOUBLE PRECISION,
    gas_therm_per_du_yr DOUBLE PRECISION
  )
);

-- Residential energy baseline — kWh and therms per dwelling unit per year, per
-- CEC Building Climate Zone, by housing class.
--
-- energy_demand.sql applies these where the parcel has a climate zone (every
-- California parcel does) and falls back to the built form's flat EUI
-- (electricity_eui / gas_eui) where it does not.
--
-- Source: CalBEM "California Prototypes Development Project" (Southern
-- California Edison Codes & Standards Program; Technical Advisory Group
-- includes the CEC and CPUC), prototype specification workbooks, worksheet
-- `Prototype Results`, data rows 3-18 = CA Building CZ 1..16 (posted
-- 2025-05-20):
--   .../NOR-Codes-Stds/CalBEM-Prototypes/main/Specifications/Single-Family/NORESCO_Prototypes_SingleFamily_Characteristics_20May2025.xlsx
--   .../NOR-Codes-Stds/CalBEM-Prototypes/main/Specifications/Low-Rise-Multifamily/NORESCO_Prototypes_LRMF_Characteristics_20May2025.xlsx
-- Published columns used: `Total Electricity` (kWh/yr) and `Total Gas`
-- (therms/yr), both absolute annual SITE energy for the prototype building.
-- Sheet row map: header row 1, units row 2, data rows 3-18 = CA Building CZ
-- 1..16. Verified spot check: SingleFamily CZ1 = 7111.649 kWh and 1010.132
-- therms (columns C and D of row 3), whose published per-square-foot columns
-- (3.966 kWh/sf, 0.56 therms/sf) imply the ~1,794 sq ft prototype.
--
-- `Total Electricity` is per dwelling unit as published: each single-family
-- prototype is one dwelling unit. `LowRiseMultifamily` is published per
-- *building*, and no unit count accompanies the results, so the per-unit value
-- is the building total divided by the building's units under the same
-- stock-weighting its area already carries:
--
--   unit_size_sqft = 1061.1818  = (7320 + 39372) / (8 + 36)
--
-- the area-weighted mean unit size of the workbook's two low-rise multifamily
-- prototypes (Garden, 7,320 sq ft / 8 units; Loaded Corridor, 39,372 sq ft / 36
-- units). units = (total_kwh / published kWh-per-sqft) / unit_size_sqft, and
-- both fuels are divided by that units count. The published per-sqft intensity
-- of a zone therefore carries through unchanged: CZ1 multifamily stays at its
-- published 4.694 kWh/sq ft.
--
-- Housing classes without a prototype of their own reuse the single-family
-- values, as the CEC prototype set ships no small-lot detached, attached
-- single-family or mobile-home prototype: detsf_ll, detsf_sl and attsf all
-- carry the single-family result. That overstates attsf slightly (less
-- envelope per unit than a detached house) and cannot be corrected from this
-- source.
--
-- Vintage caveat, shared with commercial_energy_baseline: these are the
-- *current Code* (2022-aligned) California prototypes, not an existing-stock
-- vintage. No CEC/CPUC residential prototype table keyed on the climate zones
-- publishes existing-vintage values (the DEER database's residential
-- prototypes are not published per zone; its only public per-zone sample is an
-- incidental existing-vintage measure baseline for two building types). The
-- residential demand this seed produces is therefore a code-prototype
-- estimate, i.e. a floor for existing stock, where the commercial seed's
-- DEER `Ex` vintage describes existing stock. Stated rather than papered over.
--
-- Regenerate by re-reading the two workbooks' `Prototype Results` sheets and
-- re-applying the unit-size step above.
