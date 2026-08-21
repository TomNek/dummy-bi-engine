import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  root: path.resolve(__dirname, 'open-core'),
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      buffer: 'buffer',
    },
  },
  optimizeDeps: { include: ['buffer'] },
  server: {
    port: 5174,
    proxy: {
      '/runtime': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: path.resolve(__dirname, 'dist'),
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          plotly: ['plotly.js-dist-min', 'react-plotly.js'],
        },
      },
    },
  },
})
