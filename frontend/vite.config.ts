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
  const allowedHosts = (env.VITE_ALLOWED_HOSTS?.trim() || 'localhost')
    .split(',')
    .map((host) => host.trim())
    .filter(Boolean);
  const apiTarget = env.VITE_API_TARGET?.trim() || 'http://127.0.0.1:8000';

  if (Boolean(certPath) !== Boolean(keyPath)) {
    throw new Error('VITE_HTTPS_CERT and VITE_HTTPS_KEY must be set together');
  }

  return {
    plugins: [react()],
    build: {
      // vendor chunking: stable caches for framework code
      rolldownOptions: {
        output: {
          codeSplitting: {
            groups: [
              { name: 'vendor-react', test: /node_modules[\\/]react(-dom|-router)?[\\/]/, priority: 20 },
              { name: 'vendor-mantine', test: /node_modules[\\/]@mantine[\\/]/, priority: 15 },
              { name: 'vendor', test: /node_modules/, priority: 10 },
            ],
          },
        },
      },
    },
    server: {
      allowedHosts,
      ...(certPath && keyPath
        ? {
            https: {
              cert: readFileSync(resolve(rootDir, certPath)),
              key: readFileSync(resolve(rootDir, keyPath)),
            },
          }
        : {}),
      proxy: {
        '/admin': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/auth': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/health': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/clients': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/feed-sources': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/dashboard': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/plugins': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/registry': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/export': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/logs': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/chat': {
          target: apiTarget,
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
