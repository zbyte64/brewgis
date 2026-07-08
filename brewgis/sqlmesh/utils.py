from __future__ import annotations


def sqlglot_to_pg_type(raw_type: str, column_name: str = "") -> str:
    """Map a sqlglot type string to a PostgreSQL DDL type.

    *column_name* is used as a hint for UNKNOWN types — columns named
    ``geometry``, ``local_geometry``, or ending in ``_geom``/``_geometry``
    are assigned ``GEOMETRY`` rather than the default ``TEXT``.
    """
    t = raw_type.upper().strip()
    # Geometry / PostGIS
    if t.startswith("GEOMETRY") or t.startswith("GEOGRAPHY"):
        return raw_type  # keep as-is (includes SRID qualifiers)
    # Standard mappings
    mapping = {
        "TEXT": "TEXT",
        "STRING": "TEXT",
        "VARCHAR": "TEXT",
        "CHAR": "TEXT",
        "INT": "INTEGER",
        "INTEGER": "INTEGER",
        "BIGINT": "BIGINT",
        "SMALLINT": "SMALLINT",
        "FLOAT": "DOUBLE PRECISION",
        "FLOAT8": "DOUBLE PRECISION",
        "FLOAT64": "DOUBLE PRECISION",
        "DOUBLE": "DOUBLE PRECISION",
        "REAL": "REAL",
        "NUMERIC": "NUMERIC",
        "DECIMAL": "NUMERIC",
        "BOOLEAN": "BOOLEAN",
        "BOOL": "BOOLEAN",
        "DATE": "DATE",
        "TIMESTAMP": "TIMESTAMP",
        "TIMESTAMPTZ": "TIMESTAMPTZ",
        "TIMESTAMP WITH TIME ZONE": "TIMESTAMPTZ",
        "JSONB": "JSONB",
        "JSON": "JSON",
        "UUID": "UUID",
    }
    # Handle parameterized types (NUMERIC(10,2), VARCHAR(255), etc.)
    if "(" in t and ")" in t:
        base = t.split("(")[0]
        params = t[t.index("(") :]
        mapped_base = mapping.get(base)
        if mapped_base:
            return f"{mapped_base}{params}"
        if base in (
            "GEOMETRY",
            "TEXT",
            "VARCHAR",
            "CHARACTER VARYING",
        ):
            return raw_type  # keep original
    base_type = mapping.get(t)
    if base_type:
        return base_type
    # Fallback for UNKNOWN / unresolvable
    if t in ("UNKNOWN", "NULL_TYPE", ""):
        cn = column_name.lower()
        # Geometry columns
        if cn in ("geometry", "local_geometry") or cn.endswith(("_geom", "_geometry")):
            return "GEOMETRY"
        # TEXT-hint column names (identifiers, codes, categories)
        if cn.endswith(
            (
                "_key",
                "_type",
                "_category",
                "_code",
                "_name",
                "_subtype",
                "_class",
            )
        ):
            return "TEXT"
        # ID columns — "parcel_id" → TEXT, but beware of area column names
        # like "area_parcel_no_use" which end in "_id" or "_use" but are numeric.
        if cn.endswith("_id") or cn in ("apn", "parcel_id"):
            return "TEXT"
        # Everything else defaults to DOUBLE PRECISION (the dominant
        # numeric type in this codebase).  This handles PostGIS function
        # outputs like ST_Area, ST_Intersection, etc.
        return "DOUBLE PRECISION"
    return raw_type
