import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, forward /api to the FastAPI backend so the browser never hits CORS.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': { target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true } } },
  preview: { proxy: { '/api': { target: process.env.VITE_PROXY_TARGET || 'http://localhost:8000', changeOrigin: true } } },
})
