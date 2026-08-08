import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  define: {
    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
    __FRONTEND_VERSION__: JSON.stringify('topic2-frontend-v2.0.5'),
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ['echarts', 'echarts-for-react'],
          react: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api/v1': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
      '/agent-api': {
        target: 'http://127.0.0.1:8011',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/agent-api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
    css: false,
  },
})
