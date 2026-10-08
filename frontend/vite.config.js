import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 开发模式下 /api 代理到后端服务（8003，避免与本机其他服务冲突）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8003', changeOrigin: true },
    },
  },
  build: { outDir: 'dist' },
})
