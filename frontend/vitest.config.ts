/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        // Node 26 exposes an experimental global localStorage (undefined
        // without --localstorage-file) that shadows jsdom's implementation.
        // Setting a URL activates jsdom's storage APIs so they win.
        url: 'http://localhost',
      },
    },
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
  },
})
