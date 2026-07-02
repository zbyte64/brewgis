"""Unit tests for sacog_assessor_parcels consolidation — sub-unit APN grouping."""


def test_consolidated_parcel_has_positive_lot_size(context):
    """After consolidation, the output parcel has lot_size_acres > 0."""
    result = context.evaluate(
        "brewgis.assessor.sacog_assessor_parcels",
        start="2024-01-01",
        end="2024-01-01",
        inputs={
            "public.sacog_assessor_parcels_raw": [
                {
                    "apn": "81000050040",
                    "lotsize": 0,
                    "landuse": "ATA00A",
                    "zone": "R-M-H",
                    "jurisdiction": "SAC",
                    "geometry": (
                        "SRID=4326;"
                        "POLYGON((-121.178 38.707, -121.177 38.707, "
                        "-121.177 38.708, -121.178 38.708, -121.178 38.707))"
                    ),
                },
                {
                    "apn": "81000050060",
                    "lotsize": 0,
                    "landuse": "ATA00A",
                    "zone": "R-M-H",
                    "jurisdiction": "SAC",
                    "geometry": (
                        "SRID=4326;"
                        "POLYGON((-121.176 38.707, -121.175 38.707, "
                        "-121.175 38.708, -121.176 38.708, -121.176 38.707))"
                    ),
                },
            ],
        },
        additional_vars={"local_srid": 3310},
    )
    df = result[0].df
    assert len(df) == 1, f"Expected 1 consolidated row, got {len(df)}"
    assert df["lot_size_acres"].iloc[0] > 0, (
        f"Expected lot_size_acres > 0, got {df['lot_size_acres'].iloc[0]}"
    )
