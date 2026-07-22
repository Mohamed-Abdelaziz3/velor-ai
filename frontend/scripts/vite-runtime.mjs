import { fileURLToPath } from 'node:url'
import { loadEnv } from 'vite'

export const frontendDir = fileURLToPath(new URL('../', import.meta.url))

export const resolveApiProxyTarget = (env) =>
  env.VITE_API_BASE || env.VITE_API_URL || 'http://localhost:8000'

export const createViteOptions = async (mode = 'development') => {
  const { default: react } = await import('@vitejs/plugin-react')
  const env = loadEnv(mode, frontendDir, '')

  return {
    root: frontendDir,
    configFile: false,
    envDir: frontendDir,
    plugins: [react()],
    server: {
      fs: {
        strict: true,
        allow: [frontendDir],
      },
      proxy: {
        '/api': {
          target: resolveApiProxyTarget(env),
          changeOrigin: true,
        },
      },
    },
    optimizeDeps: {
      include: [
        'react',
        'react-dom',
        'react-dom/client',
        'react-router-dom',
        '@react-oauth/google',
        'axios',
        'framer-motion',
        'lucide-react',
        'react-hot-toast',
        'react-icons',
      ],
    },
    build: {
      sourcemap: false,
      minify: 'terser',
      chunkSizeWarningLimit: 1000,
    },
  }
}
