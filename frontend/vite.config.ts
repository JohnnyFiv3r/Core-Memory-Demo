import { defineConfig } from 'vite'
import { resolve } from 'node:path'

export default defineConfig({
  server: {
    port: 5173,
  },
  // Force a single three.js instance so reagraph's scene and the bloom
  // post-processing composer share the same renderer/scene graph.
  resolve: {
    dedupe: ['three', '@react-three/fiber', '@react-three/postprocessing'],
  },
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        graph: resolve(__dirname, 'graph.html'),
      },
    },
  },
})
