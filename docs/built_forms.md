# BrewGIS Built Form Taxonomy

## Hierarchy

The UrbanFootprint framework classifies urban environments at three levels:

1. **Place Types (PT)** — neighborhood/district-level classifications describing the overall character and function of an area (e.g., Urban Residential, Village Mixed Use). A place type is defined by the **mix** of building types within it. No `pt__*` entries exist in the SACOG reference data used by BrewGIS.

2. **Building Types (BT)** — parcel-level classifications of individual structures (e.g., `bt__low_density_detached_residential`). These are what `parcel_bft_lightgbm` predicts. The `bt__` prefix indicates "Building Type" in the UrbanFootprint taxonomy.

3. **Components** — the fundamental element parameters (dwelling units per acre, floor-area ratio, household size, vacancy rate) that define each building type.

The `land_development_category` column (urban / compact / standard) serves as a coarser place-type proxy at the parcel level.

## ML-Predicted Building Types (28 classes)

The following 28 building types are predicted by the LightGBM classifier. These are feature-distinguishable by the 12 assessor feature columns.

### Residential — Detached

| Key | Label | Characteristics |
|-----|-------|-----------------|
| `bt__low_density_detached_residential` | Low-Density Detached Residential | Standard single-family homes, ~1 DU/parcel, lots 0.5–1.0 ac |
| `bt__medium_density_detached_residential` | Medium-Density Detached Residential | Smaller single-family lots, 0.12–0.25 ac |
| `bt__medium_high_density_detached_residential` | Medium-High Density Detached Residential | Compact single-family, lots 0.12–0.25 ac |
| `bt__very_low_density_detached_residential` | Very Low-Density Detached Residential | Large lots 1.0–5.0 ac |
| `bt__rural_residential` | Rural Residential | 5+ ac residential parcels |
| `bt__farm_home` | Farm Home | Residentially-used farm parcels |
| `bt__mobile_home_park` | Mobile Home Park | Multi-unit mobile home parks |

### Residential — Attached / Multi-Family

| Key | Label | Characteristics |
|-----|-------|-----------------|
| `bt__medium_density_attached_residential` | Medium-Density Attached Residential | Townhomes, duplexes, 2–4 units, low intersection density |
| `bt__medium_high_density_attached_residential` | Medium-High Density Attached Residential | Row houses, 3–6 units, moderate intersection density |
| `bt__high_density_attached_residential` | High-Density Attached Residential | Apartment buildings, 5+ units, avg DU 12+ |
| `bt__very_high_density_attached_residential` | Very High-Density Attached Residential | Large apartment complexes, 20+ units |
| `bt__urban_attached_residential` | Urban Attached Residential | Mid-rise residential, urban core, avg DU 32+ |
| `bt__urban_mid_rise_residential` | Urban Mid-Rise Residential | 5+ story residential towers, avg DU 59+ |
| `bt__blank_place_type` | Blank / Unclassified Place Type | Parcels with no dominant building type; place-type placeholder. May represent undeveloped land, transitional areas, or parcels whose built form is a mix of types. |

### Mixed Use

| Key | Label | Characteristics |
|-----|-------|-----------------|
| `bt__residentialretail_mixed_use_low` | Low-Intensity Mixed-Use Residential-Retail | Ground-floor retail + residential above, 2-4 stories |
| `bt__residentialretail_mixed_use_high` | High-Intensity Mixed-Use Residential-Retail | Ground-floor retail + mid-rise residential above |

### Commercial / Retail

| Key | Label | Characteristics |
|-----|-------|-----------------|
| `bt__communityneighborhood_retail` | Community/Neighborhood Retail | Strip malls, grocery-anchored centers |
| `bt__communityneighborhood_commercial` | Community/Neighborhood Commercial | Mixed commercial services |
| `bt__communityneighborhood_commercialoffice` | Community/Neighborhood Commercial-Office | Mixed commercial + office |
| `bt__regional_retail` | Regional Retail | Big-box stores, regional malls |
| `bt__moderate_intensity_office` | Moderate-Intensity Office | Suburban office parks, 2-4 stories |
| `bt__high_intensity_office` | High-Intensity Office | Office towers, 10+ stories |
| `bt__cbd_office` | CBD Office | Central business district high-rise office |
| `bt__hotel` | Hotel | Accommodation uses |
| `bt__light_industrialoffice` | Light Industrial-Office | Flex space, R&D, office-warehouse |

### Industrial

| Key | Label | Characteristics |
|-----|-------|-----------------|
| `bt__light_industrial` | Light Industrial | Warehouses, manufacturing, distribution |
| `bt__heavy_industrial` | Heavy Industrial | Large-scale industrial, processing |

### Agriculture

| Key | Label | Characteristics |
|-----|-------|-----------------|
| `bt__agriculture` | Agriculture | Cropland, pasture, orchards |
| `bt__agricultural_processingretail_employment` | Agricultural Processing/Retail | Farm-related commercial/industrial |

### Civic / Institutional

| Key | Label | Characteristics |
|-----|-------|-----------------|
| `bt__publicquasi_public` | Public/Quasi-Public | Government buildings, post offices, libraries |
| `bt__civic_institution` | Civic Institution | Community centers, museums |
| `bt__k_12_school` | K-12 School | Public and private schools |
| `bt__college_university` | College/University | Higher education campuses |
| `bt__medical_facility` | Medical Facility | Hospitals, clinics |
| `bt__park_and_open_space` | Park and Open Space | Parks, greenspace, recreation |
| `bt__airport` | Airport | Commercial and general aviation airports |
| `bt__parking_lot` | Parking Lot | Surface parking |
| `bt__parking_structure` | Parking Structure | Multi-level parking garages |

### Transportation / Other

| Key | Label | Characteristics |
|-----|-------|-----------------|
| `bt__road` | Road | Transportation ROW, road surfaces |
| `bt__water` | Water | Water bodies, reservoirs |

## 9-Class Mapping

The old 9-class system mapped to the 40-class system as follows:

| Old 9-Class | New BT Classes |
|---|---|
| `detsf_sl` | `bt__medium_density_detached_residential`, `bt__medium_high_density_detached_residential`, `bt__mobile_home_park` |
| `detsf_ll` | `bt__low_density_detached_residential`, `bt__very_low_density_detached_residential`, `bt__rural_residential`, `bt__farm_home` |
| `attsf` | `bt__medium_density_attached_residential`, `bt__medium_high_density_attached_residential` |
| `mf2to4` | `bt__medium_density_attached_residential`, `bt__medium_high_density_attached_residential` |
| `mf5p` | `bt__high_density_attached_residential`, `bt__very_high_density_attached_residential`, `bt__urban_attached_residential`, `bt__urban_mid_rise_residential` |
| `commercial` | `bt__communityneighborhood_retail`, `bt__regional_retail`, `bt__moderate_intensity_office`, `bt__high_intensity_office`, `bt__cbd_office`, `bt__hotel`, `bt__communityneighborhood_commercial`, `bt__communityneighborhood_commercialoffice`, `bt__light_industrialoffice` |
| `industrial` | `bt__light_industrial`, `bt__heavy_industrial`, `bt__agricultural_processingretail_employment` |
| `civic` | `bt__publicquasi_public`, `bt__civic_institution`, `bt__k_12_school`, `bt__college_university`, `bt__medical_facility`, `bt__park_and_open_space`, `bt__airport`, `bt__parking_lot`, `bt__parking_structure`, `bt__road`, `bt__water` |
| `agricultural` | `bt__agriculture`, `bt__farm_home` |

## Land-Use-Defined Building Types (not ML-predicted)

The following 12 building types are NOT predicted by the LightGBM model. They
are assigned by tier0/landuse rules using assessor use codes and Overture
building classifications, which identify them more reliably than parcel features:

| Key | Label | Assignment Method |
|-----|-------|-------------------|
| `bt__k_12_school` | K-12 School | Assessor land use code (school categories) |
| `bt__college_university` | College/University | Assessor land use code (college categories) |
| `bt__medical_facility` | Medical Facility | Overture building classification |
| `bt__airport` | Airport | Assessor land use code |
| `bt__park_and_open_space` | Park and Open Space | Assessor land use code |
| `bt__parking_lot` | Parking Lot | Assessor land use code + Overture |
| `bt__parking_structure` | Parking Structure | Overture building classification |
| `bt__road` | Road | Assessor land use code |
| `bt__water` | Water | Assessor land use code |
| `bt__publicquasi_public` | Public/Quasi-Public | Assessor land use code |
| `bt__civic_institution` | Civic Institution | Assessor land use code |
| `bt__agricultural_processingretail_employment` | Agricultural Processing | Assessor land use code |
