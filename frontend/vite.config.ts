import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const apiTarget =
  (globalThis as { process?: { env?: Record<string, string | undefined> } }).process
    ?.env?.DEEPTUTOR_API_BASE_URL || 'http://127.0.0.1:8001'

const proxy = {
  '/api': {
    target: apiTarget,
    changeOrigin: true,
    ws: true,
  },
  '/ws': {
    target: apiTarget,
    changeOrigin: true,
    ws: true,
  },
  '/auth/callback': {
    target: apiTarget,
    changeOrigin: true,
    rewrite: () => '/api/v1/auth/openai-codex/callback',
  },
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy,
  },
  preview: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy,
  },
})
