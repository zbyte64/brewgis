import { LitElement, html, type PropertyValues } from 'lit';
import { property } from 'lit/decorators.js';
import maplibregl from 'maplibre-gl';
import type { Viewport, LayerConfig, ViewportChangeEvent } from '../types/index.js';
import { generateLayerId, diffLayers } from '../utils/maplibre-helpers.js';

export class BrewGisMap extends LitElement {
  /** @inheritdoc */
  static override shadowRootOptions: ShadowRootInit = {
    ...LitElement.shadowRootOptions,
    delegatesFocus: true,
  };

  /** MapLibre style URL or style object. */
  @property({ type: String, attribute: 'map-style' })
  mapStyle: string = 'https://raw.githubusercontent.com/go2garret/maps/main/src/assets/json/openStreetMap.json';

  /** Initial viewport state. */
  @property({ type: Object })
  viewport: Viewport | null = null;

  /** Layer configurations to render on the map. */
  @property({ type: Array })
  layers: LayerConfig[] = [];

  @property({ type: Object, attribute: 'transform-request' })
  transformRequest: ((url: string, resourceType?: string) => { url: string; headers?: Record<string, string> }) | null = null;

  /** Internal map instance. */
  private _map: maplibregl.Map | null = null;

  /** Tracks the last applied layers for diffing. */
  private _previousLayers: LayerConfig[] = [];

  /** Tracks whether map is loaded. */
  private _mapLoaded = false;

  /** Creates an element. Creates the shadow root. */
  constructor() {
    super();
    // No shadow DOM needed for map container — mapbox-gl needs a real DOM element
  }

  /** @inheritdoc */
  override createRenderRoot(): HTMLElement | DocumentFragment {
    // Render into light DOM so MapLibre can find its container element
    return this;
  }

  /** @inheritdoc */
  override render(): unknown {
    return html`
      <div id="map-container" style="height: 90vh; width: 100%;"></div>
    `;
  }

  /** @inheritdoc */
  override connectedCallback(): void {
    super.connectedCallback();
    // Defer map creation to firstUpdated so the container DOM exists
  }

  /** @inheritdoc */
  override firstUpdated(_changedProperties: PropertyValues): void {
    super.firstUpdated(_changedProperties);
    this._initMap();
  }

  /** @inheritdoc */
  override updated(changedProperties: PropertyValues<this>): void {
    super.updated(changedProperties);

    if (changedProperties.has('layers') && this._mapLoaded) {
      this._syncLayers();
    }

    if (changedProperties.has('viewport') && this.viewport && this._mapLoaded) {
      this._syncViewport(this.viewport);
    }
  }

  /** @inheritdoc */
  override disconnectedCallback(): void {
    super.disconnectedCallback();
    this._destroyMap();
  }

  // ─── Private Methods ──────────────────────────────────────

  private _initMap(): void {
    if (this._map) return;

    const container = this.querySelector('#map-container') as HTMLElement;
    if (!container) return;

    const mapOptions: maplibregl.MapOptions = {
      container,
      style: this.mapStyle,
    };


    if (this.transformRequest) {
      mapOptions.transformRequest = this.transformRequest;
    }

    if (this.viewport) {
      mapOptions.center = this.viewport.center;
      mapOptions.zoom = this.viewport.zoom;
      if (this.viewport.pitch !== undefined) mapOptions.pitch = this.viewport.pitch;
      if (this.viewport.bearing !== undefined) mapOptions.bearing = this.viewport.bearing;
    }

    const map = new maplibregl.Map(mapOptions);
    this._map = map;

    // Add navigation controls
    map.addControl(new maplibregl.NavigationControl(), 'top-right');

    map.on('load', () => {
      this._mapLoaded = true;

      if (this.layers.length > 0) {
        this._syncLayers();
      }

      this._previousLayers = [...this.layers];

      this.dispatchEvent(
        new CustomEvent('mapready', {
          detail: { map },
          bubbles: true,
          composed: true,
        }),
      );
    });

    map.on('idle', () => {
      this.dispatchEvent(
        new CustomEvent('mapidle', {
          detail: {},
          bubbles: true,
          composed: true,
        }),
      );
    });

    map.on('moveend', () => {
      if (!this._map) return;
      const center = map.getCenter();
      this.dispatchEvent(
        new CustomEvent<ViewportChangeEvent>('viewportchange', {
          detail: {
            center: { lng: center.lng, lat: center.lat },
            zoom: map.getZoom(),
            pitch: map.getPitch(),
            bearing: map.getBearing(),
            bounds: map.getBounds().toArray() as [[number, number], [number, number]],
          },
          bubbles: true,
          composed: true,
        }),
      );
    });
  }

  private _syncViewport(vp: Viewport): void {
    if (!this._map) return;

    const currentCenter = this._map.getCenter();
    const currentZoom = this._map.getZoom();
    const currentPitch = this._map.getPitch();
    const currentBearing = this._map.getBearing();

    const centerChanged =
      vp.center[0] !== currentCenter.lng || vp.center[1] !== currentCenter.lat;
    const zoomChanged = vp.zoom !== currentZoom;
    const pitchChanged = vp.pitch !== undefined && vp.pitch !== currentPitch;
    const bearingChanged = vp.bearing !== undefined && vp.bearing !== currentBearing;

    if (centerChanged || zoomChanged || pitchChanged || bearingChanged) {
      this._map.jumpTo({
        center: vp.center,
        zoom: vp.zoom,
        ...(vp.pitch !== undefined ? { pitch: vp.pitch } : {}),
        ...(vp.bearing !== undefined ? { bearing: vp.bearing } : {}),
      });
    }
  }

  private _syncLayers(): void {
    if (!this._map || !this._mapLoaded) return;

    const { toAdd, toRemove } = diffLayers(this.layers, this._previousLayers);

    // Remove stale layers (reverse order to maintain stack order)
    for (const id of toRemove) {
      try {
        if (this._map.getLayer(id)) {
          this._map.removeLayer(id);
        }
      } catch {
        // Layer might have been removed already
      }

      try {
        if (this._map.getSource(id)) {
          this._map.removeSource(id);
        }
      } catch {
        // Source might have been removed already
      }
    }

    // Add new layers
    for (let i = 0; i < this.layers.length; i++) {
      const layer = this.layers[i];
      const resolvedId = generateLayerId(layer, i);

      // Skip if this layer already exists
      if (this._previousLayers.some((pl) => {
        const plId = generateLayerId(pl, this._previousLayers.indexOf(pl));
        return plId === resolvedId;
      })) continue;

      // Extract source config from layer config
      const sourceId = resolvedId;
      const { source, ...layerConfig } = layer;

      // Add source if not already present
      if (!this._map.getSource(sourceId)) {
        this._map.addSource(sourceId, source as maplibregl.SourceSpecification);
      }

      // Add layer referencing the source
      const mlLayer: maplibregl.LayerSpecification = {
        id: resolvedId,
        type: layerConfig.type,
        source: sourceId,
        ...(layerConfig['source-layer'] ? { 'source-layer': layerConfig['source-layer'] } : {}),
        ...(layerConfig.minzoom !== undefined ? { minzoom: layerConfig.minzoom } : {}),
        ...(layerConfig.maxzoom !== undefined ? { maxzoom: layerConfig.maxzoom } : {}),
        ...(layerConfig.paint ? { paint: layerConfig.paint } : {}),
        ...(layerConfig.layout ? { layout: layerConfig.layout } : {}),
      };

      this._map.addLayer(mlLayer);
    }

    this._previousLayers = [...this.layers];
  }

  private _destroyMap(): void {
    if (this._map) {
      this._map.remove();
      this._map = null;
      this._mapLoaded = false;
      this._previousLayers = [];
    }
  }
}
