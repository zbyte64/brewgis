import { BrewGisMap } from './components/brew-gis-map.js'
import { PaintModeController } from './components/paint-mode.js'

// Register the custom element
if (!customElements.get('brew-gis-map')) {
  customElements.define('brew-gis-map', BrewGisMap)
}

export { BrewGisMap, PaintModeController }
export type { FeatureSelectedEvent, PaintRequest } from './types/index.js'
