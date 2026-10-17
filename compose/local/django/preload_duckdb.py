"""Pre-download DuckDB extensions into the image cache.

This runs at Docker build time.  At runtime, INSTALL is a no-op (~0.01s).

Two extensions come from GitHub releases rather than a DuckDB repository:

- httpfs (https://github.com/zbyte64/duckdb-httpfs) — upstream httpfs v1.5.6
  plus the fix for duckdb-httpfs#407: a full download accepts a ``206 Partial
  Content`` reply, and a ``206`` whose ``Content-Range`` does not match the
  requested span falls back to a full download. overpass-api.de answers range
  requests that way, which stock httpfs fails as "Server sent back more data
  than expected" / "HTTP GET error" (see sqlmesh/macros/overpass_fetch.py).
  Built for linux_amd64 only.
- arcgis (https://github.com/zbyte64/duckdb-arcgis).

Each release asset is downloaded, checked against its pinned digest and placed
in a local extension repository at ``EXTENSION_REPOSITORY/v<duckdb
version>/<platform>/``, then installed from it. The SQLMesh duckdb gateway names
the same repository (``INSTALL x FROM ...`` is a no-op for an extension already
installed from that origin, while a bare ``INSTALL x`` would refuse it as coming
from another origin). Both binaries are built for one exact DuckDB version and
are unsigned, so every connection that loads them must allow unsigned
extensions and ``duckdb`` in requirements/base.txt must match
``DUCKDB_VERSION``.
"""

import hashlib
import io
import urllib.request
import zipfile
from pathlib import Path

import duckdb

DUCKDB_VERSION = "1.5.6"
EXTENSION_REPOSITORY = Path("/opt/duckdb-extensions")

HTTPFS_RELEASE = "v1.5.6-fix407"
# extension_version the fork's build reports — the commit it was built from.
HTTPFS_EXTENSION_VERSION = "654f19e"
# sha256 of the release's httpfs.duckdb_extension, from its asset digest.
HTTPFS_SHA256 = {
    "linux_amd64": "ef834b34c7423e662d1e825a882fa580e0e7d4b4c42c78f1f0168bd4a2d15e14",
}

ARCGIS_RELEASE = "v0.2.1"
# sha256 of each release asset, from the GitHub release's asset digests.
ARCGIS_SHA256 = {
    "linux_amd64": "04ecb0b219fe5540578fae56ff5310eccfac3da55be5b31a3f35c12cee3bf370",
    "linux_arm64": "16372575656d60530aa85dd534c6751ce62d49999adcb578da9f04c41b8aba7d",
}


def fetch_verified(url: str, sha256: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as response:
        payload = response.read()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != sha256:
        msg = f"{url}: sha256 {digest} does not match the pinned {sha256}"
        raise RuntimeError(msg)
    return payload


def stage(name: str, platform: str, binary: bytes) -> None:
    target = EXTENSION_REPOSITORY / f"v{DUCKDB_VERSION}" / platform
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{name}.duckdb_extension").write_bytes(binary)


def stage_httpfs(platform: str) -> None:
    if platform not in HTTPFS_SHA256:
        msg = f"httpfs {HTTPFS_RELEASE} has no build for {platform} (only {', '.join(HTTPFS_SHA256)})"
        raise RuntimeError(msg)
    url = f"https://github.com/zbyte64/duckdb-httpfs/releases/download/{HTTPFS_RELEASE}/httpfs.duckdb_extension"
    stage("httpfs", platform, fetch_verified(url, HTTPFS_SHA256[platform]))


def stage_arcgis(platform: str) -> None:
    asset = f"arcgis-{ARCGIS_RELEASE}-duckdb-v{DUCKDB_VERSION}-{platform}.zip"
    url = f"https://github.com/zbyte64/duckdb-arcgis/releases/download/{ARCGIS_RELEASE}/{asset}"
    with zipfile.ZipFile(
        io.BytesIO(fetch_verified(url, ARCGIS_SHA256[platform]))
    ) as archive:
        stage("arcgis", platform, archive.read("arcgis.duckdb_extension"))


if duckdb.__version__ != DUCKDB_VERSION:
    msg = (
        f"httpfs {HTTPFS_RELEASE} and arcgis {ARCGIS_RELEASE} are built for DuckDB "
        f"{DUCKDB_VERSION}, but the image has DuckDB {duckdb.__version__}"
    )
    raise RuntimeError(msg)

con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
try:
    platform = con.execute("SELECT platform FROM pragma_platform()").fetchall()[0][0]
    stage_httpfs(platform)
    stage_arcgis(platform)
    # httpfs first: installing anything below over https autoloads httpfs, and
    # from here on that is the fork.
    con.execute(f"FORCE INSTALL httpfs FROM '{EXTENSION_REPOSITORY}'")
    for ext in [
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
    con.execute(f"FORCE INSTALL arcgis FROM '{EXTENSION_REPOSITORY}'")
    con.execute("LOAD arcgis")
finally:
    con.close()

# A fresh session: the one above may already hold the stock httpfs it
# autoloaded before the fork was installed.
con = duckdb.connect(config={"allow_unsigned_extensions": "true"})
try:
    con.execute("LOAD httpfs")
    version = con.execute(
        "SELECT extension_version FROM duckdb_extensions() WHERE extension_name = 'httpfs'"
    ).fetchall()[0][0]
    if version != HTTPFS_EXTENSION_VERSION:
        msg = f"httpfs loads as {version}, expected the {HTTPFS_RELEASE} build {HTTPFS_EXTENSION_VERSION}"
        raise RuntimeError(msg)
    print("DuckDB extensions pre-loaded into image cache")
finally:
    con.close()
