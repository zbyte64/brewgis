import { BrewGisMap } from './components/brew-gis-map.js';

// Register the custom element
if (!customElements.get('brew-gis-map')) {
  customElements.define('brew-gis-map', BrewGisMap);
}

export { BrewGisMap };
