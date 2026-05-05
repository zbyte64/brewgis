import type { LayerConfig } from '../types/index.js';

let idCounter = 0;

/**
 * Generate a unique layer ID, preferring the provided id or deriving from key.
 */
export function generateLayerId(layer: LayerConfig, index: number): string {
  if (layer.id) return layer.id;
  return `${layer.key}-${index}-${++idCounter}`;
}

/**
 * Validate that layer IDs in a list are unique.
 * Returns an array of invalid (duplicate) IDs.
 */
export function validateLayerIds(layers: LayerConfig[]): string[] {
  const seen = new Map<string, number>();
  const duplicates: string[] = [];

  for (const layer of layers) {
    if (layer.id) {
      if (seen.has(layer.id)) {
        duplicates.push(layer.id);
      }
      seen.set(layer.id, (seen.get(layer.id) ?? 0) + 1);
    }
  }

  return duplicates;
}

export interface LayerDiff {
  toAdd: LayerConfig[];
  toRemove: string[];
  remaining: LayerConfig[];
}

/**
 * Diff two arrays of LayerConfig by resolved ID.
 * Returns layers to add, IDs to remove, and remaining layers.
 */
export function diffLayers(
  next: LayerConfig[],
  prev: LayerConfig[],
): LayerDiff {
  const resolvedNext = next.map((l, i) => ({ ...l, id: generateLayerId(l, i) }));
  const resolvedPrev = prev.map((l, i) => ({ ...l, id: generateLayerId(l, i) }));

  const prevIds = new Set(resolvedPrev.map((l) => l.id!));
  const nextIds = new Set(resolvedNext.map((l) => l.id!));

  const toAdd = resolvedNext.filter((l) => !prevIds.has(l.id!));
  const toRemove = [...prevIds].filter((id) => !nextIds.has(id));

  return { toAdd, toRemove, remaining: resolvedNext };
}
