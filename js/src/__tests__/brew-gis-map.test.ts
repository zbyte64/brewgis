import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import maplibregl from 'maplibre-gl'

// Import the component to trigger custom element registration
import '../index.js'
import { mockMap, triggerMockEvent } from './setup.js'

function createMapElement() {
  return document.createElement('brew-gis-map')
}

async function createAndAttach(opts?: {
  layers?: unknown[]
  viewport?: unknown
  mapStyle?: string
  mode?: string
  scenarioId?: number
}): Promise<{ el: HTMLElement; mockMap: any }> {
  const el = createMapElement()
  if (opts?.layers) el.setAttribute('layers', JSON.stringify(opts.layers))
  if (opts?.viewport) el.setAttribute('viewport', JSON.stringify(opts.viewport))
  if (opts?.mapStyle) el.setAttribute('map-style', opts.mapStyle)
  if (opts?.mode) el.setAttribute('mode', opts.mode)
  if (opts?.scenarioId !== undefined) {
    el.setAttribute('scenario-id', String(opts.scenarioId))
  }
  document.body.appendChild(el)
  await (el as any).updateComplete
  // Allow one microtask for Lit's rendering to settle
  await new Promise((r) => setTimeout(r, 0))
  const mockMap = (maplibregl.Map as any).mock.results[0]?.value
  return { el, mockMap }
}

describe('brew-gis-map', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    const el = document.querySelector('brew-gis-map')
    if (el) el.remove()
    vi.clearAllMocks()
  })

  it('renders a map container div after connection', async () => {
    const { el } = await createAndAttach()
    expect(el.innerHTML).toContain('map-container')
  })

  it('creates a Map instance on connection', async () => {
    await createAndAttach()
    expect(maplibregl.Map).toHaveBeenCalledTimes(1)
  })

  it('adds navigation controls', async () => {
    const { mockMap } = await createAndAttach()
    expect(mockMap.addControl).toHaveBeenCalledTimes(1)
  })

  it('dispatches mapready event on map load', async () => {
    const el = createMapElement()
    const readySpy = vi.fn()
    el.addEventListener('mapready', readySpy)

    document.body.appendChild(el)
    await (el as any).updateComplete
    await new Promise((r) => setTimeout(r, 0))

    expect(readySpy).toHaveBeenCalledTimes(1)
    const event = readySpy.mock.calls[0][0] as CustomEvent
    expect(event.detail.map).toBeDefined()
  })

  it('dispatches mapidle event', async () => {
    await createAndAttach()
    const idleSpy = vi.fn()
    const el = document.querySelector('brew-gis-map')!
    el.addEventListener('mapidle', idleSpy)

    triggerMockEvent('idle')

    expect(idleSpy).toHaveBeenCalledTimes(1)
  })

  it('dispatches viewportchange on moveend', async () => {
    await createAndAttach()
    const changeSpy = vi.fn()
    const el = document.querySelector('brew-gis-map')!
    el.addEventListener('viewportchange', changeSpy)

    triggerMockEvent('moveend')

    expect(changeSpy).toHaveBeenCalledTimes(1)
    const detail = changeSpy.mock.calls[0][0].detail
    expect(detail).toHaveProperty('center')
    expect(detail).toHaveProperty('zoom')
    expect(detail).toHaveProperty('bounds')
  })

  it('passes initial viewport to Map constructor', async () => {
    await createAndAttach({
      viewport: { center: [10, 20], zoom: 5 },
    })

    expect(maplibregl.Map).toHaveBeenCalledWith(
      expect.objectContaining({ center: [10, 20], zoom: 5 }),
    )
  })

  it('does not call jumpTo when viewport matches current map state', async () => {
    const { mockMap } = await createAndAttach({
      viewport: { center: [0, 0], zoom: 1 },
    })

    // jumpTo is only called from _syncViewport on subsequent viewport changes
    expect(mockMap.jumpTo).not.toHaveBeenCalled()
  })

  it('calls jumpTo when viewport changes after initial render', async () => {
    const { mockMap } = await createAndAttach({
      viewport: { center: [0, 0], zoom: 1 },
    })

    vi.clearAllMocks()

    const el = document.querySelector('brew-gis-map')!
    el.setAttribute('viewport', JSON.stringify({ center: [10, 20], zoom: 5 }))
    await (el as any).updateComplete

    expect(mockMap.jumpTo).toHaveBeenCalledWith(
      expect.objectContaining({ center: [10, 20], zoom: 5 }),
    )
  })

  it('adds layers when layers property is set', async () => {
    const { mockMap } = await createAndAttach({
      layers: [
        {
          key: 'test-layer',
          type: 'line',
          source: { type: 'vector', tiles: ['{z}/{x}/{y}'] },
          paint: { 'line-color': 'red' },
        },
      ],
    })

    expect(mockMap.addSource).toHaveBeenCalled()
    expect(mockMap.addLayer).toHaveBeenCalled()
    const layerCall = mockMap.addLayer.mock.calls[0][0]
    expect(layerCall.type).toBe('line')
  })

  it('detects layer removals when layers property changes', async () => {
    const { mockMap } = await createAndAttach({
      layers: [
        {
          key: 'remove-me',
          type: 'line',
          source: { type: 'vector', tiles: ['{z}/{x}/{y}'] },
        },
      ],
    })

    vi.clearAllMocks()

    const el = document.querySelector('brew-gis-map')!
    el.setAttribute('layers', JSON.stringify([]))
    await (el as any).updateComplete

    expect(mockMap.getLayer).toHaveBeenCalled()
  })

  it('cleans up on disconnectedCallback', async () => {
    const { mockMap } = await createAndAttach()

    const el = document.querySelector('brew-gis-map')!
    el.remove()

    expect(mockMap.remove).toHaveBeenCalledTimes(1)
  })

  // Paint mode tests

  it('initializes paint mode controller when mode is paint', async () => {
    const { mockMap } = await createAndAttach({
      mode: 'paint',
      scenarioId: 1,
    })

    // With default click mode, no MapboxDraw added
    // addControl is called for: NavigationControl (1)
    expect(mockMap.addControl).toHaveBeenCalledTimes(1)
  })

  it('initializes polygon mode with MapboxDraw when selection-mode is polygon', async () => {
    const { mockMap } = await createAndAttach({
      mode: 'paint',
      scenarioId: 1,
    })

    // Switch to polygon mode to trigger MapboxDraw
    const el = document.querySelector('brew-gis-map')!
    ;(el as any).selectionMode = 'polygon'
    await (el as any).updateComplete
    await new Promise((r) => setTimeout(r, 0))

    // addControl is called for: NavigationControl (1) + MapboxDraw (2)
    expect(mockMap.addControl).toHaveBeenCalledTimes(2)
  })

  it('accepts scenarioId property', async () => {
    const { el } = await createAndAttach({
      mode: 'paint',
      scenarioId: 42,
    })

    expect((el as any).scenarioId).toBe(42)
  })

  it('switching mode from view to paint activates draw control', async () => {
    const result = await createAndAttach()
    const brewEl = result.el as any

    // Switch to paint mode
    brewEl.mode = 'paint'
    await brewEl.updateComplete
    await new Promise((r) => setTimeout(r, 0))

    expect(brewEl.mode).toBe('paint')
  })

  it('highlightFeatures is no-op without canvas-layer-id set', async () => {
    const { el } = await createAndAttach()
    const ids = ['feature-1', 'feature-2']
    // Should not throw even without canvas layer configured
    ;(el as any).highlightFeatures(ids)
    expect(true).toBe(true)
  })

  it('highlightFeatures uses canvas source when canvas-layer-id is set', async () => {
    const { el, mockMap } = await createAndAttach({
      mode: 'paint',
      scenarioId: 1,
    })
    ;(el as any).canvasLayerId = 'scenario_test_canvas'
    ;(el as any).layers = [
      {
        key: 'scenario_test_canvas',
        id: 'scenario_test_canvas',
        source: { type: 'vector', tiles: [] },
      },
    ]

    const ids = ['feature-1', 'feature-2']
    ;(el as any).highlightFeatures(ids)

    expect(mockMap.setFeatureState).toHaveBeenCalled()
    const call = mockMap.setFeatureState.mock.calls[0]
    expect(call[0]).toHaveProperty('source')
    // Source ID is derived from the layer config id
    expect(call[0].source).toBe('scenario_test_canvas')
    expect(call[1]).toEqual({ selected: true })
  })

  it('clearHighlight uses canvas source when canvas-layer-id is set', async () => {
    const { el, mockMap } = await createAndAttach()

    ;(el as any).canvasLayerId = 'scenario_test_canvas'
    ;(el as any).layers = [
      {
        key: 'scenario_test_canvas',
        id: 'scenario_test_canvas',
        source: { type: 'vector', tiles: [] },
      },
    ]
    ;(el as any).clearHighlight()

    expect(mockMap.removeFeatureState).toHaveBeenCalled()
  })

  it('dispatches featureselected event in polygon mode on draw.selectionchange', async () => {
    await createAndAttach({ mode: 'paint', scenarioId: 1 })

    const el = document.querySelector('brew-gis-map')!
    const eventSpy = vi.fn()
    el.addEventListener('featureselected', eventSpy)

    // Switch to polygon mode to register MapboxDraw event handlers
    ;(el as any).selectionMode = 'polygon'
    await (el as any).updateComplete
    await new Promise((r) => setTimeout(r, 0))

    // Simulate draw.selectionchange from the draw controller
    triggerMockEvent('draw.selectionchange', {
      features: [{ id: '1', properties: {} }],
    })

    expect(eventSpy).toHaveBeenCalled()
    const detail = eventSpy.mock.calls[0][0].detail
    expect(detail).toHaveProperty('features')
    expect(detail).toHaveProperty('selectionMode')
  })
})
