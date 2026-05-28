import { LitElement, html, type PropertyValues } from 'lit'
import { property } from 'lit/decorators.js'
import maplibregl from 'maplibre-gl'
import type { Viewport, LayerConfig, ViewportChangeEvent } from '../types/index.js'
import { generateLayerId, diffLayers } from '../utils/maplibre-helpers.js'
import { PaintModeController } from './paint-mode.js'

export class BrewGisMap extends LitElement {
  /** @inheritdoc */
  static override shadowRootOptions: ShadowRootInit = {
    ...LitElement.shadowRootOptions,
    delegatesFocus: true,
  }

  /** MapLibre style URL or style object. */
  @property({ type: String, attribute: 'map-style' })
  mapStyle: string =
    'https://raw.githubusercontent.com/go2garret/maps/main/src/assets/json/openStreetMap.json'

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

  constructor() {
    super()
  }

  /** @inheritdoc */
  override createRenderRoot(): HTMLElement | DocumentFragment {
    return this
  }

  /** @inheritdoc */
  override render(): unknown {
    return html` <div id="map-container" style="height: 90vh; width: 100%;"></div> `
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

    this.clearHighlight()
    for (const id of ids) {
      try {
        this._map.setFeatureState({ source: sourceId, id } as any, { selected: true })
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
    try {
      ;(this._map as any).removeFeatureState({ source: sourceId })
    } catch {
      // Source may not exist
    }
  }

  /** Get the PaintModeController instance. */
  get paintController(): PaintModeController | null {
    return this._paintController
  }

  // ─── Private Methods ──────────────────────────────────────

  private _initMap(): void {
    if (this._map) return

    const container = this.querySelector('#map-container') as HTMLElement
    if (!container) return

    const mapOptions: maplibregl.MapOptions = {
      container,
      style: this.mapStyle,
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

      // Initialize paint mode if active
      if (this.mode === 'paint') {
        this._initPaintMode()
      }

      this._previousLayers = [...this.layers]

      this.dispatchEvent(
        new CustomEvent('mapready', {
          detail: { map },
          bubbles: true,
          composed: true,
        }),
      )
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
    this._paintController.setCanvasLayer(this.canvasLayerId, sourceId || '')
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
   * Find the source ID for the canvas view layer.
   */
  private _findCanvasSourceId(): string | null {
    if (!this._map || !this.canvasLayerId) return null

    // Check rendered layers on the map
    const style = this._map.getStyle()
    if (style?.layers) {
      const canvasLayer = style.layers.find((l) => l.id === this.canvasLayerId) as any
      if (canvasLayer?.source) return canvasLayer.source
    }

    // Fall back to this.layers prop
    const layerConfig = this.layers.find(
      (l) => l.id === this.canvasLayerId || l.key === this.canvasLayerId,
    )
    if (layerConfig?.source) {
      return generateLayerId(layerConfig, this.layers.indexOf(layerConfig))
    }

    return null
  }

  /**
   * Add a fill layer that highlights selected features (blue).
   * Uses the feature-state 'selected' set via setFeatureState.
   */
  private _addSelectionHighlightLayer(): void {
    if (!this._map) return

    const layerId = 'brew-gis-selection-highlight'
    if (this._map.getLayer(layerId)) return

    const sourceId = this._findCanvasSourceId()
    if (!sourceId) return

    // Find source-layer from the canvas layer config
    const canvasConfig = this.layers.find(
      (l) => l.id === this.canvasLayerId || l.key === this.canvasLayerId,
    )
    const sourceLayer = canvasConfig?.['source-layer'] || 'default'

    // Insert above the canvas view layer
    const before = this._map.getLayer(this.canvasLayerId) ? this.canvasLayerId : undefined

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
          'fill-opacity': ['case', ['boolean', ['feature-state', 'selected'], false], 0.4, 0],
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

      this._map.addLayer(mlLayer)
    }

    this._previousLayers = [...this.layers]
  }

  private _destroyMap(): void {
    if (this._paintController?.isActive) {
      this._paintController.deactivate()
    }
    this._paintController = null

    if (this._map) {
      this._map.remove()
      this._map = null
      this._mapLoaded = false
      this._previousLayers = []
    }
  }
}
