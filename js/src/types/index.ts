import type * as GeoJSON from 'geojson';

export interface Viewport {
  center: [number, number];
  zoom: number;
  pitch?: number;
  bearing?: number;
}

export interface LayerSource {
  type: 'vector' | 'raster' | 'geojson';
  tiles?: string[];
  url?: string;
  data?: GeoJSON.FeatureCollection;
  [key: string]: unknown;
}

export interface LayerConfig {
  id?: string;
  key: string;
  type: 'fill' | 'line' | 'circle' | 'symbol' | 'fill-extrusion' | 'heatmap' | 'hillshade';
  source: LayerSource;
  'source-layer'?: string;
  minzoom?: number;
  maxzoom?: number;
  paint?: Record<string, unknown>;
  layout?: Record<string, unknown>;
}

export interface ViewportChangeEvent {
  center: { lng: number; lat: number };
  zoom: number;
  pitch: number;
  bearing: number;
  bounds: [[number, number], [number, number]];
}

export interface LayerClickEvent {
  layerId: string;
  features: Record<string, unknown>[];
  lngLat: { lng: number; lat: number };
  point: { x: number; y: number };
}

declare global {
  interface HTMLElementTagNameMap {
    'brew-gis-map': import('../components/brew-gis-map').BrewGisMap;
  }
}
