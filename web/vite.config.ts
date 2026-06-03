import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// When PUBLIC_TUNNEL=1 (e.g. running behind cloudflared / ngrok), point the
// HMR websocket at wss://<host>:443 so the browser can reach it through the
// tunnel. Otherwise leave HMR on its default (ws://localhost:3000) which is
// what local dev expects.
const tunnelMode = process.env.PUBLIC_TUNNEL === '1';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: true, // bind 0.0.0.0 so LAN / cloudflared tunnel can reach us
    port: 3000,
    // Accept any Host header (e.g. *.trycloudflare.com) without rejecting.
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/artifacts': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
    hmr: tunnelMode
      ? { clientPort: 443, protocol: 'wss' }
      : undefined,
  },
});
