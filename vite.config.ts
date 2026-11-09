import { defineConfig, type Plugin } from 'vite'
import { readFileSync } from 'fs'
import { createRequire } from 'module'
import { resolve } from 'path'

const require = createRequire(import.meta.url)

/**
 * MapLibre v6 loads its worker as a separate ES module, from
 * `./maplibre-gl-worker.mjs` relative to the module that contains MapLibre —
 * here the served brew-gis-map.js. The worker file is self-contained, so it is
 * copied next to the bundle unchanged.
 */
function maplibreWorker(): Plugin {
  return {
    name: 'maplibre-worker',
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'maplibre-gl-worker.mjs',
        source: readFileSync(require.resolve('maplibre-gl/dist/maplibre-gl-worker.mjs')),
      })
    },
  }
}

export default defineConfig({
  plugins: [maplibreWorker()],
  build: {
    lib: {
      entry: resolve(__dirname, 'js/src/index.ts'),
      name: 'BrewGisMap',
      formats: ['es'],
      fileName: () => 'brew-gis-map.js',
    },
    outDir: resolve(__dirname, 'brewgis/static/js'),
    emptyOutDir: false,
    sourcemap: true,
    rollupOptions: {
      external: [],
      output: {
        inlineDynamicImports: true,
      },
    },
  },
})
