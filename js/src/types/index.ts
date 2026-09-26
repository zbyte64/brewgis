import type * as GeoJSON from 'geojson'

export interface Viewport {
  center: [number, number]
  zoom: number
  pitch?: number
  bearing?: number
}

export interface LayerSource {
  type: 'vector' | 'raster' | 'geojson'
  tiles?: string[]
  url?: string
  data?: GeoJSON.FeatureCollection
  [key: string]: unknown
}

export interface LayerConfig {
  id?: string
  key: string
  name?: string
  type: 'fill' | 'line' | 'circle' | 'symbol' | 'fill-extrusion' | 'heatmap' | 'hillshade'
  source: LayerSource
  'source-layer'?: string
  minzoom?: number
  maxzoom?: number
  paint?: Record<string, unknown>
  layout?: Record<string, unknown>
  /** Column driving this layer's symbology (e.g. built_form_key, vmt_total), for hover tooltips. */
  attribute_column?: string
  /** Human-readable label for attribute_column (e.g. "Built Form"). */
  attribute_label?: string
}

export interface ViewportChangeEvent {
  center: { lng: number; lat: number }
  zoom: number
  pitch: number
  bearing: number
  bounds: [[number, number], [number, number]]
}

export interface LayerClickEvent {
  layerId: string
  features: Record<string, unknown>[]
  lngLat: { lng: number; lat: number }
  point: { x: number; y: number }
}
export interface FeatureSelectedEvent {
  features: { id: string; layerId: string }[]
  mode: 'draw' | 'select' | 'clear'
  selectionMode?: 'click' | 'box' | 'polygon'
}

export interface PaintRequest {
  features: string[]
  column?: string
  value?: number | null
  bf_type?: 'building' | 'place'
  bf_id?: number
}

export interface LayerVisibilityEvent {
  layerId: string
  visible: boolean
}

export interface FeatureHighlightEvent {
  featureIds: string[]
  mode: 'highlight' | 'clear'
}

export interface LayerStylePreviewEvent {
  layerId: string
  paint: Record<string, unknown>
}

export interface ColumnMeta {
  name: string
  numeric: boolean
}

export type ColumnOperator =
  | 'eq'
  | 'neq'
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  | 'contains'
  | 'is_null'
  | 'is_not_null'

export interface ColumnNode {
  type: 'column'
  field: string
  operator: ColumnOperator
  value: string
  value_type: 'string' | 'number'
}

export interface GroupNode {
  type: 'group'
  operator: 'AND' | 'OR'
  children: FilterNode[]
}

export type SpatialMode = 'intersects' | 'excludes'

/**
 * A geospatial condition: intersect with (or exclude from) another layer's
 * geometry, optionally within a distance buffer. The server materializes a
 * filtered table for the layer and evaluates this predicate there
 * (`services.spatial_filter`), so the map's own filter expression ignores it.
 */
export interface SpatialNode {
  type: 'spatial'
  mode: SpatialMode
  /** `schema.table` of the layer to test against. */
  source: string
  /** Geometry column of `source`. */
  source_geom: string
  /** Buffer distance in metres around `source`; null for a plain intersection. */
  buffer_meters: number | null
}

/** One other-layer choice offered to a `SpatialNode`, from the server. */
export interface SpatialLayerOption {
  value: string
  label: string
  geometry: string
}

export type FilterNode = GroupNode | ColumnNode | SpatialNode

declare global {
  interface HTMLElementTagNameMap {
    'brew-gis-map': import('../components/brew-gis-map').BrewGisMap
    'filter-builder': import('../components/filter-builder').FilterBuilder
    'palette-picker': import('../components/palette-picker').PalettePicker
  }
}
