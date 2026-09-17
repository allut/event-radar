import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    environmentOptions: {
      jsdom: {
        url: 'http://localhost/',
      },
    },
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // The Tiptap-mounting cases in EventSubmit.test.tsx blow past the 5s
    // default under load — 13/13 pass at 30s, reproduced flaky-then-stable
    // across two separate runs at the default.
    testTimeout: 30000,
    env: {
      TZ: 'UTC',
    },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/**', 'scripts/**', 'functions/**', 'api/**'],
      exclude: [
        'src/_generated/**',
        'src/**/*.module.css',
        'src/main.tsx',
        'src/**/index.ts',
      ],
    },
  },
});
