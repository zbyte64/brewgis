import { vi } from 'vitest'

// Mock maplibregl module before any component imports
const mockEventCallbacks: Record<string, Array<(...args: unknown[]) => void>> = {}

// Shared DOM elements for stable references across getCanvas/getContainer calls
const _sharedCanvas = document.createElement('canvas')
const _sharedContainer = document.createElement('div')
_sharedContainer.style.position = 'relative'

const mockMap = {
  on: vi.fn().mockImplementation((event: string, cb: (...args: unknown[]) => void) => {
    if (!mockEventCallbacks[event]) mockEventCallbacks[event] = []
    mockEventCallbacks[event].push(cb)
    // Fire 'load' synchronously — real MapLibre fires after style loads,
    // but for tests we simulate ready state immediately
    if (event === 'load') cb()
    return mockMap
  }),
  off: vi.fn().mockReturnThis(),
  remove: vi.fn(),
  jumpTo: vi.fn().mockReturnThis(),
  flyTo: vi.fn().mockReturnThis(),
  getCenter: vi.fn().mockReturnValue({ lng: 0, lat: 0 }),
  getZoom: vi.fn().mockReturnValue(1),
  getPitch: vi.fn().mockReturnValue(0),
  getBearing: vi.fn().mockReturnValue(0),
  getBounds: vi.fn().mockReturnValue({
    toArray: vi.fn().mockReturnValue([
      [-180, -90],
      [180, 90],
    ]),
  }),
  addSource: vi.fn(),
  removeSource: vi.fn(),
  getCanvas: vi.fn(() => _sharedCanvas),
  getContainer: vi.fn(() => _sharedContainer),
  queryRenderedFeatures: vi.fn().mockReturnValue([]),
  addLayer: vi.fn(),
  removeLayer: vi.fn(),
  getLayer: vi.fn().mockReturnValue(null),
  getSource: vi.fn().mockReturnValue(null), // return null by default — no sources pre-existing
  getStyle: vi.fn().mockReturnValue({ layers: [] }),
  loaded: vi.fn().mockReturnValue(true),
  once: vi.fn().mockImplementation((event: string, cb: (...args: unknown[]) => void) => {
    if (event === 'load') cb()
    return mockMap
  }),
  resize: vi.fn(),
  dragRotate: { enable: vi.fn(), disable: vi.fn() },
  touchZoomRotate: { enable: vi.fn(), disable: vi.fn() },
  addControl: vi.fn(),
  removeControl: vi.fn(),
  setFeatureState: vi.fn(),
  removeFeatureState: vi.fn(),
}

// Helper to trigger events in tests (e.g. triggerMockEvent('moveend'))
const triggerMockEvent = (event: string, ...args: unknown[]) => {
  const cbs = mockEventCallbacks[event] || []
  cbs.forEach((cb) => cb(...args))
}

// Mock draw instance
const mockDrawInstance = {
  getSelectedIds: vi.fn().mockReturnValue([]),
  getAll: vi.fn().mockReturnValue({ features: [] }),
  deleteAll: vi.fn(),
  changeMode: vi.fn(),
  onAdd: vi.fn().mockReturnValue(document.createElement('div')),
  onRemove: vi.fn(),
  add: vi.fn().mockReturnValue([]),
}

const mockNavControl = vi.fn()
const mockScaleControl = vi.fn()
const mockAttributionControl = vi.fn()

vi.mock('maplibre-gl', () => ({
  default: {
    Map: vi.fn(() => mockMap),
    NavigationControl: mockNavControl,
    ScaleControl: mockScaleControl,
    AttributionControl: mockAttributionControl,
    MapLibreGL: { setRTLTextPlugin: vi.fn() },
  },
  Map: vi.fn(() => mockMap),
  NavigationControl: mockNavControl,
  ScaleControl: mockScaleControl,
  AttributionControl: mockAttributionControl,
}))

vi.mock('maplibre-gl-draw', () => ({
  default: vi.fn(() => mockDrawInstance),
}))

export { mockMap, mockDrawInstance, triggerMockEvent }
