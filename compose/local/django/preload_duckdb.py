"""Pre-download DuckDB extensions into the image cache.

This runs at Docker build time.  At runtime, INSTALL is a no-op (~0.01s).

The arcgis extension (https://github.com/zbyte64/duckdb-arcgis) is not in any
DuckDB repository: its release zip is downloaded, checked against the pinned
digest and unpacked into a local extension repository at
``ARCGIS_REPOSITORY/v<duckdb version>/<platform>/``, then installed from it.
The SQLMesh duckdb gateway names the same repository (``INSTALL arcgis FROM
...`` is a no-op for an extension already installed from that origin, while a
bare ``INSTALL arcgis`` would refuse it as coming from another origin). The
binary is built for one exact DuckDB version and is unsigned, so the connection
must allow unsigned extensions and ``duckdb`` in requirements/base.txt must
match ``ARCGIS_DUCKDB_VERSION``.
"""

import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

import duckdb

ARCGIS_RELEASE = "v0.2.0"
ARCGIS_DUCKDB_VERSION = "1.5.6"
ARCGIS_REPOSITORY = Path("/opt/duckdb-extensions")
# sha256 of each release asset, from the GitHub release's asset digests.
ARCGIS_SHA256 = {
    "linux_amd64": "d1859846af8d936d7202373710764198e1cdd8b10e6e39ac2e07e3dc3a3b97f4",
    "linux_arm64": "2f422d65912098b27bc0e0e20d7568fc907640bf259ba97a458e0df6bac5f1f0",
}


def stage_arcgis(platform: str) -> None:
    if duckdb.__version__ != ARCGIS_DUCKDB_VERSION:
        msg = (
            f"arcgis {ARCGIS_RELEASE} is built for DuckDB {ARCGIS_DUCKDB_VERSION}, "
            f"but the image has DuckDB {duckdb.__version__}"
        )
        raise RuntimeError(msg)
    asset = f"arcgis-{ARCGIS_RELEASE}-duckdb-v{ARCGIS_DUCKDB_VERSION}-{platform}.zip"
    url = f"https://github.com/zbyte64/duckdb-arcgis/releases/download/{ARCGIS_RELEASE}/{asset}"
    with urllib.request.urlopen(url, timeout=300) as response:
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != ARCGIS_SHA256[platform]:
        msg = f"{asset}: sha256 {digest} does not match the pinned {ARCGIS_SHA256[platform]}"
        raise RuntimeError(msg)
    target = ARCGIS_REPOSITORY / f"v{ARCGIS_DUCKDB_VERSION}" / platform
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        (target / "arcgis.duckdb_extension").write_bytes(
            archive.read("arcgis.duckdb_extension")
        )


con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
try:
    for ext in [
        "httpfs",
        "spatial",
        "postgres_scanner",
        "cache_httpfs",
        "zipfs",
        "raster",
    ]:
        if ext in ("cache_httpfs", "zipfs", "raster"):
            # FORCE: cache_httpfs artifacts pinned before ~2026-09 wedge on
            # s3:// parquet reads; always fetch the current community build.
            con.execute(f"FORCE INSTALL {ext} FROM community")
        else:
            con.execute(f"INSTALL {ext}")
        con.execute(f"LOAD {ext}")
    stage_arcgis(con.execute("SELECT platform FROM pragma_platform()").fetchall()[0][0])
    con.execute(f"FORCE INSTALL arcgis FROM '{ARCGIS_REPOSITORY}'")
    con.execute("LOAD arcgis")
    print("DuckDB extensions pre-loaded into image cache")
finally:
    con.close()
