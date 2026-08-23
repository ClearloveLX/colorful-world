import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    // three.js 随主包一起打包（锁屏首屏即用，避免懒加载二次等待）
    chunkSizeWarningLimit: 900,
  },
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
