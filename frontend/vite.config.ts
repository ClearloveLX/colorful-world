import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 4398,
    strictPort: true,
    open: false,
    proxy: {
      '/api': {
        target: 'http://localhost:4396',
        changeOrigin: true,
      }
    }
  }
})
