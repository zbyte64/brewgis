"""Network analysis module — OSM extraction and pgRouting topology.

Provides infrastructure for road network extraction from OpenStreetMap,
pgRouting topology building, and network distance computation.

Usage:
    extractor = NetworkExtractor()
    extractor.extract_for_bbox(minx, miny, maxx, maxy, schema="public")

    topology = NetworkTopology()
    topology.build(schema="public")
"""

from brewgis.workspace.analysis.network.extractor import NetworkExtractor
from brewgis.workspace.analysis.network.topology import NetworkTopology

__all__ = [
    "NetworkExtractor",
    "NetworkTopology",
]
