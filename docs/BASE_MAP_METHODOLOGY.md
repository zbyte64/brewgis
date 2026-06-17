# Base Map Methodology — Specification

## 1. Overview

This spec defines how the base canvas is constructed: a parcel-level dataset containing population, households, dwelling units, and employment by sector, allocated from coarser source zones using assessor data, building footprints, and land-use classification.

Two parallel allocation strategies operate:

- **Residential** — DU-weighted allocation. Population is allocated proportional to estimated dwelling units per parcel. DUs are derived from assessor data or inferred from built_form_key + parcel area.
- **Employment** — sector-constrained allocation. Each employment subsector allocates proportional to the relevant building sqft type (commercial, industrial, other) on each parcel.

The central classifier that drives both paths is `built_form_key` (development subtype), derived from assessor data as the primary signal and Overture building data as the secondary signal.

---

## 2. Data Flow

```
                         DATA FLOW

 SOURCES         CLASSIFICATION            ALLOCATION              OUTPUT

 ┌──────────┐   ┌────────────────────┐   ┌────────────────┐   ┌──────────────┐
 │ACS Block │   │  Assessor          │   │ DU-Weighted    │   │ Base Canvas  │
 │Group     │   │  Use Code          │   │ Allocation     │   │              │
 │(pop,du,  │   │                    │   │ (DUs × hh_size) │   │ • pop        │
 │ hh,      │   │  ┌──────────────┐  │   │                │   │ • hh         │
 │ income,  │   │  │built_form_key│  │   │ ACS/Census     │   │ • du         │
 │ etc)─────┼───┼──►(development  │  │   │ Block → Parcel │   │ • du_subtype │
 └──────────┘   │  │ subtype)     │  │   └────────────────┘   │ • emp_*      │
                │  └──────────────┘  │                        │ • sqft_*     │
 ┌──────────┐   │        │           │   ┌────────────────┐   │ • bft_key    │
 │Census    │   │        ▼           │   │ Sector-        │   └──────────────┘
 │2020 Block│   │  ┌──────────────┐  │   │ Constrained    │
 │(pop)─────┼───┼──►Overture      │  │   │ Employment     │
 └──────────┘   │  │Building Sqft │  │   │                │
                │  │by Type       ├──┼──►│ WAC Block →    │
 ┌──────────┐   │  │(res, com,    │  │   │ Parcel         │
 │LEHD WAC  │   │  │ ind, other)  │  │   └────────────────┘
 │Blocks    │   │  └──────────────┘  │
 │(emp_*)───┼───┼─────────┘          │
 └──────────┘   │                    │
                │  ┌──────────────┐  │
 ┌──────────┐   │  │Land Dev      │  │
 │Overture  │   │  │Category      │  │
 │Buildings │───┼──►(5-way:       │  │
 │(footprint│   │  │ urban, mixed,│  │
 │class,    │   │  │ industrial,  │  │
 │height,   │   │  │ ag, undevel) │  │
 │levels)   │   │  └──────────────┘  │
 └──────────┘   └────────────────────┘
```

---

## 3. built_form_key Derivation

The first step for every parcel is to determine its development subtype. Only ~15% of parcels have assessor data with property type and lot size. The remaining 85% are classified through a cascade of inference tiers, each using a different signal.

### Tier 1: Direct Assessor Data (~15% coverage)

For the minority of parcels with assessor sales records containing property type:

```
 SFR + lot < 0.15 ac   → detsf_sl   (single-family small lot)
 SFR + lot ≥ 0.15 ac   → detsf_ll   (single-family large lot)
 Condo / Townhouse     → attsf      (attached single-family)
 MF + 2-4 units        → mf2to4     (duplex, triplex, fourplex)
 MF + 5+ units         → mf5p       (apartment)
 Commercial use code   → commercial
 Industrial use code   → industrial
 Agricultural use code → agricultural
 Civic/institutional   → civic
```

### Tier 2: Overture Building Footprint Class (variable coverage)

For parcels with building footprints but no assessor subtype:

```
 building_class = 'residential' + levels < 3  → detsf
 building_class = 'residential' + levels ≥ 3  → mf5p
 building_class = 'commercial'                → commercial
 building_class = 'industrial'                → industrial
 building_class = 'civic'                     → civic
```

Coarse — separates residential from non-residential, and low-rise from high-rise. Cannot distinguish `detsf_sl` from `detsf_ll`, or `mf2to4` from `mf5p`. This is refined by Tier 3.

### Tier 3: Spatial Inference from Nearby Assessor Parcels

For the remaining parcels without direct assessor data or a distinguishing building class, we use the **15% of parcels with known built_form_key as a training set**, propagating their subtype to nearby parcels using feature similarity. Three inputs:

1. **Intersection density** — a continuous proxy for urban form. Derived from Overture transport road segments. Higher values mean denser street grids, which correlate with denser development. Lower values mean sparse roads, which correlate with large-lot or rural use.

2. **Lot size / parcel area** — available for every parcel from the parcel geometry itself. Constrains the density band (larger parcels cannot be high-density residential).

3. **Proximity to known parcels** — the assumption that development patterns cluster. A parcel surrounded by `detsf_sl` parcels is likely also `detsf_sl`, unless its intersection density or lot size contradicts that.

#### Inference procedure

```
                     TIER 3: SPATIAL INFERENCE

  For each unclassified parcel U:

  1. Find known parcels K within the same block group
     (or tract, or county — three-tier spatial partition,
      identical to parcel_footprint_imputed.sql)
      that share the same land_development_category.

  2. Compute feature distance between U and each K:

     distance = SQRT(
         ((intersection_density_U - int_dens_K)
             / σ(int_dens)_in_partition)^2
         + ((lot_size_U - lot_size_K)
             / σ(lot_size)_in_partition)^2
         + ((footprint_ratio_U - footprint_ratio_K)
             / σ(footprint_ratio)_in_partition)^2
     )

  3. Take the k=5 nearest neighbors.
     built_form_key = MODE(neighbor built_form_keys)

  4. Validate: if the inferred subtype contradicts the
     intersection density band (e.g., int_dens = 22
     suggests urban, but nearest neighbor is agricultural),
     reject and escalate to Tier 4.
```

The three-tier spatial partition (block group → tract → county-wide within 5km), z-score normalization, and k=5 neighbor count mirror the existing `parcel_footprint_imputed.sql` implementation. The only new feature vector is intersection density, which is already computed per parcel.

#### Why intersection density refines the inference

Intersection density correlates with development intensity in a way that lot size alone does not:

```
 Intersection Density    Typical built_form_key       Est. Density
 ──────────────────────────────────────────────────────────────────
 >20 (urban grid)        mf5p, commercial, mixed-use   30+ du/ac
 10-20 (suburban grid)   detsf_sl, attsf, mf2to4       8-30 du/ac
 5-10 (suburban sparse)  detsf_ll                      4-8 du/ac
 1-5 (exurban)           detsf_ll, agricultural        0-4 du/ac
 <1 (rural)              agricultural, undeveloped      0 du/ac
```

A parcel with `lot_size = 0.3 ac` could be either `detsf_sl` (small-lot suburban) or `detsf_ll` (large-lot infill). The intersection density disambiguates: if the surrounding street network is a grid (int_dens > 15), it is likely `detsf_sl`. If it is a cul-de-sac subdivision (int_dens < 10), it is likely `detsf_ll`.

#### Empirical validation from SACOG data

The feature vectors for Tier 3 inference were validated against SACOG assessor records (55,079 parcels) joined with OSM intersection density (jurisdiction-level, the only resolution available at analysis time) and Overture building footprints. Key findings:

**Residential: Within the same intersection density jurisdiction, lot size separates built form types clearly for some pairs, but not all:**

```
Int Dens  Type      N     P50 Lot    Avg Living  Avg Units  Separable?
        (juris avg)       (sqft)      (sqft)
──────────────────────────────────────────────────────────────────────────
21 (low)  SFR      13,441  6,970     1,813       1.00       ──
          MF         584  9,158     2,235      13.93       No (lot overlap)
          Com/Ind    382 28,505     1,357       0.00       Yes (3-5× lot)
          Condo      882      0     1,008       0.93       Yes (lot ~0)

148 (high) SFR    10,188  5,663     1,649       1.00       ──
          MF         698  6,534     2,239       9.43       No (lot overlap)
          Com/Ind    485 16,337     1,664       0.00       Yes (3× lot)
          Condo      579      0     1,152       1.15       Yes (lot ~0)

181 (high) SFR     1,898  6,970     1,522       1.00       ──
          MF          79  8,712     2,168       5.62       No (lot overlap)
          Com/Ind     35 21,344     1,815       0.00       Yes (3× lot)
          Condo       97  1,842       961       0.94       Yes (lot ~0)
```

What this means for the feature vectors:

- **Lot_size** is the primary discriminator for Com/Ind (3-5× larger than residential) and Condo (near-zero). No other feature is needed for these.
- **Lot_size alone cannot distinguish SFR from MF** within the same density band — their lot size distributions overlap. This is why `footprint_ratio` is essential: MF has more building sqft on the same lot (higher FAR), producing a distinguishable footprint_ratio.
- **Intersection density** (even jurisdiction-level) captures a cross-jurisdiction gradient: SFR p50 lot shrinks from 6,970 sqft at low density to 5,663 sqft at high density (~20% decrease). This gradient provides signal for parcels at the boundary between two jurisdictions.

**SFR dwelling unit count is always 1:** Across 46,772 SFR records, every single one has exactly 1 dwelling unit. The `units` column (housing units) is distinct from `bedrooms` (avg 3.42 for SFR). A 4-bedroom house has 1 dwelling unit.

**Non-residential: lot size, building coverage, and building height separate the coarse subtypes clearly:**

```
                    P50      P25-P75    Avg      Avg      P50       Avg
Type        N       Lot      Lot        Footpr   Bldg     Coverage  Levels
                    (sqft)   (sqft)     (sqft)   Cnt      Ratio
───────────────────────────────────────────────────────────────────────────────
Com/Ind   1,182    25,680   10,920-    19,544   1.5      0.337     2.9
                            58,697
Vacant    3,077     6,098    4,500-       530   0.1      0.000     1.0
                             9,148
Other       458    27,917    4,583-     6,096   1.0      0.000     1.5
                           423,512
```

Heuristics derived:

| Condition | Classification | Rationale |
|---|---|---|
| Lot < 10,000 sqft, building_count = 0 | Vacant | Small vacant lots (92% have no buildings) |
| Lot 10k-100k sqft, building_count ≥ 1, coverage_ratio > 0.2 | Com/Ind | Built-up commercial or industrial; coverage ratio separates from Other |
| Lot 10k-100k sqft, coverage_ratio < 0.1 | Other (parking, roads, vacant-commercial) | Low building presence on commercial-scale lot |
| Lot > 1M sqft, coverage_ratio < 0.01 | Agricultural / Heavy Other | Massive lots, essentially no buildings |
| Levels ≥ 3 | Commercial subtype of Com/Ind | Commercial avg 3.9 levels; Industrial avg 1.6 levels (B-prefix codes) |
| Levels ≤ 2 | Industrial subtype of Com/Ind | Industrial is predominantly single-story |

Coverage ratio (`total_footprint_sqft / lot_size_sqft`) is the single strongest discriminator among non-residential types. Vacant and Other have nearly zero coverage; Com/Ind has 0.34 median ratio (higher when multi-story: ratio > 1 means multistory buildings).

The Overture building `class` field (commercial, industrial, civic) provides a direct cross-check for parcels with building overlap (92% of Com/Ind parcels have Overture data).

**Intersection density computation from Overture transport:** Road segments from Overture transport are already loaded in PostGIS (190k driveable segments for Sacramento County, with class and surface attributes). To compute parcel-level intersection density:

  1. Extract segment endpoints from the driveable road network (classes: motorway, primary, secondary, tertiary, residential, service).
  2. Snap endpoints within 10m tolerance and group by location. Count segments meeting at each node.
  3. Filter to nodes with street_count ≥ 3 (these are intersections).
  4. Define a hex grid over the region (~1/4 sq mi cells). Count intersections per cell.
  5. Density = intersection_count / cell_area_sq_mi.
  6. Join to parcels by cell overlap.

This produces a continuous density surface that varies across the county (not 8 discrete values), giving enough variance to distinguish a downtown grid (high density) from a suburban cul-de-sac subdivision (low density) even within the same jurisdiction.

### Tier 3 coverage

With the 15% assessor parcels distributed across block groups and land-use categories, the k-NN spatial inference covers the majority of remaining parcels within the same block group. A parcel in a residential subdivision where even a few neighbors have assessor data will inherit the correct subtype. The three-tier partition ensures most parcels find at least Tier 2 or 3 matches before reaching the area heuristic.

### Tier 4: Area-Based Heuristic (final fallback)

For parcels that reach no match in any spatial tier (isolated parcels with no nearby assessor data and no building footprints):

```
 area > 3.0 ac     → industrial or civic
 area > 1.5 ac     → commercial, office, or detsf_ll
 area > 0.4 ac     → detsf_ll
 area > 0.15 ac    → detsf_sl
 area ≤ 0.15 ac    → mf2to4 or mf5p (townhouse to apartment)

 Within each area band, diversity (parcel_id % N)
 distributes across plausible subtypes to avoid
 uniform assignment of the entire band.
```

This tier fires only for parcels with no assessor data, no building footprint, and no spatially-nearby known parcels — the long tail of rural or recently subdivided land.

### Subtype hierarchy

```
built_form_key (residential)
├── detsf_sl     — single-family detached, small lot (<0.15 ac)
├── detsf_ll     — single-family detached, large lot (≥0.15 ac)
├── attsf        — attached single-family (condo, townhouse)
├── mf2to4       — multifamily 2-4 units (duplex, triplex, fourplex)
├── mf5p         — multifamily 5+ units (apartment, condo building)
│   ├── courtyard apartment
│   ├── stacked flats
│   ├── mid-rise apartment
│   └── high-rise apartment
│   (refined by Overture building levels)
│
built_form_key (non-residential)
├── commercial
│   ├── neighborhood retail
│   ├── general commercial
│   ├── office low rise
│   └── office mid/high rise
├── industrial
│   └── light industrial
├── civic / institutional
├── agricultural
├── mixed_use
└── undeveloped
```

The resolution of the hierarchy varies by parcel. Those with rich assessor data can distinguish all 5 residential subtypes. Those classified purely by area heuristic use coarser bins.

---

## 4. Building Sqft by Type via Overture

Each parcel's building square footage is computed from Overture building footprints intersected with the parcel, aggregated by building class.

This produces four per-parcel values that drive both residential and employment allocation:

```
              OVERTURE BUILDING SQFT BREAKDOWN

 For each parcel:

 1. Intersect Overture building footprints with parcel geometry
 2. For each intersecting building:
    building_sqft = footprint_area × COALESCE(levels, 1)
    Accumulate into bucket by building class:

    class = 'residential'  → residential_building_sqft
    class = 'commercial'   → commercial_building_sqft
    class = 'industrial'   → industrial_building_sqft
    class = 'civic'        → other_building_sqft
    class = 'agricultural' → other_building_sqft
    class = 'transport'    → other_building_sqft
    class = 'mixed'        → infer by levels:
                             If levels > 1: ground floor = commercial,
                               upper floors = residential
                               comm_sqft = bldg_sqft / levels
                               res_sqft  = bldg_sqft - comm_sqft
                             If levels = 1 or NULL: split by assessor
                               use code ratio, or 50/50 if no data

    Parcels with built_form_key = 'mixed_use' get additional
    processing after the per-building accumulation:
      total_commercial_sqft += comm_sqft_from_levels
      total_residential_sqft += res_sqft_from_levels
      Where no building overlap exists but the parcel is
      classified mixed_use, commercial_sqft and
      residential_sqft both fall back to assessor data
      or 50/50 split of total estimated building sqft.

 3. For parcels with zero building overlap, fall back to:
    ─ assessor sales sqft (actual_building_sqft)
    ─ estimated sqft from lot_size × impervious_fraction
    ─ lot_size (last resort)

 Result per parcel:
   residential_building_sqft   → DU estimation (units from assessor)
                               → pop weight (DUs × household_size)
   commercial_building_sqft    → retail/office employment allocation
   industrial_building_sqft    → industrial employment allocation
   other_building_sqft         → civic/ag/military employment
```

---

## 5. Dwelling Unit Estimation (Pipeline Step)

Dwelling units are the central weight for population allocation, but most parcels do not have directly observed unit counts. The assessor data covers ~15% of parcels. For the remaining 85%, DU is estimated through a cascade that uses built_form_key to determine the subtype, then Overture building footprints to estimate the count where needed.

### Prerequisites

This step runs after:
  1. built_form_key derivation (Section 3) — every parcel has a subtype
  2. Overture building sqft breakdown (Section 4) — every parcel has residential_building_sqft
  3. region_avg_sqft_per_unit calibration (computed from known assessor MF parcels in the region)

### The cascade

```
                    DU ESTIMATION CASCADE

  For each parcel:

                 ┌────────────────────────────┐
                 │  Assessor has units > 0?   │
                 └──────────┬─────────────────┘
                            │
                      ┌─────┴──────┐
                      │ YES        │ NO
                      ▼            ▼
              ┌──────────────┐  ┌────────────────────────────┐
              │ du =         │  │  built_form_key is known?  │
              │ assessor.    │  └──────────┬─────────────────┘
              │ units        │             │
              └──────────────┘        ┌────┴──────┐
                                      │ YES       │ NO
                                      ▼           ▼
                              ┌────────────────┐  │
                              │  Subtype?      │  │
                              └───┬────────────┘  │
                                  │               │
                    ┌─────────────┼─────────┐     │
                    ▼             ▼         ▼     │
              ┌──────────┐  ┌──────────┐  ┌──────┴─────┐
              │ SFR type │  │ MF type  │  │ Unknown    │
              │ (detsf_sl,│  │ (mf2to4, │  │ residential│
              │ detsf_ll,│  │ mf5p)    │  │ → du = 1   │
              │ attsf)   │  │          │  └────────────┘
              │ → du = 1 │  │ Estimate │
              └──────────┘  │ from     │
                            │ building │
                            │ sqft     │
                            └────┬─────┘
                                 │
                    ┌────────────┴────────────┐
                    │ residential_building_    │
                    │ sqft > 0?               │
                    └───┬─────────────────────┘
                   ┌────┴──────┐
                   │ YES       │ NO
                   ▼           ▼
           ┌──────────────┐  ┌────────────────────┐
           │ du = ROUND(  │  │  land_dev_category │
           │  res_bldg_   │  │  IN ('urban',      │
           │  sqft /      │  │  'mixed_use')?     │
           │  region_avg_ │  └───┬────────────────┘
           │  sqft_per_   │ ┌────┴──────┐
           │  unit)       │ │ YES       │ NO
           │ clamped to   │ ▼           ▼
           │ [min, ∞)     │ ┌────────┐  ┌────────┐
           └──────────────┘ │ du = 1 │  │ du = 0 │
                            └────────┘  └────────┘
```

### Tier details

```
 du_on_parcel = CASE

     ── Tier 1: Direct assessor observation (covers ~15% of parcels)
     WHEN assessor.units IS NOT NULL AND assessor.units > 0
         THEN assessor.units
         -- This is the ground truth. No estimation needed.

     ── Tier 2: Implied from built_form_key (SFR subtypes)
     WHEN built_form_key IN (detsf_sl, detsf_ll, attsf)
         THEN 1
         -- SACOG validation: 46,772 SFR records, avg units = 1.00, zero exceptions.
         -- Condo avg units = 1.07 but individual parcel is always 1.
         -- No building sqft needed. Single-family always has one dwelling unit.

     ── Tier 3: Implied from built_form_key (MF subtypes) + Overture building sqft
     WHEN built_form_key IN (mf2to4, mf5p)
       AND COALESCE(residential_building_sqft, 0) > 0
         THEN CASE
             WHEN built_form_key = mf2to4
                 THEN GREATEST(2,
                      ROUND(residential_building_sqft / region_avg_overture_sqft_per_unit, 0)::int)
             WHEN built_form_key = mf5p
                 THEN GREATEST(5,
                      ROUND(residential_building_sqft / region_avg_overture_sqft_per_unit, 0)::int)
         END
         -- Both numerator and denominator use Overture gross sqft.
         -- residential_building_sqft from Overture (footprint × levels).
         -- region_avg_overture_sqft_per_unit from the k=20 nearest
         -- overlapping parcels (assessor units + Overture res_sqft) in
         -- intersection density space. No assessor living_area involved.
         -- The GREATEST clamp ensures minimum DUs match the subtype definition.

     ── Tier 4: MF subtype without building sqft data
     WHEN built_form_key IN (mf2to4, mf5p)
         THEN CASE
             WHEN built_form_key = mf2to4 THEN 2
             WHEN built_form_key = mf5p THEN 5
         END
         -- Conservative floor. No Overture building overlap for this parcel.
         -- The subtype definition minimum is the best estimate available.

     ── Tier 5: Residential without assessor data, subtype, or building overlap
     WHEN land_development_category IN ('urban', 'mixed_use')
         THEN 1
         -- Last resort: no assessor units, no built_form_key refinement,
         -- and no Overture building overlap to estimate from.
         -- Conservative default of 1 DU is better than over-allocation.
         -- Mixed-use parcels that DO have Overture building overlap will
         -- have their residential_sqft computed via the levels-based split
         -- in Section 4, then enter Tier 3 for DU estimation — they never
         -- reach this tier.

     ── Tier 6: Non-residential
     WHEN built_form_key IN (commercial, industrial, civic, agricultural)
       OR land_development_category IN ('industrial', 'agricultural', 'undeveloped')
         THEN 0

     ELSE 0
 END
```

### region_avg_overture_sqft_per_unit calibration

Both the numerator (`residential_building_sqft`) and the denominator in the DU formula must use the same sqft definition. Overture's `footprint_area × levels` measures gross building envelope (includes walls, halls, common areas). Assessor `living_area` measures unit interiors only. Using one for the numerator and the other for the denominator would systematically overcount DUs (~33% for MF).

Therefore, the denominator is computed from **Overture sqft as well**, using parcels that have BOTH Overture building overlap AND assessor unit counts:

```
 region_avg_overture_sqft_per_unit = Σ(Overture_residential_building_sqft)
                                     / Σ(assessor_units)
                                     for parcels where:
                                       residential_building_sqft > 0
                                       AND assessor.units > 0
                                       AND (property_type = 'Multiple Family Residence'
                                            OR units >= 2)

 Partition levels (finest first):

   1. k-NN in int_dens space (k=20, same subtype)
      — Uses overlapping parcels (Overture + assessor units)
        closest in intersection density to the target parcel.
        Ratio of sums.

   2. County-wide subtype avg (fallback)
      — Uses ALL overlapping parcels of the same subtype.

 Computation is separate per subtype:
   mf2to4: units BETWEEN 2 AND 4
   mf5p:   units >= 5
```

From the SACOG region (informative):

| Subtype | Overlapping parcels | Avg Overture sqft/unit | Std | R² vs units |
|---|---|---|---|---|
| **mf2to4** | **150** | **1,259** (p50: 1,198) | 669 | — |
| **mf5p** | **34** | **393** (p50: 316) | 255 | **0.94** |

For mf5p, Overture sqft predicts unit count with R² = 0.94 — highly reliable. The assessor living_area approach (R² ≈ 0.07 for mf5p) was only weak because so few MF 5+ parcels have living_area data (23 of 323). Overture fills this gap: 34 MF 5+ parcels have both Overture sqft and unit counts, with near-perfect correlation.

The ratio between the two subtypes (~3.2×) is structural — larger buildings build smaller units. Compute separately, do not borrow across subtypes.

### Output

Every parcel now has `du` estimated. This is the sole weight for population allocation. No parcel area or intersection area enters the weight formula.

### Households and vacancy

Households are derived from DUs using the vacancy rate:

```
 vacancy_rate = CASE
     WHEN assessor vacancy data IS NOT NULL  → assessor rate
     WHEN built_form_key = detsf_sl          → 2.5%   (stable SFR)
     WHEN built_form_key = detsf_ll          → 2.5%
     WHEN built_form_key = attsf             → 5.0%   (condos higher)
     WHEN built_form_key = mf2to4            → 5.0%
     WHEN built_form_key = mf5p              → 8.0%   (apartments highest)
     ELSE                                     → 5.0%   (regional default)
 END

 hh_on_parcel = du_on_parcel × (1 - vacancy_rate)
 pop_on_parcel = hh_on_parcel × household_size
```

### DU subtype breakdown

The DU subtype breakdown follows from built_form_key directly — no need for a separate post-allocation split:

```
 built_form_key  →  du_detsf_sl  du_detsf_ll  du_attsf  du_mf2to4  du_mf5p
 ────────────────────────────────────────────────────────────────────────────
 detsf_sl        →        du           0          0          0         0
 detsf_ll        →         0          du          0          0         0
 attsf           →         0           0         du          0         0
 mf2to4          →         0           0          0         du         0
 mf5p            →         0           0          0          0        du
 NULL (unknown)  →  county-averaged proportions
```

A parcel classified as `detsf_ll` by assessor data gets zero `mf5p` DU, even though ACS might imply a multifamily share. The subtype is grounded in observation, not allocation.

---

## 7. Employment Allocation — Sector-Constrained

Each employment subsector allocates independently, weighted by the relevant building sqft type on each parcel:

```
              SECTOR-CONSTRAINED EMPLOYMENT ALLOCATION

  For each employment sector S and each parcel P in a WAC block:

  1. Determine which building sqft type applies to sector S:

     Sector                          → Uses building sqft
     ─────────────────────────────────────────────────
     emp_retail_services               commercial_building_sqft
     emp_restaurant                    commercial_building_sqft
     emp_accommodation                 commercial_building_sqft
     emp_arts_entertainment            commercial_building_sqft
     emp_other_services                commercial_building_sqft
     emp_office_services               commercial_building_sqft
     emp_medical_services              commercial_building_sqft

     emp_public_admin                  other_building_sqft
     emp_education                     other_building_sqft
     emp_agriculture                   other_building_sqft
     emp_extraction                    other_building_sqft
     emp_military                      other_building_sqft

     emp_manufacturing                 industrial_building_sqft
     emp_wholesale                     industrial_building_sqft
     emp_transport_warehousing         industrial_building_sqft
     emp_utilities                     industrial_building_sqft
     emp_construction                  industrial_building_sqft

  2. Allocate:

     emp_S_on_P = WAC_block_S
                × (relevant_building_sqft_on_P
                   / Σ relevant_building_sqft_in_block)

     Parcels with zero relevant_building_sqft get zero
     allocation for sector S. No separate land-use exclusion
     mask needed — the sqft filter naturally excludes
     ineligible parcels.
```

### Mixed-use parcels

A parcel with both commercial and industrial buildings gets both employment types, each proportional to the relevant sqft. No single `built_form_key` needs to represent multiple uses — the sqft breakdown per parcel handles it directly.

### Parcels with no building data

For parcels in the WAC block with no Overture building overlap, employment is allocated using:

1. Assessor building sqft (sales data) — if available
2. Estimated building sqft (lot_size × impervious_fraction) — fallback
3. Parcel area under the land_development_category — last resort, only for non-undeveloped categories

---

## 8. Full Pipeline

```
                           PIPELINE

 ┌────────────────────────────────────────────────────────────────┐
 │  STAGING                                                       │
 │                                                                │
 │  assessor_parcels         overture_buildings                   │
 │  (use codes, sqft, lots)  (footprints, class, height, levels)  │
 │                                                                │
 │  wac_block (LEHD LODES)   acs_block_group (ACS)               │
 │  nlcd (impervious)        census_2020_block                    │
 └────────────────────────────────────────────────────────────────┘
         │                        │
         ▼                        ▼
 ┌────────────────────────────────────────────────────────────────┐
 │  CLASSIFICATION & WEIGHTS                                     │
 │                                                                │
 │  parcel_dasymetric_weights                                     │
 │    · built_form_key (from assessor → overture → heuristic)     │
 │    · du_subtype                                                │
 │    · residential/commercial/industrial/other_building_sqft     │
 │      (from Overture class breakdown)                           │
 │    · land_development_category (5-way)                         │
 └────────────────────────────────────────────────────────────────┘
         │
         ▼
 ┌────────────────────────────────────────────────────────────────┐
 │  DWELLING UNIT ESTIMATION                                     │
 │                                                                │
 │  For each parcel, in priority order:                          │
 │    Tier 1: assessor.units (direct, ~15% of parcels)            │
 │    Tier 2: built_form_key = SFR type → du = 1                 │
 │    Tier 3: built_form_key = MF type                           │
 │            + residential_building_sqft                         │
 │            → du = res_bldg_sqft / region_avg_sqft_per_unit    │
 │    Tier 4: built_form_key = MF type (no bldg data) → min      │
 │    Tier 5: urban/mixed_use default → du = 1                   │
 │    Tier 6: non-residential → du = 0                            │
 │                                                                │
 │  Output: du_on_parcel, pop_dasym_weight (DU × hh_size)         │
 └────────────────────────────────────────────────────────────────┘
         │
         ▼
 ┌────────────────────────────────────────────────────────────────┐
 │  GEOMETRY & AREA                                              │
 │                                                                │
 │  base_canvas_geometry                                           │
 │    · parcel geometry, area_gross, area_parcel                  │
 │    · built_form_key, intersection_density                      │
 │    · du_subtype, building sqft columns                         │
 └────────────────────────────────────────────────────────────────┘
         │
         ├─────────────────────────────────┐
         ▼                                 ▼
 ┌────────────────────────┐   ┌────────────────────────────────────┐
 │  DEMOGRAPHICS           │   │  EMPLOYMENT                       │
 │                         │   │                                    │
 │  ACS/Census Block →     │   │  WAC Block → Parcel               │
 │  Parcel                 │   │                                    │
 │                         │   │  Per sector:                      │
 │  pop_dasym_weight       │   │    weight = relevant_sqft_on      │
 │  (DU × household_size)  │   │             parcel / total in      │
 │                         │   │             block                  │
 │  pop, hh, du            │   │                                    │
 │  du subtype breakdown   │   │  emp_retail_services: commercial   │
 │  demographic averages   │   │  emp_manufacturing: industrial     │
 │  (income, education,    │   │  emp_education: other              │
 │   rent burden, etc)     │   │  ...                               │
 └────────────────────────┘   └────────────────────────────────────┘
         │                                 │
         └────────────────┬────────────────┘
                          ▼
 ┌────────────────────────────────────────────────────────────────┐
 │  ATTRIBUTES (Post-Allocation)                                  │
 │                                                                │
 │  base_canvas_attributes                                        │
 │    · DU subtype breakdown (from du_subtype)                    │
 │    · Building area by subtype (sqft × subtype ratios)           │
 │    · Area by use (residential, employment, mixed, no_use)      │
 │    · Irrigation (residential/commercial irrigated area)         │
 │    · Intersection density (from Overture transport or          │
 │      calibration defaults)                                    │
 └────────────────────────────────────────────────────────────────┘
         │
         ▼
 ┌────────────────────────────────────────────────────────────────┐
 │  RECONCILIATION                                                │
 │                                                                │
 │  base_canvas_reconciled                                        │
 │    · DU subtype sum scaled to match total DU                   │
 │    · NULL imputation from county means                         │
 │    · Final output: pop, hh, du, du_subtypes,                   │
 │      emp by 15+ sectors, building sqft by subtype,             │
 │      area by use, irrigated area                               │
 └────────────────────────────────────────────────────────────────┘
         │
         ▼
 ┌────────────────────────────────────────────────────────────────┐
 │  BASE CANVAS                                                   │
 │                                                                │
 │  ~500k parcels, each with:                                     │
 │    · pop, hh, du, du_subtype breakdown                         │
 │    · emp by 15+ subsectors                                     │
 │    · built_form_key, land_development_category                  │
 │    · building sqft by type                                     │
 │    · area by use, irrigated area                               │
 │    · demographic averages (income, education, rent burden)     │
 └────────────────────────────────────────────────────────────────┘
```

---

## 9. Source Zone Strategy

Population allocation uses **Census 2020 blocks** as the source zone. Demographics (income, education, etc.) use **ACS 5-year block groups** because those variables aren't available at the block level.

### Census 2020 block (P.L. 94-171 redistricting data)

| Property | Value |
|---|---|
| Source | Decennial Census, 100% count (every resident, not a sample) |
| Resolution | ~200 acres, ~75 people (CA average) |
| Variables | Total population, race/ethnicity (voting-age and total), housing units, group quarters population |
| Frequency | Every 10 years (2020 is the current vintage) |
| Coverage | Every parcel in the US falls in exactly one census block |

**Why use census blocks instead of block groups:**
- Block groups are ~4,000 acres (~20× larger). A block group with 1,500 people and a mix of residential, commercial, and industrial parcels distributes population across all of them. A census block with 75 people and 50 parcels is more likely to be homogeneous — if it's zoned industrial, all 50 parcels are industrial.
- The DU-weighted allocation method already corrects for misallocation (residential parcels get population, non-residential don't), so the coarser block group would be acceptable. But blocks are strictly better: fewer parcels per source zone means less variance in the allocation denominator.

### ACS 5-year block group

| Property | Value |
|---|---|
| Source | American Community Survey, sample-based estimate (~1-in-40 households per year, rolled up to 5 years) |
| Resolution | ~4,000 acres, ~1,500 people |
| Variables | Income, education, rent burden, poverty, vacancy rate, race/ethnicity detail, age distribution, household size — everything not in the decennial census short form |
| Frequency | Annual (rolling 5-year window) |
| Coverage | Every block group has estimates, but margins of error widen for small-population BGs |

**Limitations:** ACS is a survey, not a count. Margins of error at the block group level can be 20-40% for small-population variables (e.g., rent burden in a BG with 200 households). These are used for area-weighted means after population allocation, not as allocation controls, so the error doesn't cascade into population totals.

### Allocation detail

| Variable | Source | Resolution | Method |
|---|---|---|---|
| Population | Census 2020 block | ~200 ac | DU-weighted proportional (du / Σ du) |
| Households | Derived | Parcel-level | du × (1 - vacancy_rate) |
| Dwelling units | Assessor + built_form_key | Parcel-level | Estimated directly, not allocated from ACS |
| Demographics | ACS block group | ~4,000 ac | Area-weighted mean over intersecting parcels |
| Employment | LEHD LODES WAC block | ~200 ac | Sector-constrained by building sqft type |

---

## 10. Key Design Decisions

### Why built_form_key is derived first, then drives allocation

The development subtype is a property of the parcel's physical form, not a consequence of its allocated population. Assessing it first from assessor data ensures the classification is grounded in observation rather than inference. The allocation then uses `built_form_key` to determine:
- Whether the parcel receives population at all (residential vs non-residential)
- Whether population is spread across the parcel or constrained to building footprints
- Which employment sectors the parcel can host (via sqft type from Overture)

### Why building sqft by type replaces sector-to-form-key mapping

Originally proposed was a many-to-many mapping table (sector S → eligible built_form_keys). The Overture sqft breakdown is simpler and more accurate:
- A parcel with mixed uses (retail ground floor + offices above) needs no special handling — each building contributes to the right sqft bucket.
- The sqft buckets are a natural spatial quantity. They don't require maintaining a lookup table.
- The `built_form_key` still identifies the parcel's predominant use, but the sqft breakdown handles the marginal cases.

### Why Overture buildings are critical

- Building footprint provides the spatial mask for large-lot residential parcels.
- The `class` field splits sqft into residential/commercial/industrial — the basis for sector-constrained employment allocation.
- Building `levels` enables volume-based sqft estimation (footprint × levels).
- Intersection density derived from Overture transport road segments provides parcel-level urban form context. Computed from driveable road network endpoints (190k segments for Sacramento County) using hex-grid aggregation. Replaces the prior jurisdiction-level OSM approach with a continuous density surface.


---

## 11. SACOG Built Form Alignment — Gap Analysis & Proposed Heuristics

### 11.1 Observed Gaps

Cross-referencing BrewGIS `built_form_key` against SACOG v1 reference (`sac_cnty_region_base_canvas`, 2015 vintage) reveals systematic classification mismatches:

**Exact match rate: 0%** — the two systems use incompatible classification labels (BrewGIS uses short codes like `detsf_sl`; SACOG uses descriptive strings like `bt__low_density_detached_residential`). However, conceptual agreement can be assessed by mapping to equivalent categories.

| BrewGIS bf | Top SACOG match | Parcels | Agreement | Avg ref no_use acres |
|---|---|---|---|---|
| `detsf_sl` | low_density_detached_residential | 257,137 | ✅ reasonable — density may differ | 0.0 |
| `detsf_sl` | medium_density_detached_residential | 37,834 | ✅ acceptable | 0.0 |
| `detsf_sl` | **agriculture_sacog** | **14,778** | ❌ **ag misclassified as residential** | **6.6** |
| `detsf_sl` | **blank_place_type** | **14,915** | ❌ **unclassified** | **1.0** |
| `detsf_sl` | **rural_residential_sacog** | **13,367** | ❌ **rural misclassified as suburban** | **1.1** |
| `detsf_sl` | **park_andor_open_space_sacog** | **3,733** | ❌ **park misclassified as residential** | **4.7** |
| `civic` | low_density_detached_residential | 17,378 | ❌ **62% civic/school/church → house** | 0.0 |
| `commercial` | blank_place_type | 5,885 | ❌ **40% unclassified** | 2.5 |
| `detsf_ll` | **agriculture_sacog** | **22,311** | ❌ **82% large-lot → ag (not residential)** | **6.8** |

**Downstream impact:** The 410K acre "no use" gap (SACOG: 410,822 acres; BrewGIS: 3,915 acres) is explained almost entirely by these ~50K misclassified parcels, which carry 6-7 average no-use acres each in the SACOG reference but are assigned 100% residential area by BrewGIS due to the `du_subtype IS NOT NULL → full area to residential` logic.

### 11.2 Root Cause Analysis

The built form classification pipeline (`parcel_dasymetric_weights`) uses four tiers of inference:
1. **Tier 1:** Assessor sales data (8.5% coverage — only ~43K sold parcels)
2. **Tier 2:** Overture building footprint class + levels (90% coverage)
3. **Tier 3:** k-NN spatial imputation from known parcels
4. **Tier 4:** Lot-size heuristic

Critical gaps in the current approach:
- **Assessor `landuse` field is never consulted.** The county's official land-use designation (`sacog_assessor_parcels.landuse`) is available for every parcel but is only used in the `land_development_category` fallback, not in built form classification.
- **Lot-size thresholds in Tier 4 are too aggressive.** Parcels > 0.4 acres with any building are classified as `detsf_ll` regardless of assessor designation or actual use. SACOG classifies 82% of these as agriculture.
- **No footprint ratio check.** Parcels with a tiny building on a large lot (footprint_ratio < 0.02, lot > 3 acres) are classified as residential, but SACOG sees them as agriculture.
- **`du_subtype` short-circuits area allocation.** Once a parcel has any residential built form, `area_by_use` assigns 100% of its area to residential — the assessor's `land_development_category` is never checked.
- **k-NN imputation ignores land development category.** Tier 3 matches by intersection density, lot size, and footprint ratio within the same block group, but does not filter by the assessor-derived land development category.

### 11.3 Proposed Heuristics

#### Heuristic A: Assessor landuse as primary signal

Before checking Overture footprints or lot-size heuristics, consult the assessor's official `landuse` code for the parcel:

```
WHEN assessor.landuse IS NOT NULL THEN
    CASE assessor.landuse
        WHEN 'Agriculture'          → 'agricultural'
        WHEN 'Vacant'               → 'undeveloped'
        WHEN 'Industrial'           → 'industrial'
        WHEN 'Commercial'           → 'commercial'
        WHEN 'Public'               → 'civic'
        WHEN 'Single Family'        → assign by lot size (detsf_sl / detsf_ll)
        WHEN 'Multi Family'         → assign by unit count (mf2to4 / mf5p)
        ELSE                        → fall through to Overture-based tiers
    END
```

This directly uses the assessor's professional land-use classification — the same data source SACOG relies on. Impact: ~36K parcels currently misclassified as `detsf_sl`/`detsf_ll` that the assessor labels as agriculture would get the correct `agricultural` built form.

#### Heuristic B: Footprint ratio filter

For parcels without assessor landuse data (the ~90% with only Overture footprints):

```
-- A tiny building on a large parcel is not a residential built form.
-- It's an agricultural or rural parcel with an incidental structure.
WHEN lot_size_acres > 3
  AND COALESCE(footprint_ratio, 0) < 0.02
  AND (zone IS NULL OR zone NOT IN ('Residential', ...))
    THEN 'agricultural'
```

The 2% threshold comes from the data: SACOG-agriculture parcels average 0.01-0.05 footprint ratio. A barn or small house on 10+ acres should not make the parcel "residential."

#### Heuristic C: Revised Tier 4 thresholds

Current thresholds are too simplistic — `lot_size > 0.4 ac → detsf_ll`. From SACOG cross-validation, parcels >3 acres are predominantly agricultural:

```
lot_size > 10.0 ac  → agricultural (check zone/landuse first)
lot_size > 3.0 ac   → check assessor zone:
                         agricultural zone → agricultural
                         residential zone  → detsf_ll
                         NULL              → agricultural (conservative)
lot_size > 0.4 ac   → detsf_ll
lot_size > 0.15 ac  → detsf_sl
lot_size ≤ 0.15 ac  → attsf / mf (based on parcel_id diversity)
```

#### Heuristic D: Add land_development_category as k-NN filter

In Tier 3's spatial inference, add `land_development_category` as a partition key alongside block_group/tract:

```
-- Current: match by block_group + same built_form_key range
-- Proposed: match by block_group + same land_development_category

WHERE u.block_group_geoid = k.block_group_geoid
  AND u.land_development_category = k.land_development_category
```

This prevents imputing a `detsf_sl` built form from urban neighbors onto a parcel the assessor classifies as agricultural. The `land_development_category` is already computed from assessor use codes in the existing pipeline — it just needs to be propagated into the k-NN join condition.

### 11.4 Coverage Impact

| Heuristic | Parcels affected | Source of improvement |
|---|---|---|
| A: Assessor landuse | ~43K (8.5%) | Direct use of county land-use codes |
| B: Footprint ratio | ~18K (3.5%) | Catches parcels with tiny buildings on large lots |
| C: Better thresholds | ~27K (5.3%) | Fixes large-lot → residential misclassification |
| D: k-NN + lnd_cat | ~14K (2.8%) | Prevents cross-category imputation |

**Total addressable misclassification: ~60K parcels (12%),** accounting for overlaps between heuristics. This would reduce the "no use" area gap from 410K acres to approximately zero — the remaining gap would be methodological differences in how SACOG vs BrewGIS assign area within correctly classified residential parcels.

### 11.5 Implementation Priority

1. **Heuristic A (landuse)** — highest impact, lowest effort. The column already exists in `sacog_assessor_parcels`. Requires adding a CASE expression to the built form pipeline.
2. **Heuristic C (thresholds)** — simple threshold changes in Tier 4. No new data dependencies.
3. **Heuristic B (footprint ratio)** — requires joining `footprint_ratio` from `parcel_building_footprints` into the built form pipeline.
4. **Heuristic D (k-NN filter)** — requires propagating `land_development_category` through the k-NN join. Moderate refactor of the inference query.
