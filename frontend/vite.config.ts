import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.REVRANK_API_URL || 'http://127.0.0.1:8000',
        changeOrigin: true,
        // The bundled proxy only drops the upstream request on 'aborted', which Node stops emitting
        // once the request body has arrived. Without this, a cancelled or timed-out compare leaves
        // the API working on a request nobody is waiting for.
        configure(proxy) {
          proxy.on('proxyReq', (proxyReq, _request, response) => {
            // A response closing before it was written means the browser left, not that we answered.
            response.on('close', () => { if (!response.writableEnded) proxyReq.destroy(); });
          });
        },
      },
    },
  },
});
