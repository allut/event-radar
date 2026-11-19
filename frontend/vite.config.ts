import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 127.0.0.1, not localhost: uvicorn binds IPv4-only by default and the proxy
// would otherwise hit the same ::1 resolution trap noted below for the dev
// server's own bind address.
const BACKEND_TARGET = 'http://127.0.0.1:8000';

// `vite preview`'s target during the prerender build step (scripts/prerender.ts) —
// there's no dev server proxy at that point, so the built SPA's same-origin
// `/api` fetches need a real backend to hit. Defaults to the same Render origin
// functions/api/[[path]].ts's proxy already points at in production;
// overridable via env for a local dry run against a different backend.
// Exported (not just used below) so scripts/prerender.ts's own direct
// `fetch()` calls to the backend share this exact value instead of
// redeclaring the same literal a second place to keep in sync by hand.
export const PRERENDER_BACKEND_TARGET = process.env.PRERENDER_API_ORIGIN ?? 'https://event-radar-api-r7l6.onrender.com';

export default defineConfig({
  plugins: [react()],
  server: {
    // Bind IPv4 loopback explicitly. Vite's default `localhost` resolves to ::1
    // first under Node's verbatim DNS order, so the listener can end up IPv6-only
    // while a port forwarder dials 127.0.0.1 and gets every connection refused
    // even though Vite prints "ready".
    host: '127.0.0.1',
    // strictPort: fail rather than silently drifting to 5174, which a port
    // forwarder pinned to 5173 would miss.
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: BACKEND_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      // Dev-only docs (Swagger, ReDoc, the raw spec): proxied so they're
      // same-origin with the SPA and the session cookie (Path=/api, belongs
      // to :5173) rides along automatically.
      '/docs': {
        target: BACKEND_TARGET,
        changeOrigin: true,
      },
      '/redoc': {
        target: BACKEND_TARGET,
        changeOrigin: true,
      },
      '/openapi.json': {
        target: BACKEND_TARGET,
        changeOrigin: true,
      },
    },
  },
  preview: {
    // Mirrors `server.proxy`'s `/api` rewrite so scripts/prerender.ts's
    // `vite preview` instance (serving the built dist/ for Playwright to
    // navigate) can resolve the same-origin `/api` fetches the SPA makes —
    // against the real backend, not localhost:8000.
    proxy: {
      '/api': {
        target: PRERENDER_BACKEND_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
});
