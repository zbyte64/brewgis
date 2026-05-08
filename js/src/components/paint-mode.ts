import maplibregl from 'maplibre-gl'
import MapboxDraw from 'maplibre-gl-draw'
import type { FeatureSelectedEvent } from '../types/index.js'

/**
 * Manages the maplibre-gl-draw instance for paint mode.
 *
 * Provides polygon/rectangle/box-select drawing and selection,
 * dispatches custom events on feature selection changes.
 */
export class PaintModeController {
  private _map: maplibregl.Map
  private _draw: MapboxDraw | null = null
  private _active = false
  private _host: HTMLElement

  constructor(map: maplibregl.Map, host: HTMLElement) {
    this._map = map
    this._host = host
  }

  /** Activate paint mode — add draw control to map. */
  activate(): void {
    if (this._active) return
    this._active = true

    this._draw = new MapboxDraw({
      displayControlsDefault: false,
      controls: {
        polygon: true,
        trash: true,
      },
      defaultMode: 'simple_select',
    })

    // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-argument
    this._map.addControl(this._draw as any, 'top-left')

    // Register draw event handlers
    this._map.on('draw.create', this._handleDrawCreate)
    this._map.on('draw.delete', this._handleDrawDelete)
    this._map.on('draw.update', this._handleDrawUpdate)
    this._map.on('draw.selectionchange', this._handleSelectionChange)
  }

  /** Deactivate paint mode — remove draw control from map. */
  deactivate(): void {
    if (!this._active) return
    this._active = false

    if (this._draw) {
      this._draw.deleteAll()
      // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-argument
      this._map.removeControl(this._draw as any)
      this._draw = null
    }

    this._clearSelectionHighlight()

    // Remove event listeners
    this._map.off('draw.create', this._handleDrawCreate)
    this._map.off('draw.delete', this._handleDrawDelete)
    this._map.off('draw.update', this._handleDrawUpdate)
    this._map.off('draw.selectionchange', this._handleSelectionChange)
  }

  /** Whether paint mode is active. */
  get isActive(): boolean {
    return this._active
  }

  /** Get selected feature IDs from the draw instance. */
  getSelectedFeatures(): string[] {
    if (!this._draw) return []
    return this._draw.getSelectedIds()
  }

  /** Clear all selection. */
  clearSelection(): void {
    if (!this._draw) return
    this._draw.deleteAll()
    this._draw.changeMode('simple_select')
    this._dispatchEvent({ features: [], mode: 'clear' })
  }

  /** Set paint mode to simple_select (for clearing drawing state). */
  setSelectMode(featureIds?: string[]): void {
    if (!this._draw) return
    this._draw.changeMode('simple_select', featureIds ? { featureIds } : undefined)
  }

  // ── Event Handlers ──────────────────────────────────────

  private _handleDrawCreate = (e: { features: GeoJSON.Feature[] }) => {
    this._dispatchDrawEvent(e.features, 'draw')
  }

  private _handleDrawDelete = (_e: { features: GeoJSON.Feature[] }) => {
    this._dispatchEvent({ features: [], mode: 'clear' })
  }

  private _handleDrawUpdate = () => {
    // Updates (drag vertices) don't change selection; no event needed
  }

  private _handleSelectionChange = (e: { features: GeoJSON.Feature[] }) => {
    const features = e.features.map((f) => ({
      id: String(f.id ?? ''),
      layerId: '',
    }))
    this._dispatchEvent({
      features,
      mode: features.length > 0 ? 'select' : 'clear',
    })
  }

  // ── Internal Helpers ────────────────────────────────────

  private _dispatchDrawEvent(features: GeoJSON.Feature[], mode: 'draw' | 'select' | 'clear'): void {
    const mapped = features.map((f) => ({
      id: String(f.id ?? ''),
      layerId: '',
    }))
    // After draw.create, enter simple_select so features are selectable
    if (this._draw && mode === 'draw') {
      this._draw.changeMode('simple_select', {
        featureIds: mapped.map((f) => f.id),
      })
    }
    this._dispatchEvent({ features: mapped, mode })
  }

  private _dispatchEvent(detail: FeatureSelectedEvent): void {
    this._host.dispatchEvent(
      new CustomEvent('featureselected', {
        detail,
        bubbles: true,
        composed: true,
      }),
    )

    this._host.dispatchEvent(
      new CustomEvent('paint-features-changed', {
        detail,
        bubbles: true,
        composed: true,
      }),
    )
  }

  private _clearSelectionHighlight(): void {
    // Remove any draw-related feature states from the map
    try {
      this._map.removeFeatureState({ source: 'composite' })
    } catch {
      // Ignore — source may not exist
    }
  }
}
