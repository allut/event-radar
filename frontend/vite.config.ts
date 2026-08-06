import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    // Bind IPv4 loopback explicitly. Vite's default `localhost` resolves to ::1
    // first under Node's verbatim DNS order, so in the dev container the listener
    // ends up IPv6-only while VS Code's port forwarder dials 127.0.0.1 -> the
    // forwarded port refuses every connection even though Vite prints "ready".
    host: '127.0.0.1',
    // strictPort: 5173 is the only dev port .devcontainer forwards; without this
    // Vite silently drifts to 5174 and the forward is dead again.
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        // 127.0.0.1, not localhost: uvicorn binds IPv4-only by default and this
        // proxy would otherwise hit the same ::1 resolution trap.
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
});
