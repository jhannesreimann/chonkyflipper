import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'

// The dev server proxies /api to the Flask backend so the dashboard talks to
// real hardware without CORS headaches.  Default points at localhost (run the
// backend locally for pure-UI work).  Set CHONKY_API to reach a remote Pi:
//
//   CHONKY_API=http://192.168.178.78 npm run dev
const PI_API = process.env.CHONKY_API || 'http://localhost:5000'

export default defineConfig({
  plugins: [tailwindcss()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        target: PI_API,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
