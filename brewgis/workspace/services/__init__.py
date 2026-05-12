"""Service layer for data fetching, allocation, stitching, and imputation."""

from brewgis.workspace.services.built_form_classifier import BuiltFormAssignment
from brewgis.workspace.services.built_form_classifier import BuiltFormClassifier
from brewgis.workspace.services.base_canvas_manager import BaseCanvasManager
from brewgis.workspace.services.base_canvas_schema import BaseCanvasSchema
from brewgis.workspace.services.imputation_engine import ImputationEngine
from brewgis.workspace.services.imputation_engine import ImputationResult
from brewgis.workspace.services.imputation_engine import ImputationRule
from brewgis.workspace.services.imputation_engine import ImputationStrategy
from brewgis.workspace.services.spatial_allocator import allocate_attributes
from brewgis.workspace.services.stitcher import impute_area_proportional
from brewgis.workspace.services.stitcher import impute_built_form_default
from brewgis.workspace.services.stitcher import impute_constant
from brewgis.workspace.services.stitcher import stitch_dataframe
from brewgis.workspace.services.synthetic_parcel_generator import (
    generate_synthetic_parcels,
)

__all__ = [
    "BaseCanvasManager",
    "BuiltFormAssignment",
    "BuiltFormClassifier",
    "BaseCanvasSchema",
    "ImputationEngine",
    "ImputationResult",
    "ImputationRule",
    "ImputationStrategy",
    "allocate_attributes",
    "generate_synthetic_parcels",
    "impute_area_proportional",
    "impute_built_form_default",
    "impute_constant",
    "stitch_dataframe",
]
