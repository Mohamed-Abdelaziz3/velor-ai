import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

const frontendDir = fileURLToPath(new URL('.', import.meta.url))

export const resolveApiProxyTarget = (env) =>
  env.VITE_API_BASE || env.VITE_API_URL || 'http://localhost:8000'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, frontendDir, '')

  return {
    envDir: frontendDir,
    plugins: [react()],
    server: {
      fs: {
        strict: true,
        allow: ['.']
      },
      proxy: {
        '/api': {
          target: resolveApiProxyTarget(env),
          changeOrigin: true,
        }
      }
    },
    build: {
      sourcemap: false,
      minify: 'terser',
      chunkSizeWarningLimit: 1000,
    }
  }
})
