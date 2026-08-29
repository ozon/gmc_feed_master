import { defineConfig } from 'vitest/config';
import { loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export default defineConfig(({ mode }) => {
  const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
  const env = loadEnv(mode, rootDir, '');
  const certPath = env.VITE_HTTPS_CERT?.trim();
  const keyPath = env.VITE_HTTPS_KEY?.trim();

  if (Boolean(certPath) !== Boolean(keyPath)) {
    throw new Error('VITE_HTTPS_CERT and VITE_HTTPS_KEY must be set together');
  }

  return {
    plugins: [react()],
    server: {
      ...(certPath && keyPath
        ? {
            https: {
              cert: readFileSync(resolve(rootDir, certPath)),
              key: readFileSync(resolve(rootDir, keyPath)),
            },
          }
        : {}),
      proxy: {
        '/auth': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/health': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/clients': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/feed-sources': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/dashboard': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/plugins': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/registry': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
        '/export': {
          target: 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      globals: true,
    },
  };
});
