// filepath: /workspaces/batterymanager/frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: './', // Use relative paths instead of absolute paths for assets
  server: {
    host: '0.0.0.0', // Allow connections from outside the container
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://bess-dev:8080', // Direct reference to the container name
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path
      }
    }
  },
  optimizeDeps: {
    // Pre-bundle these dependencies to avoid re-optimization
    include: [
      'react',
      'react-dom',
      'react-router-dom',
      'axios',
      'recharts',
      'lucide-react',
      '@radix-ui/react-dialog',
      '@radix-ui/react-label',
      '@radix-ui/react-select',
      '@radix-ui/react-slot',
      '@radix-ui/react-switch',
      '@radix-ui/react-tabs'
    ],
    // Force re-optimization when lockfile changes
    force: false
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500, // Increase chunk size warning limit (in kB)
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