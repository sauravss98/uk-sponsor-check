import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // The dev server proxies /api to the FastAPI backend (`sponsor-check-api`), so the
      // frontend never needs to know the API's host in dev. In production the app is built
      // as static files and served behind whatever reverse-proxies /api the same way.
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
