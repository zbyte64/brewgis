import maplibregl from 'maplibre-gl'
import MapboxDraw from 'maplibre-gl-draw'
import type { FeatureSelectedEvent } from '../types/index.js'

/**
 * Manages feature selection for paint mode.
 * Supports three selection modes: click, box, and polygon.
 */
export class PaintModeController {
  private _map: maplibregl.Map
  private _draw: MapboxDraw | null = null
  private _active = false
  private _host: HTMLElement
  private _selectionMode: 'click' | 'box' | 'polygon' = 'polygon'
  private _canvasLayerId = ''
  private _canvasSourceId = ''
  private _selectedFeatureIds: string[] = []

  // Box select state
  private _isBoxSelecting = false
  private _boxStartPoint: { x: number; y: number } | null = null
  private _boxRect: HTMLDivElement | null = null

  // Event handler references for cleanup
  private _boundClickHandler: ((e: MouseEvent) => void) | null = null
  private _boundMouseDownHandler: ((e: MouseEvent) => void) | null = null
  private _boundMouseMoveHandler: ((e: MouseEvent) => void) | null = null
  private _boundMouseUpHandler: ((e: MouseEvent) => void) | null = null

  constructor(map: maplibregl.Map, host: HTMLElement) {
    this._map = map
    this._host = host
  }

  get isActive(): boolean {
    return this._active
  }

  getSelectedFeatures(): string[] {
    return [...this._selectedFeatureIds]
  }

  /** Set the canvas view layer info for querying features. */
  setCanvasLayer(layerId: string, sourceId: string): void {
    this._canvasLayerId = layerId
    this._canvasSourceId = sourceId
  }

  /** Set the selection mode. */
  setSelectionMode(mode: 'click' | 'box' | 'polygon'): void {
    if (this._selectionMode === mode) return
    this._selectionMode = mode
    if (this._active) {
      this.deactivate()
      this.activate()
    }
  }

  /** Activate paint mode — set up selection handlers. */
  activate(): void {
    if (this._active) return
    this._active = true

    if (this._selectionMode === 'polygon') {
      this._activatePolygonMode()
    } else if (this._selectionMode === 'box') {
      this._activateBoxMode()
    } else {
      this._activateClickMode()
    }
  }

  /** Deactivate paint mode — remove all handlers and draw controls. */
  deactivate(): void {
    if (!this._active) return
    this._active = false

    this._removeDraw()
    this._removeClickHandler()
    this._removeBoxHandlers()
    this._removeBoxRect()
    this._clearSelectionHighlight()
    this._selectedFeatureIds = []
  }

  /** Clear all selection. */
  clearSelection(): void {
    this._selectedFeatureIds = []
    this._clearSelectionHighlight()
    if (this._draw) {
      this._draw.deleteAll()
      this._draw.changeMode('simple_select')
    }
    this._dispatchEvent({ features: [], mode: 'clear' })
  }

  // ── Click Mode ──────────────────────────────────────────

  private _activateClickMode(): void {
    this._boundClickHandler = (e: MouseEvent) => {
      const features = this._queryFeaturesAtPoint(e)
      if (features.length === 0) return
      const ids = features.map((f) => f.id)
      this._selectedFeatureIds = ids
      this._highlightFeatures(ids)
      this._dispatchEvent({
        features: ids.map((id) => ({ id, layerId: this._canvasLayerId })),
        mode: 'select',
      })
    }
    this._map.getCanvas().addEventListener('click', this._boundClickHandler)
  }

  private _removeClickHandler(): void {
    if (this._boundClickHandler) {
      this._map.getCanvas().removeEventListener('click', this._boundClickHandler)
      this._boundClickHandler = null
    }
  }

  // ── Box Select Mode ─────────────────────────────────────

  private _activateBoxMode(): void {
    const canvas = this._map.getCanvas()

    this._boundMouseDownHandler = (e: MouseEvent) => {
      this._isBoxSelecting = true
      this._boxStartPoint = { x: e.offsetX, y: e.offsetY }
      this._createBoxRect(e.offsetX, e.offsetY)
    }

    this._boundMouseMoveHandler = (e: MouseEvent) => {
      if (!this._isBoxSelecting || !this._boxStartPoint || !this._boxRect) return
      const x = Math.min(this._boxStartPoint.x, e.offsetX)
      const y = Math.min(this._boxStartPoint.y, e.offsetY)
      const w = Math.abs(e.offsetX - this._boxStartPoint.x)
      const h = Math.abs(e.offsetY - this._boxStartPoint.y)
      this._boxRect.style.left = x + 'px'
      this._boxRect.style.top = y + 'px'
      this._boxRect.style.width = w + 'px'
      this._boxRect.style.height = h + 'px'
    }

    this._boundMouseUpHandler = (e: MouseEvent) => {
      if (!this._isBoxSelecting || !this._boxStartPoint) return
      this._isBoxSelecting = false

      const x1 = Math.min(this._boxStartPoint.x, e.offsetX)
      const y1 = Math.min(this._boxStartPoint.y, e.offsetY)
      const x2 = Math.max(this._boxStartPoint.x, e.offsetX)
      const y2 = Math.max(this._boxStartPoint.y, e.offsetY)

      this._removeBoxRect()

      if (Math.abs(x2 - x1) < 3 && Math.abs(y2 - y1) < 3) return // Too small

      const bbox: [[number, number], [number, number]] = [
        [x1, y1],
        [x2, y2],
      ]
      const features = this._queryFeaturesInBbox(bbox)
      if (features.length === 0) return

      const ids = features.map((f) => f.id)
      this._selectedFeatureIds = ids
      this._highlightFeatures(ids)
      this._dispatchEvent({
        features: ids.map((id) => ({ id, layerId: this._canvasLayerId })),
        mode: 'select',
      })
    }

    canvas.addEventListener('mousedown', this._boundMouseDownHandler)
    canvas.addEventListener('mousemove', this._boundMouseMoveHandler)
    canvas.addEventListener('mouseup', this._boundMouseUpHandler)
  }

  private _removeBoxHandlers(): void {
    const canvas = this._map.getCanvas()
    if (this._boundMouseDownHandler) {
      canvas.removeEventListener('mousedown', this._boundMouseDownHandler)
      this._boundMouseDownHandler = null
    }
    if (this._boundMouseMoveHandler) {
      canvas.removeEventListener('mousemove', this._boundMouseMoveHandler)
      this._boundMouseMoveHandler = null
    }
    if (this._boundMouseUpHandler) {
      canvas.removeEventListener('mouseup', this._boundMouseUpHandler)
      this._boundMouseUpHandler = null
    }
  }

  private _createBoxRect(x: number, y: number): void {
    this._removeBoxRect()
    const rect = document.createElement('div')
    rect.style.cssText = `
      position: absolute;
      left: ${x}px;
      top: ${y}px;
      width: 0;
      height: 0;
      border: 2px solid #2196f3;
      background: rgba(33, 150, 243, 0.1);
      pointer-events: none;
      z-index: 1000;
    `
    const container = this._map.getContainer()
    container.appendChild(rect)
    this._boxRect = rect
  }

  private _removeBoxRect(): void {
    if (this._boxRect && this._boxRect.parentNode) {
      this._boxRect.parentNode.removeChild(this._boxRect)
    }
    this._boxRect = null
    this._boxStartPoint = null
    this._isBoxSelecting = false
  }

  // ── Polygon Mode (MapboxDraw) ───────────────────────────

  private _activatePolygonMode(): void {
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

    this._map.on('draw.create', this._handleDrawCreate)
    this._map.on('draw.delete', this._handleDrawDelete)
    this._map.on('draw.update', this._handleDrawUpdate)
    this._map.on('draw.selectionchange', this._handleSelectionChange)
  }

  private _removeDraw(): void {
    if (this._draw) {
      this._draw.deleteAll()
      // eslint-disable-next-line @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-argument
      this._map.removeControl(this._draw as any)
      this._draw = null
    }
    this._map.off('draw.create', this._handleDrawCreate)
    this._map.off('draw.delete', this._handleDrawDelete)
    this._map.off('draw.update', this._handleDrawUpdate)
    this._map.off('draw.selectionchange', this._handleSelectionChange)
  }

  private _handleDrawCreate = (e: { features: GeoJSON.Feature[] }): void => {
    const features = e.features
    if (features.length === 0) return

    // Get bounding box of drawn polygon and query real features
    const bbox = this._computeBbox(features)
    const tileFeatures = this._queryFeaturesInBbox(bbox)

    this._selectedFeatureIds = tileFeatures.map((f) => f.id)
    this._highlightFeatures(this._selectedFeatureIds)

    this._dispatchDrawEvent(
      this._selectedFeatureIds.map((id) => ({ id, layerId: this._canvasLayerId })),
      'draw',
    )

    // Enter simple_select so features are selectable
    if (this._draw) {
      this._draw.changeMode('simple_select', {
        featureIds: features.map((f) => String(f.id ?? '')),
      })
    }
  }

  private _handleDrawDelete = (_e: { features: GeoJSON.Feature[] }): void => {
    this._selectedFeatureIds = []
    this._clearSelectionHighlight()
    this._dispatchEvent({ features: [], mode: 'clear' })
  }

  private _handleDrawUpdate = (): void => {
    // Updates (drag vertices) don't change selection; no event needed
  }

  private _handleSelectionChange = (e: { features: GeoJSON.Feature[] }): void => {
    // When user clicks on a drawn polygon, we don't re-query tile features
    // Keep existing selected features but still notify consumers
    if (e.features.length === 0) {
      this._selectedFeatureIds = []
      this._clearSelectionHighlight()
      this._dispatchEvent({ features: [], mode: 'clear' })
    } else {
      this._dispatchEvent({
        features: this._selectedFeatureIds.map((id) => ({ id, layerId: this._canvasLayerId })),
        mode: 'select',
      })
    }
  }

  private _dispatchDrawEvent(
    features: { id: string; layerId: string }[],
    mode: 'draw' | 'select' | 'clear',
  ): void {
    this._dispatchEvent({ features, mode })
  }

  // ── Feature Querying ────────────────────────────────────

  private _queryFeaturesAtPoint(e: MouseEvent): { id: string }[] {
    if (!this._canvasLayerId) return []
    try {
      const point = { x: e.offsetX, y: e.offsetY } as any
      const features = this._map.queryRenderedFeatures(point, {
        layers: [this._canvasLayerId],
      })
      return features.filter((f) => f.id != null).map((f) => ({ id: String(f.id) }))
    } catch {
      return []
    }
  }

  private _queryFeaturesInBbox(bbox: [[number, number], [number, number]]): { id: string }[] {
    if (!this._canvasLayerId) return []
    try {
      const features = this._map.queryRenderedFeatures(bbox, {
        layers: [this._canvasLayerId],
      })
      return features.filter((f) => f.id != null).map((f) => ({ id: String(f.id) }))
    } catch {
      return []
    }
  }

  private _computeBbox(features: GeoJSON.Feature[]): [[number, number], [number, number]] {
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity

    for (const feature of features) {
      this._walkCoordinates(feature.geometry, (coord) => {
        minX = Math.min(minX, coord[0])
        minY = Math.min(minY, coord[1])
        maxX = Math.max(maxX, coord[0])
        maxY = Math.max(maxY, coord[1])
      })
    }

    return [
      [minX, minY],
      [maxX, maxY],
    ]
  }

  private _walkCoordinates(geo: GeoJSON.Geometry | null, fn: (coord: number[]) => void): void {
    if (!geo) return
    if (geo.type === 'Point') {
      fn(geo.coordinates)
    } else if (geo.type === 'MultiPoint' || geo.type === 'LineString') {
      geo.coordinates.forEach((c) => fn(c))
    } else if (geo.type === 'MultiLineString' || geo.type === 'Polygon') {
      geo.coordinates.forEach((ring) => ring.forEach((c) => fn(c)))
    } else if (geo.type === 'MultiPolygon') {
      geo.coordinates.forEach((poly) => poly.forEach((ring) => ring.forEach((c) => fn(c))))
    } else if (geo.type === 'GeometryCollection') {
      geo.geometries.forEach((g) => this._walkCoordinates(g, fn))
    }
  }

  // ── Highlighting ────────────────────────────────────────

  private _highlightFeatures(ids: string[]): void {
    this._clearSelectionHighlight()
    if (!this._canvasSourceId) return
    for (const id of ids) {
      try {
        this._map.setFeatureState({ source: this._canvasSourceId, id } as any, { selected: true })
      } catch {
        // Feature or source may not exist
      }
    }
  }

  private _clearSelectionHighlight(): void {
    if (!this._canvasSourceId) return
    try {
      ;(this._map as any).removeFeatureState({ source: this._canvasSourceId })
    } catch {
      // Source may not exist
    }
  }

  // ── Event Dispatch ──────────────────────────────────────

  private _dispatchEvent(detail: FeatureSelectedEvent): void {
    this._host.dispatchEvent(
      new CustomEvent('featureselected', {
        detail: { ...detail, selectionMode: this._selectionMode },
        bubbles: true,
        composed: true,
      }),
    )

    this._host.dispatchEvent(
      new CustomEvent('paint-features-changed', {
        detail: { ...detail, selectionMode: this._selectionMode },
        bubbles: true,
        composed: true,
      }),
    )
  }
}
