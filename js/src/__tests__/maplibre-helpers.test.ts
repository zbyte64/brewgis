import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { LayerConfig } from '../types/index.js';
import {
  generateLayerId,
  validateLayerIds,
  diffLayers,
} from '../utils/maplibre-helpers.js';

describe('generateLayerId', () => {
  it('uses user-provided id when present', () => {
    const layer: LayerConfig = {
      id: 'my-custom-id',
      key: 'test-layer',
      type: 'line',
      source: { type: 'vector', tiles: ['{z}/{x}/{y}'] },
    };
    expect(generateLayerId(layer, 0)).toBe('my-custom-id');
  });

  it('generates ID from key and index when id is absent', () => {
    const layer: LayerConfig = {
      key: 'test-layer',
      type: 'line',
      source: { type: 'vector', tiles: ['{z}/{x}/{y}'] },
    };
    const id = generateLayerId(layer, 3);
    expect(id).toMatch(/^test-layer-3-\d+$/);
  });

  it('produces unique IDs for consecutive calls without id', () => {
    const layer: LayerConfig = {
      key: 'roads',
      type: 'line',
      source: { type: 'vector', tiles: ['{z}/{x}/{y}'] },
    };
    const id1 = generateLayerId(layer, 0);
    const id2 = generateLayerId(layer, 0);
    expect(id1).not.toBe(id2);
  });
});

describe('validateLayerIds', () => {
  it('returns empty array when all IDs are unique', () => {
    const layers: LayerConfig[] = [
      { id: 'a', key: 'a', type: 'line', source: { type: 'vector', tiles: [] } },
      { id: 'b', key: 'b', type: 'line', source: { type: 'vector', tiles: [] } },
      { id: 'c', key: 'c', type: 'line', source: { type: 'vector', tiles: [] } },
    ];
    expect(validateLayerIds(layers)).toEqual([]);
  });

  it('returns duplicate IDs', () => {
    const layers: LayerConfig[] = [
      { id: 'dup', key: 'a', type: 'line', source: { type: 'vector', tiles: [] } },
      { id: 'unique', key: 'b', type: 'line', source: { type: 'vector', tiles: [] } },
      { id: 'dup', key: 'c', type: 'line', source: { type: 'vector', tiles: [] } },
    ];
    expect(validateLayerIds(layers)).toEqual(['dup']);
  });

  it('ignores layers without ids', () => {
    const layers: LayerConfig[] = [
      { key: 'a', type: 'line', source: { type: 'vector', tiles: [] } },
      { key: 'b', type: 'line', source: { type: 'vector', tiles: [] } },
    ];
    expect(validateLayerIds(layers)).toEqual([]);
  });
});

describe('diffLayers', () => {
  const baseLayer = (id: string, key?: string): LayerConfig => ({
    id,
    key: key ?? id,
    type: 'line',
    source: { type: 'vector', tiles: [] },
  });

  it('returns all next layers as toAdd when prev is empty', () => {
    const next = [baseLayer('a'), baseLayer('b')];
    const { toAdd, toRemove } = diffLayers(next, []);
    expect(toAdd).toHaveLength(2);
    expect(toRemove).toHaveLength(0);
  });

  it('returns all prev ids as toRemove when next is empty', () => {
    const prev = [baseLayer('a'), baseLayer('b')];
    const { toAdd, toRemove } = diffLayers([], prev);
    expect(toAdd).toHaveLength(0);
    expect(toRemove).toHaveLength(2);
  });

  it('detects added layers', () => {
    const prev = [baseLayer('a')];
    const next = [baseLayer('a'), baseLayer('b')];
    const { toAdd, toRemove } = diffLayers(next, prev);
    expect(toAdd).toHaveLength(1);
    expect(toAdd[0].id).toBe('b');
    expect(toRemove).toHaveLength(0);
  });

  it('detects removed layers', () => {
    const prev = [baseLayer('a'), baseLayer('b')];
    const next = [baseLayer('a')];
    const { toAdd, toRemove } = diffLayers(next, prev);
    expect(toAdd).toHaveLength(0);
    expect(toRemove).toEqual(['b']);
  });

  it('handles add and remove simultaneously', () => {
    const prev = [baseLayer('a'), baseLayer('b')];
    const next = [baseLayer('b'), baseLayer('c')];
    const { toAdd, toRemove } = diffLayers(next, prev);
    expect(toAdd).toHaveLength(1);
    expect(toAdd[0].id).toBe('c');
    expect(toRemove).toEqual(['a']);
  });

  it('returns remaining layers', () => {
    const next = [baseLayer('a'), baseLayer('b')];
    const { remaining } = diffLayers(next, []);
    expect(remaining).toHaveLength(2);
    expect(remaining[0].id).toBe('a');
  });
});
