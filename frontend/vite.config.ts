// filepath: /workspaces/batterymanager/frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './', // Use relative paths instead of absolute paths for assets
  server: {
    host: '0.0.0.0', // Allow connections from outside the container
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://bess-dev:8080', // Direct reference to the container name
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path
      }
    }
  },
  build: {
    outDir: 'dist',
    rollupOptions: {
      input: {
        main: './index.html'
      },
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'], // Example: Split vendor libraries
        }
      }      
    }
  }
})