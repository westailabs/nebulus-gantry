import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    allowedHosts: ['nebulus', 'nebulus.local'],
    proxy: {
      // Override with GANTRY_API_PROXY (e.g. http://localhost:<backend-port>) for native installs.
      '/api': process.env.GANTRY_API_PROXY || 'http://172.17.0.1:8000',
    },
  },
})
