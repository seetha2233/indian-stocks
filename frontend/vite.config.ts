import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // FastAPI backend: uvicorn app.main:app --reload (port 8000)
    proxy: { '/api': 'http://localhost:8000' },
  },
})
