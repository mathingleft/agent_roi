import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  server: {
    fs: {
      allow: ['..'],
    },
    watch: {
      usePolling: false,
      ignored: ['**/.git/**', '**/node_modules/**'],
    },
  },
})
