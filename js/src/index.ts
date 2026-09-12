import { BrewGisMap } from './components/brew-gis-map.js'
import { FilterBuilder } from './components/filter-builder.js'
import { PaintModeController } from './components/paint-mode.js'

// Register the custom elements
if (!customElements.get('brew-gis-map')) {
  customElements.define('brew-gis-map', BrewGisMap)
}
if (!customElements.get('filter-builder')) {
  customElements.define('filter-builder', FilterBuilder)
}

export { BrewGisMap, FilterBuilder, PaintModeController }
export type { FeatureSelectedEvent, PaintRequest } from './types/index.js'
