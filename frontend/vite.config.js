import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      // API endpoints — JSON REST layer
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      // Static files (uploads, img, css, js)
      '/static': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      // AI assistant page
      '/assistant': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      // Flask report-issue HTML form (used by the "Report an issue" button)
      '/report-issue': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      // Auth routes — needed when the user follows a Flask link while in dev mode
      '/login': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/logout': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
      '/register': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  build: {
    // Output relative to frontend/ directory
    outDir: 'dist',
    emptyOutDir: true,
  },
});