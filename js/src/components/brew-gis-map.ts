import { LitElement, html, type PropertyValues } from 'lit'
import { property } from 'lit/decorators.js'
import maplibregl from 'maplibre-gl'
import type { Viewport, LayerConfig, ViewportChangeEvent, LayerClickEvent } from '../types/index.js'
import { generateLayerId, diffLayers } from '../utils/maplibre-helpers.js'
import { PaintModeController } from './paint-mode.js'

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

  @property({ type: Object, attribute: 'transform-request' })
  transformRequest:
    | ((url: string, resourceType?: string) => { url: string; headers?: Record<string, string> })
    | null = null

  /** Internal map instance. */
  private _map: maplibregl.Map | null = null

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
  }

  /** @inheritdoc */
  override updated(changedProperties: PropertyValues<this>): void {
    super.updated(changedProperties)

    if (changedProperties.has('layers') && this._mapLoaded) {
      this._syncLayers()
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
   * Zoom to fit a feature by its ID.
   * Queries the resolved layer ID and fits the map bounds.
   */
  zoomToFeature(featureId: string): void {
    if (!this._map) return
    const sourceId = this._findCanvasSourceId()
    if (!sourceId) return
    const canvasConfig = this.layers.find(
      (l) => l.id === this.canvasLayerId || l.key === this.canvasLayerId,
    )
    const sourceLayer = canvasConfig?.['source-layer']
    try {
      const features = this._map.querySourceFeatures(sourceId, {
        sourceLayer: sourceLayer,
        filter: ['==', ['id'], featureId],
      })
      if (features.length > 0) {
        const bounds = new maplibregl.LngLatBounds()
        for (const f of features) {
          if (f.geometry?.type === 'Point') {
            const coords = f.geometry.coordinates
            if (
              coords.length >= 2 &&
              typeof coords[0] === 'number' &&
              typeof coords[1] === 'number'
            ) {
              bounds.extend([coords[0], coords[1]] as [number, number])
            }
          }
        }
        if (!bounds.isEmpty()) {
          this._map.fitBounds(bounds, { padding: 50 })
        }
      }
    } catch {
      // Feature query failed
    }
  }

  /**
   * Force the canvas view layer's vector tiles to be re-fetched.
   *
   * `refresh_canvas_view()` on the server does a `CREATE OR REPLACE VIEW`,
   * which is picked up immediately by new tile requests — but MapLibre
   * caches tiles it has already fetched for the current viewport, so a
   * paint/clear/undo would otherwise stay invisible until an unrelated
   * pan/zoom evicted the stale tiles. Bumping a cache-busting param on the
   * source's tile URLs forces exactly that source to re-request.
   */
  refreshCanvasTiles(): void {
    if (!this._map) return

    // A scenario's canvas view backs *two* independent MapLibre sources —
    // the base layer (re-pointed at the canvas view, rendered with the
    // workspace's real symbology — what a user is actually looking at) and
    // the separate "is painted" highlight overlay layer (`canvasLayerId`).
    // Each layer gets its own dedicated source (see `_syncLayers`), so
    // busting only one leaves the other showing pre-paint tiles forever.
    // Refresh whichever of the two are present.
    const sourceIds = new Set(
      [this.canvasLayerId, this.baseLayerId]
        .map((layerId) => this._findSourceIdForLayerId(layerId))
        .filter((id): id is string => !!id),
    )
    if (sourceIds.size === 0) return

    const cacheBust = `_cb=${Date.now()}`
    for (const sourceId of sourceIds) {
      const source = this._map.getSource(sourceId) as maplibregl.VectorTileSource | undefined
      if (!source || typeof source.setTiles !== 'function' || !source.tiles) continue
      const tiles = source.tiles.map((url) => {
        const sep = url.includes('?') ? '&' : '?'
        return `${url}${sep}${cacheBust}`
      })
      source.setTiles(tiles)
    }
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

    const rows: { label: string; value: unknown }[] = []
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

      rows.push({ label: layer.attribute_label || attributeColumn, value })
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

  /** Show (creating on first use) a floating tooltip of symbology attribute values at lngLat. */
  private _showHoverTooltip(
    lngLat: maplibregl.LngLat,
    rows: { label: string; value: unknown }[],
  ): void {
    if (!this._map) return

    const html = rows
      .map((row) => {
        const value =
          typeof row.value === 'number' ? Number(row.value.toFixed(2)) : String(row.value)
        return (
          '<div style="display:flex;justify-content:space-between;gap:10px;font-size:0.75rem;white-space:nowrap;">' +
          `<span style="color:#666;">${_escapeHtml(String(row.label))}</span>` +
          `<span style="font-weight:600;">${_escapeHtml(String(value))}</span></div>`
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

  private _syncLayers(): void {
    if (!this._map || !this._mapLoaded) return

    const { toAdd: _toAdd, toRemove } = diffLayers(this.layers, this._previousLayers)

    // Remove stale layers (reverse order to maintain stack order)
    for (const id of toRemove) {
      try {
        if (this._map.getLayer(id)) {
          this._map.removeLayer(id)
        }
      } catch {
        // Layer might have been removed already
      }

      try {
        if (this._map.getSource(id)) {
          this._map.removeSource(id)
        }
      } catch {
        // Source might have been removed already
      }
    }

    // Compute insertion point so data layers render below
    // water and roads in vector basemaps.
    const allLayersBefore = (this._map?.getStyle().layers || []).map((l) => l.id)
    const beforeId = this._findBeforeId()
    console.log(
      '_syncLayers beforeId:',
      beforeId,
      '| total style layers:',
      allLayersBefore.length,
      '| adding:',
      this.layers.length,
      'layers',
    )

    // Add new layers
    for (let i = 0; i < this.layers.length; i++) {
      const layer = this.layers[i]
      const resolvedId = generateLayerId(layer, i)

      // Skip if this layer already exists
      if (
        this._previousLayers.some((pl) => {
          const plId = generateLayerId(pl, this._previousLayers.indexOf(pl))
          return plId === resolvedId
        })
      )
        continue

      // Extract source config from layer config
      const sourceId = resolvedId
      const { source, ...layerConfig } = layer

      // Add source if not already present
      if (!this._map.getSource(sourceId)) {
        this._map.addSource(sourceId, source as maplibregl.SourceSpecification)
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
      }

      this._map.addLayer(mlLayer, beforeId)
      console.log('  added layer:', resolvedId, 'before:', beforeId || '(top)')
    }

    this._previousLayers = [...this.layers]

    // Idempotent — no-ops once already added, and no-ops until a base/canvas
    // layer is actually resolvable. Added here (rather than only in
    // _initPaintMode) so click-select and hover highlighting also work in
    // plain view mode, with no scenario and no paint mode ever activated.
    this._addHoverHighlightLayer()
    this._addSelectionHighlightLayer()
  }

  private _destroyMap(): void {
    if (this._paintController?.isActive) {
      this._paintController.deactivate()
    }
    this._paintController = null

    this._hoverPopup?.remove()
    this._hoverPopup = null
    this._hoveredFeatureId = null

    if (this._map) {
      this._map.remove()
      this._map = null
      this._mapLoaded = false
      this._previousLayers = []
    }
  }
}
