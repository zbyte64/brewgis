import { LitElement, html, type PropertyValues } from 'lit'
import { property } from 'lit/decorators.js'
import maplibregl from 'maplibre-gl'
import type {
  Viewport,
  LayerConfig,
  ViewportChangeEvent,
  LayerClickEvent,
  LngLatBoundsTuple,
} from '../types/index.js'
import { generateLayerId, diffLayers } from '../utils/maplibre-helpers.js'
import { MapSocket, type MapEvent } from '../utils/map-socket.js'
import { PaintModeController } from './paint-mode.js'

/** Padding, in pixels, kept clear around a located feature. */
const FOCUS_PADDING_PX = 80
/** Zoom a located feature is fitted to at most, so one small parcel (or a
 * zero-area box around a point) doesn't fill the screen with a single lot. */
const FOCUS_MAX_ZOOM = 18

/** Quiet period, in ms, that collapses a burst of `layers.changed` events
 * (a bulk import saves many layers) into one layer-list fetch. */
const LAYERS_RELOAD_DEBOUNCE_MS = 150

/** Structural equality for JSON-shaped layer config values. */
function _sameJson(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b)
}

/** Escape text for safe interpolation into hover-tooltip HTML. */
function _escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export class BrewGisMap extends LitElement {
  /** @inheritdoc */
  static override shadowRootOptions: ShadowRootInit = {
    ...LitElement.shadowRootOptions,
    delegatesFocus: true,
  }

  /** MapLibre style URL or style object. Read from #basemap-style-data by default. */
  @property({ type: String })
  mapStyle: string = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json'

  /** Initial viewport state. */
  @property({ type: Object })
  viewport: Viewport | null = null

  /** Layer configurations to render on the map. */
  @property({ type: Array })
  layers: LayerConfig[] = []

  /** Map mode: 'view' for read-only, 'paint' for editing. */
  @property({ type: String })
  mode: 'view' | 'paint' = 'view'

  /** Scenario ID for paint operations (null in view mode). */
  @property({ type: Number, attribute: 'scenario-id' })
  scenarioId: number | null = null

  /** Selection mode for paint tool: 'click', 'box', or 'polygon'. */
  @property({ type: String, attribute: 'selection-mode' })
  selectionMode: 'click' | 'box' | 'polygon' = 'click'

  /** Canvas view layer ID for feature querying in paint mode. */
  @property({ type: String, attribute: 'canvas-layer-id' })
  canvasLayerId: string = ''

  /** Base (non-scenario) layer ID to inspect-click against when no scenario is active. */
  @property({ type: String, attribute: 'base-layer-id' })
  baseLayerId: string = ''

  /** Width of an open panel in pixels, for map viewport adjustment. */
  @property({ type: Number, attribute: 'panel-width' })
  panelWidth: number = 0

  /** Which side has an open panel: 'left', 'right', 'bottom', or null. */
  @property({ type: String, attribute: 'panel-side' })
  panelSide: 'left' | 'right' | 'bottom' | null = null

  /** Websocket path of the workspace's map-event stream (`/ws/workspace/<pk>/map/`).
   * When set, the map keeps itself current from server events — see
   * `_handleMapEvent`. Unset (e.g. scenario comparison), the map is static. */
  @property({ type: String, attribute: 'events-url' })
  eventsUrl: string = ''

  /** URL serving this map's layer configs as JSON (`map_layers_json`),
   * fetched again whenever a `layers.changed` event arrives. */
  @property({ type: String, attribute: 'layers-url' })
  layersUrl: string = ''

  @property({ type: Object, attribute: 'transform-request' })
  transformRequest:
    | ((url: string, resourceType?: string) => { url: string; headers?: Record<string, string> })
    | null = null

  /** Internal map instance. */
  private _map: maplibregl.Map | null = null

  /** Map-event websocket, open while `eventsUrl` is set and the element is connected. */
  private _socket: MapSocket | null = null

  /** Pending debounced layer-list reload. */
  private _layersReloadTimer: ReturnType<typeof setTimeout> | null = null

  /** Paint mode controller. */
  private _paintController: PaintModeController | null = null

  /** Tracks the last applied layers for diffing. */
  private _previousLayers: LayerConfig[] = []

  /** Tracks whether map is loaded. */
  private _mapLoaded = false

  /** Feature id currently shown as hovered (feature-state 'hover'), or null. */
  private _hoveredFeatureId: string | null = null

  /** Floating tooltip shown over a hovered parcel in view mode. */
  private _hoverPopup: maplibregl.Popup | null = null

  /** Geometry the located-feature outline was last drawn for, or null. Kept
   * so a style reload — which drops the overlay's own source and layers —
   * can restore it. */
  private _locatedGeometry: GeoJSON.Geometry | null = null

  constructor() {
    super()
  }

  /** @inheritdoc */
  override createRenderRoot(): HTMLElement | DocumentFragment {
    return this
  }

  /** @inheritdoc */
  override render(): unknown {
    return html` <div id="map-container" style="height: 100%; width: 100%;"></div> `
  }

  /** @inheritdoc */
  override connectedCallback(): void {
    super.connectedCallback()
  }

  /** @inheritdoc */
  override firstUpdated(_changedProperties: PropertyValues): void {
    super.firstUpdated(_changedProperties)
    this._initMap()
    this._connectEvents()
  }

  /** @inheritdoc */
  override updated(changedProperties: PropertyValues<this>): void {
    super.updated(changedProperties)

    if (changedProperties.has('layers') && this._mapLoaded) {
      this._syncLayers()
    }

    if (changedProperties.has('eventsUrl') && changedProperties.get('eventsUrl') !== undefined) {
      this._connectEvents()
    }

    if (changedProperties.has('viewport') && this.viewport && this._mapLoaded) {
      this._syncViewport(this.viewport)
    }

    if (changedProperties.has('mode') && this._mapLoaded) {
      this._syncMode()
    }

    if (changedProperties.has('selectionMode') && this._mapLoaded) {
      this._syncSelectionMode()
    }

    if (changedProperties.has('canvasLayerId') && this._mapLoaded) {
      this._syncCanvasLayer()
    }

    if (
      (changedProperties.has('panelWidth') || changedProperties.has('panelSide')) &&
      this._mapLoaded
    ) {
      this._adjustViewport()
    }
  }

  /** @inheritdoc */
  override disconnectedCallback(): void {
    super.disconnectedCallback()
    this._disconnectEvents()
    this._destroyMap()
  }

  // ─── Public API ─────────────────────────────────────────

  /**
   * Highlight specified features using MapLibre feature state.
   * Sets 'selected' = true on the specified feature IDs.
   */
  highlightFeatures(ids: string[]): void {
    if (!this._map) return
    const sourceId = this._findCanvasSourceId()
    if (!sourceId) return
    const sourceLayer = this._findCanvasSourceLayer()

    this.clearHighlight()
    for (const id of ids) {
      try {
        // `sourceLayer` is required for vector sources — omitting it makes
        // MapLibre log an error and drop the update instead of applying it.
        this._map.setFeatureState({ source: sourceId, sourceLayer, id }, { selected: true })
      } catch {
        // Feature or source may not exist yet
      }
    }
  }

  /** Clear all feature state highlights. */
  clearHighlight(): void {
    // Before the source check below: the located-feature outline is drawn
    // from the server's geometry, not from a source this map owns, so it
    // must go even when there is no canvas source to clear state on.
    this.clearLocatedFeature()
    if (!this._map) return
    const sourceId = this._findCanvasSourceId()
    if (!sourceId) return
    const sourceLayer = this._findCanvasSourceLayer()
    try {
      this._map.removeFeatureState({ source: sourceId, sourceLayer })
    } catch {
      // Source may not exist
    }
  }

  /** Get the PaintModeController instance. */
  get paintController(): PaintModeController | null {
    return this._paintController
  }

  /**
   * Resize the map to fit its container. Called by panel manager after panel opens/closes.
   */
  resize(): void {
    if (this._map) {
      this._map.resize()
    }
  }

  /**
   * Get the underlying maplibre-gl Map instance, e.g. for canvas export.
   */
  getMap(): maplibregl.Map | null {
    return this._map
  }

  /**
   * Preview a layer style by applying paint properties directly.
   * Used for live-preview updates in the symbology panel.
   */
  previewLayerStyle(layerId: string, paintProperties: Record<string, unknown>): void {
    if (!this._map) return
    for (const [key, value] of Object.entries(paintProperties)) {
      try {
        this._map.setPaintProperty(layerId, key, value)
      } catch {
        // Layer may not exist yet
      }
    }
  }

  /**
   * Draw a temporary overlay of a pending geometry edit — the cells a grid
   * would cut, or the shape a merge would leave — so the user can judge an
   * operation before applying it.
   *
   * One fixed source and two fixed layers: shown again, it replaces the
   * previous preview rather than stacking a second one. It is deliberately not
   * part of `layers`, which is the layer set `_syncLayers` diffs and removes
   * against.
   */
  showPaintPreview(geojson: GeoJSON.FeatureCollection): void {
    if (!this._map) return

    const sourceId = 'brew-gis-paint-preview'
    const source = this._map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined
    if (source) {
      source.setData(geojson)
      return
    }

    this._map.addSource(sourceId, { type: 'geojson', data: geojson })
    // Below the selection highlight when it exists: the marks showing which
    // parcels are selected belong on top of the preview of what they become.
    const before = this._map.getLayer('brew-gis-selection-highlight')
      ? 'brew-gis-selection-highlight'
      : undefined

    this._map.addLayer(
      {
        id: 'brew-gis-paint-preview-fill',
        type: 'fill',
        source: sourceId,
        paint: {
          'fill-color': '#f59e0b',
          'fill-opacity': 0.18,
        },
      },
      before,
    )

    this._map.addLayer(
      {
        id: 'brew-gis-paint-preview-line',
        type: 'line',
        source: sourceId,
        paint: {
          'line-color': '#d97706',
          'line-width': 2,
          'line-dasharray': [2, 2],
        },
      },
      before,
    )
  }

  /**
   * Remove the pending-edit preview overlay. A no-op when there is none, so
   * callers can clear it unconditionally.
   */
  clearPaintPreview(): void {
    if (!this._map) return

    for (const id of ['brew-gis-paint-preview-fill', 'brew-gis-paint-preview-line']) {
      if (this._map.getLayer(id)) this._map.removeLayer(id)
    }
    if (this._map.getSource('brew-gis-paint-preview')) {
      this._map.removeSource('brew-gis-paint-preview')
    }
  }

  /**
   * Set a layer's visibility.
   */
  setLayerVisibility(layerId: string, visible: boolean): void {
    if (!this._map) return
    try {
      this._map.setLayoutProperty(layerId, 'visibility', visible ? 'visible' : 'none')
    } catch {
      // Layer may not exist yet
    }
  }

  /**
   * Centre the map on one feature and select-highlight it — what the data
   * table's "Locate on map" button does.
   *
   * `bounds` is `[[west, south], [east, north]]` in lng/lat, read from the
   * feature's own table by the server (`layer_feature_bounds`) instead of
   * from this component's loaded tiles: `querySourceFeatures` only sees the
   * tiles the current viewport has fetched, so a row for a parcel a page
   * away in the table would find nothing to fit. `maxZoom` keeps a
   * single small parcel — or a point with a zero-area box — from being
   * zoomed to the tile server's own limit.
   *
   * The highlight is the same `selected` feature state a map click sets
   * (which only reaches the active parcel layer: the scenario's canvas view
   * when a scenario is active, else the base canvas), plus `showLocatedFeature`
   * for the rows that source cannot mark — a point layer's POIs, whose
   * circle symbology is drawn by a layer of its own.
   */
  focusFeature(
    featureId: string,
    bounds: LngLatBoundsTuple,
    geometry: GeoJSON.Geometry | null,
  ): void {
    if (!this._map) return

    this._map.fitBounds(bounds, {
      padding: FOCUS_PADDING_PX,
      maxZoom: FOCUS_MAX_ZOOM,
      duration: 600,
    })
    // Clears any previous outline of this same overlay (see clearHighlight).
    this.highlightFeatures([featureId])
    this.showLocatedFeature(geometry)
  }

  /**
   * Draw the located feature's own geometry on top of every layer.
   *
   * Feature-state highlighting only reaches the active parcel source, so a
   * located row of a point layer — `food_pois`, drawn as circles — would
   * otherwise zoom with nothing marking which circle it was. This draws the
   * geometry the server read from the row's table, in the same blue as a
   * clicked parcel's selection: a fill and thick outline for an area, a ring
   * around a point. `null` clears it.
   *
   * One fixed source and three fixed layers, shown again it replaces the
   * previous feature rather than stacking a second outline. Like the
   * paint-preview overlay it is deliberately not part of `layers`, the set
   * `_syncLayers` diffs and removes against.
   */
  showLocatedFeature(geometry: GeoJSON.Geometry | null): void {
    if (!this._map) return

    this._locatedGeometry = geometry
    const sourceId = 'brew-gis-locate-highlight'

    if (!this._map.getSource(sourceId)) {
      // Added empty, and given its data by the `setData` below on every call:
      // a source created *with* data and layers in the same frame stays blank
      // until some later reload (verified in the browser — the first locate
      // drew nothing until the second one called setData on it).
      this._map.addSource(sourceId, {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })
      // Topmost, unlike the parcel highlight layers: the layer's own symbology
      // (a POI's circle) is drawn over anything inserted beneath it, and what
      // is being marked here can be only a few pixels wide.
      this._map.addLayer({
        id: 'brew-gis-locate-highlight-fill',
        type: 'fill',
        source: sourceId,
        paint: { 'fill-color': '#2196f3', 'fill-opacity': 0.18 },
      })
      this._map.addLayer({
        id: 'brew-gis-locate-highlight-outline',
        type: 'line',
        source: sourceId,
        paint: { 'line-color': '#1565c0', 'line-width': 3 },
      })
      // A ring around a point, wide enough to be seen outside the symbology's
      // own circle; a fill/line layer draws nothing for a point geometry, and
      // a circle layer draws nothing for a parcel, so one overlay serves both.
      this._map.addLayer({
        id: 'brew-gis-locate-highlight-point',
        type: 'circle',
        source: sourceId,
        paint: {
          'circle-radius': 11,
          'circle-color': 'rgba(0,0,0,0)',
          'circle-stroke-color': '#1565c0',
          'circle-stroke-width': 2.5,
        },
      })
    }

    // Cast: `getSource` is typed as the whole `Source` union, which has no
    // `setData` — same as showPaintPreview below.
    const source = this._map.getSource(sourceId) as maplibregl.GeoJSONSource | undefined
    source?.setData({
      type: 'FeatureCollection',
      features: geometry ? [{ type: 'Feature', properties: {}, geometry }] : [],
    })
  }

  /**
   * Drop the located-feature outline. A no-op when nothing was located, so
   * callers can clear it unconditionally.
   */
  clearLocatedFeature(): void {
    this._locatedGeometry = null
    const source = this._map?.getSource('brew-gis-locate-highlight') as
      | maplibregl.GeoJSONSource
      | undefined
    source?.setData({ type: 'FeatureCollection', features: [] })
  }

  /**
   * Force the canvas view layer's vector tiles to be re-fetched.
   *
   * The scenario's canvas view is a live SQL view, so a paint write is
   * visible to new tile requests immediately (the server purges the tile
   * server's cached copy for it) — but MapLibre caches tiles it has already
   * fetched for the current viewport, so a paint/clear/undo would otherwise
   * stay invisible until an unrelated pan/zoom evicted the stale tiles.
   *
   * A scenario's canvas view backs *two* independent MapLibre sources — the
   * base layer (re-pointed at the canvas view, rendered with the workspace's
   * real symbology) and the separate "is painted" highlight overlay layer
   * (`canvasLayerId`). Each layer has its own source (see `_syncLayers`), so
   * both are refreshed.
   */
  refreshCanvasTiles(): void {
    const ids = [this.canvasLayerId, this.baseLayerId].filter((id) => !!id)
    if (ids.length > 0) this.refreshLayerTiles(ids)
  }

  /**
   * Force the given layers' tiles (by layer id or key; every layer when
   * omitted) to be re-fetched, by bumping a cache-busting param on their
   * sources' tile URLs. A TileJSON (`url`) source is re-requested instead.
   */
  refreshLayerTiles(layerIds?: string[]): void {
    if (!this._map) return

    const wanted = layerIds ? new Set(layerIds) : null
    const sourceIds = new Set(
      this.layers
        .filter((l) => !wanted || wanted.has(l.key) || (l.id !== undefined && wanted.has(l.id)))
        .map((l) => this._findSourceIdForLayerId(l.id ?? l.key))
        .filter((id): id is string => !!id),
    )

    const cacheBust = `_cb=${Date.now()}`
    const bust = (url: string): string => {
      const base = url.replace(/([?&])_cb=\d+(&|$)/, (_m, lead: string, tail: string) =>
        tail ? lead : '',
      )
      return `${base}${base.includes('?') ? '&' : '?'}${cacheBust}`
    }
    for (const sourceId of sourceIds) {
      const source = this._map.getSource<maplibregl.VectorTileSource>(sourceId)
      if (!source) continue
      if (typeof source.setTiles === 'function' && source.tiles) {
        source.setTiles(source.tiles.map(bust))
      } else if (typeof source.setUrl === 'function' && source.url) {
        source.setUrl(bust(source.url))
      }
    }
  }

  /**
   * Fetch the layer list from `layersUrl` and reconcile the map against it
   * (`_syncLayers` adds, removes, restyles and reorders in place).
   */
  async reloadLayers(): Promise<void> {
    if (!this.layersUrl) return
    const response = await fetch(this.layersUrl, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
    if (!response.ok) {
      console.warn('brew-gis-map: layer reload failed', response.status)
      return
    }
    this.layers = (await response.json()) as LayerConfig[]
  }

  /**
   * Switch the basemap at runtime. `setStyle` drops the data layers with the
   * old style; the `styledata` handler re-adds them.
   */
  setBasemapStyle(style: maplibregl.StyleSpecification | string): void {
    if (!this._map) return
    this._map.setStyle(style)
  }

  // ─── Map events (websocket) ─────────────────────────────

  private _connectEvents(): void {
    this._disconnectEvents()
    if (!this.eventsUrl || typeof WebSocket === 'undefined') return
    this._socket = new MapSocket(this.eventsUrl, {
      onEvent: (event) => {
        this._handleMapEvent(event)
      },
      onReconnected: () => {
        this._resyncAfterReconnect()
      },
    })
    this._socket.connect()
  }

  private _disconnectEvents(): void {
    this._socket?.close()
    this._socket = null
    if (this._layersReloadTimer !== null) {
      clearTimeout(this._layersReloadTimer)
      this._layersReloadTimer = null
    }
  }

  private _scheduleLayersReload(): void {
    if (this._layersReloadTimer !== null) clearTimeout(this._layersReloadTimer)
    this._layersReloadTimer = setTimeout(() => {
      this._layersReloadTimer = null
      void this.reloadLayers()
    }, LAYERS_RELOAD_DEBOUNCE_MS)
  }

  /** Events missed while the socket was down are gone: resync everything. */
  private _resyncAfterReconnect(): void {
    this._scheduleLayersReload()
    this.refreshLayerTiles()
    this._dispatchMapEvent({ kind: 'socket.reconnected' })
  }

  /**
   * Apply one server map event (see `services/map_events.py`), then re-dispatch
   * it as a bubbling `map-event` so page scripts (legend, paint toolbar,
   * toasts) can react too.
   */
  private _handleMapEvent(event: MapEvent): void {
    switch (event.kind) {
      case 'layers.changed':
        this._scheduleLayersReload()
        break
      case 'tiles.changed': {
        const scenarioId = event.scenario_id as number | null | undefined
        const layerKeys = event.layer_keys as string[] | undefined
        if (scenarioId != null) {
          if (scenarioId === Number(this.scenarioId)) this.refreshCanvasTiles()
        } else {
          this.refreshLayerTiles(layerKeys)
        }
        break
      }
      case 'basemap.changed':
        this.setBasemapStyle(event.style as maplibregl.StyleSpecification | string)
        break
    }
    this._dispatchMapEvent(event)
  }

  private _dispatchMapEvent(event: MapEvent): void {
    this.dispatchEvent(
      new CustomEvent<MapEvent>('map-event', { detail: event, bubbles: true, composed: true }),
    )
  }

  /**
   * Adjust map viewport padding to accommodate open panels.
   */
  private _adjustViewport(): void {
    if (!this._map) return
    try {
      if (this.panelSide === 'right' && this.panelWidth > 0) {
        this._map.setPadding({ top: 0, bottom: 0, left: 0, right: this.panelWidth })
      } else if (this.panelSide === 'bottom' && this.panelWidth > 0) {
        this._map.setPadding({ top: 0, bottom: this.panelWidth, left: 0, right: 0 })
      } else {
        this._map.setPadding({ top: 0, bottom: 0, left: 0, right: 0 })
      }
      this._map.resize()
    } catch {
      // Map may not be fully initialized
    }
  }

  /**
   * Resolve the basemap style from the script data tag or property fallback.
   *
   * Reads from `<script id="basemap-style-data" type="application/json">`
   * which can contain either a URL string (fetched by MapLibre) or a
   * full style object (used directly). Falls back to `this.mapStyle`.
   */
  private _resolveBasemapStyle(): maplibregl.StyleSpecification | string {
    const el =
      typeof document !== 'undefined' ? document.getElementById('basemap-style-data') : null
    if (el?.textContent) {
      try {
        const parsed: unknown = JSON.parse(el.textContent)
        if (typeof parsed === 'string') return parsed
        return parsed as maplibregl.StyleSpecification
      } catch {
        // Invalid JSON in script tag — fall through to property
      }
    }
    return this.mapStyle
  }

  // ─── Private Methods ──────────────────────────────────────

  /** Fallback default basemap URL. */
  private readonly _defaultMapStyle =
    'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json'

  /**
   * Find a good insertion point for data layers so they render
   * below water and roads in vector basemaps.
   *
   * Scans the current style for the first layer whose ID matches
   * water/road/building patterns. Returns undefined if no suitable
   * layer is found (data layers go on top — correct for raster
   * basemaps).
   */
  private _findBeforeId(): string | undefined {
    if (!this._map) return undefined

    const layers = this._map.getStyle().layers
    if (!layers) return undefined

    // Insert before the first water/road/building/label layer so
    // our data renders underneath those features.
    const beforePatterns = ['water', 'road', 'building', 'poi', 'label']

    for (const layer of layers) {
      const id = layer.id.toLowerCase()
      // Skip background and land layers — data should sit above them
      if (id === 'background' || id.startsWith('land')) continue
      if (beforePatterns.some((p) => id.includes(p))) {
        console.log('_findBeforeId matched:', layer.id)
        return layer.id
      }
    }

    console.log(
      '_findBeforeId no match — available layers:',
      layers.map((l) => l.id),
    )
    return undefined
  }

  private _initMap(): void {
    if (this._map) return

    const container = this.querySelector('#map-container') as HTMLElement
    if (!container) return

    const mapOptions: maplibregl.MapOptions = {
      container,
      style: this._resolveBasemapStyle(),
      // Export Map (workspace_map.html) reads the WebGL canvas via
      // getCanvas()/toDataURL() from a button click, not from inside a
      // render callback — without this, the drawing buffer is typically
      // already cleared by then and the capture comes out blank.
      preserveDrawingBuffer: true,
    }

    if (this.transformRequest) {
      mapOptions.transformRequest = this.transformRequest
    }

    if (this.viewport) {
      mapOptions.center = this.viewport.center
      mapOptions.zoom = this.viewport.zoom
      if (this.viewport.pitch !== undefined) mapOptions.pitch = this.viewport.pitch
      if (this.viewport.bearing !== undefined) mapOptions.bearing = this.viewport.bearing
    }

    const map = new maplibregl.Map(mapOptions)
    this._map = map

    map.addControl(new maplibregl.NavigationControl(), 'top-right')

    map.on('load', () => {
      this._mapLoaded = true

      if (this.layers.length > 0) {
        this._syncLayers()
      }

      if (this.mode === 'paint') {
        this._initPaintMode()
      }

      this.dispatchEvent(
        new CustomEvent('mapready', {
          detail: { map },
          bubbles: true,
          composed: true,
        }),
      )
    })

    // Re-add data layers after runtime basemap switches.
    // setStyle() wipes our sources/layers. styledata fires
    // when new style data loads; we detect the wipe by
    // checking if our first data source still exists.
    map.on('styledata', () => {
      if (!this._mapLoaded) return
      if (!this._map || this.layers.length === 0) return
      const firstId = this.layers[0].id || this.layers[0].key
      console.log('styledata', firstId, !this._map.getSource(firstId))
      if (!this._map.getSource(firstId)) {
        this._previousLayers = []
        this._syncLayers()
      }
    })

    map.on('idle', () => {
      this.dispatchEvent(
        new CustomEvent('mapidle', {
          detail: {},
          bubbles: true,
          composed: true,
        }),
      )
    })

    map.on('click', (e) => {
      this._handleInspectClick(e)
    })

    map.on('mousemove', (e) => {
      this._handleHoverMove(e)
    })

    container.addEventListener('mouseleave', () => {
      this._clearHover()
    })

    map.on('moveend', () => {
      if (!this._map) return
      const center = map.getCenter()
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
      )
    })
  }

  private _initPaintMode(): void {
    if (!this._map) return
    this._paintController = new PaintModeController(this._map, this)

    // Wire up canvas layer info to paint controller
    this._syncCanvasLayer()
    this._syncSelectionMode()

    // Add selection highlight overlay layer
    this._addSelectionHighlightLayer()

    this._paintController.activate()
  }

  private _syncSelectionMode(): void {
    if (this._paintController) {
      this._paintController.setSelectionMode(this.selectionMode)
    }
  }

  private _syncCanvasLayer(): void {
    if (!this._paintController || !this.canvasLayerId) return
    const sourceId = this._findCanvasSourceId()
    this._paintController.setCanvasLayer(
      this.canvasLayerId,
      sourceId || '',
      this._findCanvasSourceLayer(),
    )
  }

  /**
   * Handle a map click in 'view' mode by querying the active data layer
   * (canvas view when a scenario is active, otherwise the base layer) and
   * dispatching a `layerclick` event with the feature's already-decoded
   * tile properties — the canvas view's SELECT already includes every
   * base + painted column, so no extra fetch is needed just to read it.
   *
   * Paint mode's own click-to-select handler (`PaintModeController`) only
   * attaches while paint mode is active, so this coexists safely with it.
   */
  private _handleInspectClick(e: maplibregl.MapMouseEvent): void {
    if (this.mode !== 'view' || !this._map) return
    const targetLayerId = this.canvasLayerId || this.baseLayerId
    if (!targetLayerId || !this._map.getLayer(targetLayerId)) return

    const features = this._map.queryRenderedFeatures(e.point, { layers: [targetLayerId] })
    if (features.length === 0) return

    const feature = features[0]
    if (feature.id == null) return

    this.highlightFeatures([String(feature.id)])

    this.dispatchEvent(
      new CustomEvent<LayerClickEvent>('layerclick', {
        detail: {
          layerId: targetLayerId,
          features: [{ id: String(feature.id), properties: feature.properties ?? {} }],
          lngLat: { lng: e.lngLat.lng, lat: e.lngLat.lat },
          point: { x: e.point.x, y: e.point.y },
        },
        bubbles: true,
        composed: true,
      }),
    )
  }

  /**
   * Handle pointer movement in 'view' mode: outline whichever parcel is
   * under the cursor and show a tooltip of just the column(s) actually
   * driving each visible layer's symbology (`attribute_column`, e.g.
   * built_form_key on the base layer, vmt_total on a VMT result layer) —
   * not every column on those layers' tables.
   */
  private _handleHoverMove(e: maplibregl.MapMouseEvent): void {
    if (this.mode !== 'view' || !this._map) return

    // Resolved separately from the attribute-column loop below: the
    // painted-features overlay (`canvasLayerId`, when a scenario is active)
    // typically has no symbology attribute_column of its own, but it's
    // still the parcel that should get outlined and made clickable — the
    // same target `_handleInspectClick` queries.
    const targetLayerId = this.canvasLayerId || this.baseLayerId
    let primaryId: string | null = null
    if (targetLayerId && this._map.getLayer(targetLayerId)) {
      const targetFeatures = this._map.queryRenderedFeatures(e.point, {
        layers: [targetLayerId],
      })
      if (targetFeatures.length > 0 && targetFeatures[0].id != null) {
        primaryId = String(targetFeatures[0].id)
      }
    }

    const rows: { label: string; value: unknown; unit: string }[] = []
    for (let i = 0; i < this.layers.length; i++) {
      const layer = this.layers[i]
      const attributeColumn = layer.attribute_column
      if (!attributeColumn) continue

      const resolvedId = generateLayerId(layer, i)
      if (!this._map.getLayer(resolvedId)) continue
      if (this._map.getLayoutProperty(resolvedId, 'visibility') === 'none') continue

      const features = this._map.queryRenderedFeatures(e.point, { layers: [resolvedId] })
      if (features.length === 0) continue

      const value = features[0].properties?.[attributeColumn]
      if (value === undefined || value === null) continue

      rows.push({
        label: layer.attribute_label || attributeColumn,
        value,
        unit: layer.attribute_unit ?? '',
      })
    }

    if (primaryId === null && rows.length === 0) {
      this._clearHover()
      return
    }

    this._setHoverFeature(primaryId)
    if (rows.length > 0) {
      this._showHoverTooltip(e.lngLat, rows)
    } else {
      this._hoverPopup?.remove()
    }
    this._map.getCanvas().style.cursor = primaryId ? 'pointer' : ''
  }

  /** Clear hover outline, tooltip, and cursor override. */
  private _clearHover(): void {
    this._setHoverFeature(null)
    this._hoverPopup?.remove()
    if (this._map) this._map.getCanvas().style.cursor = ''
  }

  /** Set (or clear, with `id === null`) the 'hover' feature-state on the active parcel layer. */
  private _setHoverFeature(id: string | null): void {
    if (!this._map || id === this._hoveredFeatureId) return
    const sourceId = this._findCanvasSourceId()
    if (sourceId) {
      const sourceLayer = this._findCanvasSourceLayer()
      if (this._hoveredFeatureId !== null) {
        try {
          this._map.setFeatureState(
            { source: sourceId, sourceLayer, id: this._hoveredFeatureId },
            { hover: false },
          )
        } catch {
          // Feature or source may not exist
        }
      }
      if (id !== null) {
        try {
          this._map.setFeatureState({ source: sourceId, sourceLayer, id }, { hover: true })
        } catch {
          // Feature or source may not exist
        }
      }
    }
    this._hoveredFeatureId = id
  }

  /**
   * Show (creating on first use) a floating tooltip of symbology attribute
   * values at lngLat. Each value is suffixed with its column's unit
   * (``24.73 acres``); a column with no unit (``built_form_key``, counts)
   * renders bare.
   */
  private _showHoverTooltip(
    lngLat: maplibregl.LngLat,
    rows: { label: string; value: unknown; unit: string }[],
  ): void {
    if (!this._map) return

    const html = rows
      .map((row) => {
        const value =
          typeof row.value === 'number' ? Number(row.value.toFixed(2)) : String(row.value)
        const unit = row.unit
          ? ` <span style="color:#666;font-weight:400;">${_escapeHtml(row.unit)}</span>`
          : ''
        return (
          '<div style="display:flex;justify-content:space-between;gap:10px;font-size:0.75rem;white-space:nowrap;">' +
          `<span style="color:#666;">${_escapeHtml(String(row.label))}</span>` +
          `<span style="font-weight:600;">${_escapeHtml(String(value))}${unit}</span></div>`
        )
      })
      .join('')

    if (!this._hoverPopup) {
      this._hoverPopup = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
        className: 'brew-gis-hover-popup',
      })
    }
    this._hoverPopup.setLngLat(lngLat).setHTML(html).addTo(this._map)
  }

  private _syncMode(): void {
    if (this.mode === 'paint') {
      if (!this._paintController) {
        this._initPaintMode()
      } else if (!this._paintController.isActive) {
        this._paintController.activate()
      }
    } else {
      if (this._paintController?.isActive) {
        this._paintController.deactivate()
      }
    }
  }

  /**
   * Find the source ID for the active parcel layer — the scenario canvas
   * view when a scenario is active, otherwise the plain base layer. Falling
   * back to baseLayerId (rather than only canvasLayerId) lets selection and
   * hover highlighting work in plain view mode with no scenario, matching
   * how `_handleInspectClick` already resolves its target layer.
   */
  private _findCanvasSourceId(): string | null {
    return this._findSourceIdForLayerId(this.canvasLayerId || this.baseLayerId)
  }

  /** Find the MapLibre source ID backing a given layer config's id/key. */
  private _findSourceIdForLayerId(layerId: string): string | null {
    if (!this._map || !layerId) return null

    const layerConfig = this.layers.find((l) => l.id === layerId || l.key === layerId)
    if (layerConfig?.source) {
      return generateLayerId(layerConfig, this.layers.indexOf(layerConfig))
    }

    return null
  }

  /**
   * Find the source-layer name for the canvas view layer — required
   * alongside the source id for any vector-source setFeatureState /
   * removeFeatureState / addLayer call.
   */
  private _findCanvasSourceLayer(): string {
    const targetId = this.canvasLayerId || this.baseLayerId
    const layerConfig = this.layers.find((l) => l.id === targetId || l.key === targetId)
    return (layerConfig?.['source-layer'] as string | undefined) || 'default'
  }

  /**
   * Add a highlight layer for selected features — a thicker colored
   * outline plus a light fill — driven by the feature-state 'selected'
   * set via setFeatureState.
   */
  private _addSelectionHighlightLayer(): void {
    if (!this._map) return

    const layerId = 'brew-gis-selection-highlight'
    if (this._map.getLayer(layerId)) return

    const sourceId = this._findCanvasSourceId()
    if (!sourceId) return

    const sourceLayer = this._findCanvasSourceLayer()

    // Insert above the active parcel layer, or before water/roads
    const targetLayerId = this.canvasLayerId || this.baseLayerId
    const before = this._map.getLayer(targetLayerId) ? targetLayerId : this._findBeforeId()

    this._map.addLayer(
      {
        id: layerId,
        type: 'fill',
        source: sourceId,
        'source-layer': sourceLayer,
        paint: {
          'fill-color': [
            'case',
            ['boolean', ['feature-state', 'selected'], false],
            '#2196f3', // Blue for selected
            'rgba(0,0,0,0)', // Transparent otherwise
          ],
          'fill-opacity': ['case', ['boolean', ['feature-state', 'selected'], false], 0.25, 0],
        },
      },
      before,
    )

    // A fill layer's own outline is capped at 1px (fill-outline-color has
    // no width control), so a separate line layer gives selected parcels
    // an actually-visible thick border.
    this._map.addLayer(
      {
        id: `${layerId}-outline`,
        type: 'line',
        source: sourceId,
        'source-layer': sourceLayer,
        paint: {
          'line-color': '#1565c0',
          'line-width': ['case', ['boolean', ['feature-state', 'selected'], false], 3, 0],
        },
      },
      before,
    )
  }

  /**
   * Add a hover-outline layer for the parcel under the pointer in view mode
   * — driven by the feature-state 'hover' key (kept separate from
   * 'selected' so hovering never clobbers the click-selected highlight;
   * `removeFeatureState` with no id would otherwise wipe both at once).
   */
  private _addHoverHighlightLayer(): void {
    if (!this._map) return

    const layerId = 'brew-gis-hover-highlight'
    if (this._map.getLayer(layerId)) return

    const sourceId = this._findCanvasSourceId()
    if (!sourceId) return

    const sourceLayer = this._findCanvasSourceLayer()
    const targetLayerId = this.canvasLayerId || this.baseLayerId
    const before = this._map.getLayer(targetLayerId) ? targetLayerId : this._findBeforeId()

    this._map.addLayer(
      {
        id: layerId,
        type: 'line',
        source: sourceId,
        'source-layer': sourceLayer,
        paint: {
          'line-color': '#ff9800',
          'line-width': ['case', ['boolean', ['feature-state', 'hover'], false], 2, 0],
        },
      },
      before,
    )
  }

  private _syncViewport(vp: Viewport): void {
    if (!this._map) return

    const currentCenter = this._map.getCenter()
    const currentZoom = this._map.getZoom()
    const currentPitch = this._map.getPitch()
    const currentBearing = this._map.getBearing()

    const centerChanged = vp.center[0] !== currentCenter.lng || vp.center[1] !== currentCenter.lat
    const zoomChanged = vp.zoom !== currentZoom
    const pitchChanged = vp.pitch !== undefined && vp.pitch !== currentPitch
    const bearingChanged = vp.bearing !== undefined && vp.bearing !== currentBearing

    if (centerChanged || zoomChanged || pitchChanged || bearingChanged) {
      this._map.jumpTo({
        center: vp.center,
        zoom: vp.zoom,
        ...(vp.pitch !== undefined ? { pitch: vp.pitch } : {}),
        ...(vp.bearing !== undefined ? { bearing: vp.bearing } : {}),
      })
    }
  }

  /**
   * Reconcile the map's data layers with `layers`, in place: remove layers no
   * longer listed, add new ones, carry source/paint/layout changes over to
   * existing ones, and restack them in list order (first = bottom). Each layer
   * owns a source with the layer's own id.
   */
  private _syncLayers(): void {
    if (!this._map || !this._mapLoaded) return
    const map = this._map

    const { toRemove } = diffLayers(this.layers, this._previousLayers)

    for (const id of toRemove) {
      this._removeDataLayer(id)
    }

    // Compute insertion point so data layers render below
    // water and roads in vector basemaps.
    const beforeId = this._findBeforeId()

    const previousById = new Map(
      this._previousLayers.map((pl, i) => [generateLayerId(pl, i), pl] as const),
    )
    const resolvedIds: string[] = []

    for (let i = 0; i < this.layers.length; i++) {
      const layer = this.layers[i]
      const resolvedId = generateLayerId(layer, i)
      resolvedIds.push(resolvedId)
      const previous = previousById.get(resolvedId)

      if (previous && map.getLayer(resolvedId)) {
        if (previous.type !== layer.type || previous['source-layer'] !== layer['source-layer']) {
          // A layer's type and source-layer are fixed once added.
          this._removeDataLayer(resolvedId)
        } else {
          this._updateDataLayer(resolvedId, previous, layer)
          continue
        }
      }

      const { source, ...layerConfig } = layer
      if (!map.getSource(resolvedId)) {
        map.addSource(resolvedId, source as maplibregl.SourceSpecification)
      }
      const mlLayer: maplibregl.LayerSpecification = {
        id: resolvedId,
        type: layerConfig.type,
        source: resolvedId,
        ...(layerConfig['source-layer'] ? { 'source-layer': layerConfig['source-layer'] } : {}),
        ...(layerConfig.minzoom !== undefined ? { minzoom: layerConfig.minzoom } : {}),
        ...(layerConfig.maxzoom !== undefined ? { maxzoom: layerConfig.maxzoom } : {}),
        ...(layerConfig.paint ? { paint: layerConfig.paint } : {}),
        ...(layerConfig.layout ? { layout: layerConfig.layout } : {}),
      }
      map.addLayer(mlLayer, beforeId)
    }

    this._restackDataLayers(resolvedIds, beforeId)

    this._previousLayers = [...this.layers]

    // Idempotent — no-ops once already added, and no-ops until a base/canvas
    // layer is actually resolvable. Added here (rather than only in
    // _initPaintMode) so click-select and hover highlighting also work in
    // plain view mode, with no scenario and no paint mode ever activated.
    this._addHoverHighlightLayer()
    this._addSelectionHighlightLayer()
    // Not part of `layers` either — and a new style drops its source and
    // layers, so redraw it from the geometry it was last drawn for.
    if (this._locatedGeometry) this.showLocatedFeature(this._locatedGeometry)
  }

  /** Remove a data layer and its own source, plus any overlay drawn from that source. */
  private _removeDataLayer(id: string): void {
    if (!this._map) return
    const map = this._map
    if (map.getLayer(id)) map.removeLayer(id)
    if (map.getSource(id)) {
      // The hover/selection highlights draw from the canvas layer's source;
      // they are re-added against the new source after the sync.
      for (const styleLayer of map.getStyle().layers ?? []) {
        if ('source' in styleLayer && styleLayer.source === id) map.removeLayer(styleLayer.id)
      }
      map.removeSource(id)
    }
  }

  /** Carry a listed layer's changed source, paint, layout and zoom range over to the map. */
  private _updateDataLayer(id: string, previous: LayerConfig, next: LayerConfig): void {
    if (!this._map) return
    const map = this._map

    if (!_sameJson(previous.source, next.source)) {
      const source = map.getSource(id) as maplibregl.VectorTileSource | undefined
      const sameKind =
        source && previous.source.type === next.source.type && previous.source.type === 'vector'
      if (sameKind && next.source.tiles && typeof source.setTiles === 'function') {
        source.setTiles(next.source.tiles)
      } else if (sameKind && next.source.url && typeof source.setUrl === 'function') {
        source.setUrl(next.source.url)
      } else {
        this._removeDataLayer(id)
        const { source: spec, ...layerConfig } = next
        map.addSource(id, spec as maplibregl.SourceSpecification)
        map.addLayer({
          id,
          type: layerConfig.type,
          source: id,
          ...(layerConfig['source-layer'] ? { 'source-layer': layerConfig['source-layer'] } : {}),
          ...(layerConfig.paint ? { paint: layerConfig.paint } : {}),
          ...(layerConfig.layout ? { layout: layerConfig.layout } : {}),
        } as maplibregl.LayerSpecification)
        return
      }
    }

    for (const [kind, prev, nextProps] of [
      ['paint', previous.paint ?? {}, next.paint ?? {}],
      ['layout', previous.layout ?? {}, next.layout ?? {}],
    ] as const) {
      for (const name of new Set([...Object.keys(prev), ...Object.keys(nextProps)])) {
        if (_sameJson(prev[name], nextProps[name])) continue
        if (kind === 'paint') map.setPaintProperty(id, name, nextProps[name])
        else map.setLayoutProperty(id, name, nextProps[name])
      }
    }

    if (previous.minzoom !== next.minzoom || previous.maxzoom !== next.maxzoom) {
      map.setLayerZoomRange(id, next.minzoom ?? 0, next.maxzoom ?? 24)
    }
  }

  /**
   * Stack the data layers in list order (first = bottom) below the basemap's
   * insertion point, when they are not already. The hover/selection
   * highlights keep their place just under the layer they outline.
   */
  private _restackDataLayers(ids: string[], beforeId: string | undefined): void {
    if (!this._map) return
    const map = this._map
    const ours = new Set(ids)
    const current = (map.getStyle().layers ?? []).map((l) => l.id).filter((id) => ours.has(id))
    if (current.length === ids.length && current.every((id, i) => id === ids[i])) return

    for (const id of ids) {
      if (map.getLayer(id)) map.moveLayer(id, beforeId)
    }
    const targetLayerId = this.canvasLayerId || this.baseLayerId
    if (targetLayerId && map.getLayer(targetLayerId)) {
      for (const overlayId of [
        'brew-gis-selection-highlight',
        'brew-gis-selection-highlight-outline',
        'brew-gis-hover-highlight',
      ]) {
        if (map.getLayer(overlayId)) map.moveLayer(overlayId, targetLayerId)
      }
    }
  }

  private _destroyMap(): void {
    if (this._paintController?.isActive) {
      this._paintController.deactivate()
    }
    this._paintController = null

    this._hoverPopup?.remove()
    this._hoverPopup = null
    this._hoveredFeatureId = null
    this._locatedGeometry = null

    if (this._map) {
      this._map.remove()
      this._map = null
      this._mapLoaded = false
      this._previousLayers = []
    }
  }
}
