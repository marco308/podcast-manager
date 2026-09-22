import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import fs from 'fs';
import path from 'path';

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // Check if SSL certificates exist for HTTPS in development
  const certPath = path.resolve(__dirname, '../backend/certs/localhost+2.pem');
  const keyPath = path.resolve(__dirname, '../backend/certs/localhost+2-key.pem');
  const hasSSL = fs.existsSync(certPath) && fs.existsSync(keyPath);

  return {
    plugins: [react()],
    server: {
      port: 3000,
      // Enable HTTPS in development if certificates exist
      ...(mode === 'development' && hasSSL
        ? {
            https: {
              cert: fs.readFileSync(certPath),
              key: fs.readFileSync(keyPath),
            },
          }
        : {}),
      // Proxy API requests to backend
      proxy: {
        '/api': {
          target: 'https://127.0.0.1:8000',
          changeOrigin: true,
          secure: false, // Allow self-signed certificates
        },
      },
    },
    build: {
      outDir: 'dist',
      // Source maps in dev only — they're a source-code disclosure risk in prod.
      sourcemap: mode !== 'production',
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
  };
});
