import { defineConfig } from 'vite'
import { resolve } from 'path'

export default defineConfig({
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
