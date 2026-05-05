import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import maplibregl from 'maplibre-gl';

// Import the component to trigger custom element registration
import '../index.js';
import { triggerMockEvent } from './setup.js';

function createMapElement() {
  return document.createElement('brew-gis-map');
}

async function createAndAttach(opts?: {
  layers?: unknown[];
  viewport?: unknown;
  mapStyle?: string;
}): Promise<{ el: HTMLElement; mockMap: any }> {
  const el = createMapElement();
  if (opts?.layers) el.setAttribute('layers', JSON.stringify(opts.layers));
  if (opts?.viewport) el.setAttribute('viewport', JSON.stringify(opts.viewport));
  if (opts?.mapStyle) el.setAttribute('map-style', opts.mapStyle);
  document.body.appendChild(el);
  await (el as any).updateComplete;
  // Allow one microtask for Lit's rendering to settle
  await new Promise((r) => setTimeout(r, 0));
  const mockMap = (maplibregl.Map as any).mock.results[0]?.value;
  return { el, mockMap };
}

describe('brew-gis-map', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    const el = document.querySelector('brew-gis-map');
    if (el) el.remove();
    vi.clearAllMocks();
  });

  it('renders a map container div after connection', async () => {
    const { el } = await createAndAttach();
    expect(el.innerHTML).toContain('map-container');
  });

  it('creates a Map instance on connection', async () => {
    await createAndAttach();
    expect(maplibregl.Map).toHaveBeenCalledTimes(1);
  });

  it('adds navigation controls', async () => {
    const { mockMap } = await createAndAttach();
    expect(mockMap.addControl).toHaveBeenCalledTimes(1);
  });

  it('dispatches mapready event on map load', async () => {
    const el = createMapElement();
    const readySpy = vi.fn();
    el.addEventListener('mapready', readySpy);

    document.body.appendChild(el);
    await (el as any).updateComplete;
    await new Promise((r) => setTimeout(r, 0));

    expect(readySpy).toHaveBeenCalledTimes(1);
    const event = readySpy.mock.calls[0][0] as CustomEvent;
    expect(event.detail.map).toBeDefined();
  });

  it('dispatches mapidle event', async () => {
    await createAndAttach();
    const idleSpy = vi.fn();
    const el = document.querySelector('brew-gis-map')!;
    el.addEventListener('mapidle', idleSpy);

    triggerMockEvent('idle');

    expect(idleSpy).toHaveBeenCalledTimes(1);
  });

  it('dispatches viewportchange on moveend', async () => {
    await createAndAttach();
    const changeSpy = vi.fn();
    const el = document.querySelector('brew-gis-map')!;
    el.addEventListener('viewportchange', changeSpy);

    triggerMockEvent('moveend');

    expect(changeSpy).toHaveBeenCalledTimes(1);
    const detail = changeSpy.mock.calls[0][0].detail;
    expect(detail).toHaveProperty('center');
    expect(detail).toHaveProperty('zoom');
    expect(detail).toHaveProperty('bounds');
  });

  it('passes initial viewport to Map constructor', async () => {
    await createAndAttach({
      viewport: { center: [10, 20], zoom: 5 },
    });

    expect(maplibregl.Map).toHaveBeenCalledWith(
      expect.objectContaining({ center: [10, 20], zoom: 5 }),
    );
  });

  it('does not call jumpTo when viewport matches current map state', async () => {
    const { mockMap } = await createAndAttach({
      viewport: { center: [0, 0], zoom: 1 },
    });

    // jumpTo is only called from _syncViewport on subsequent viewport changes
    expect(mockMap.jumpTo).not.toHaveBeenCalled();
  });

  it('calls jumpTo when viewport changes after initial render', async () => {
    const { mockMap } = await createAndAttach({
      viewport: { center: [0, 0], zoom: 1 },
    });

    vi.clearAllMocks();

    const el = document.querySelector('brew-gis-map')!;
    el.setAttribute('viewport', JSON.stringify({ center: [10, 20], zoom: 5 }));
    await (el as any).updateComplete;

    expect(mockMap.jumpTo).toHaveBeenCalledWith(
      expect.objectContaining({ center: [10, 20], zoom: 5 }),
    );
  });

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
    });

    expect(mockMap.addSource).toHaveBeenCalled();
    expect(mockMap.addLayer).toHaveBeenCalled();
    const layerCall = mockMap.addLayer.mock.calls[0][0];
    expect(layerCall.type).toBe('line');
  });

  it('detects layer removals when layers property changes', async () => {
    const { mockMap } = await createAndAttach({
      layers: [
        {
          key: 'remove-me',
          type: 'line',
          source: { type: 'vector', tiles: ['{z}/{x}/{y}'] },
        },
      ],
    });

    vi.clearAllMocks();

    const el = document.querySelector('brew-gis-map')!;
    el.setAttribute('layers', JSON.stringify([]));
    await (el as any).updateComplete;

    expect(mockMap.getLayer).toHaveBeenCalled();
  });

  it('cleans up on disconnectedCallback', async () => {
    const { mockMap } = await createAndAttach();

    const el = document.querySelector('brew-gis-map')!;
    el.remove();

    expect(mockMap.remove).toHaveBeenCalledTimes(1);
  });
});
