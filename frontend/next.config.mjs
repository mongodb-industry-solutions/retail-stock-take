/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emit a minimal standalone server bundle for small, env-configurable
  // container images (Dockerfile.frontend runtime stage runs `node server.js`).
  output: 'standalone',

  transpilePackages: ['@powersync/web', '@powersync/react'],

  // Same-origin /api/* proxy is handled by app/api/[...path]/route.js at
  // request time. next.config.mjs rewrites() run at build time — BACKEND_URL
  // isn't set during docker build, so they would bake in the wrong URL.

  // wa-sqlite needs OPFS, which requires cross-origin isolation.
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'Cross-Origin-Opener-Policy', value: 'same-origin' },
          { key: 'Cross-Origin-Embedder-Policy', value: 'require-corp' },
        ],
      },
    ];
  },

  webpack: (config) => {
    config.resolve.fallback = { ...config.resolve.fallback, crypto: false };
    return config;
  },
};

export default nextConfig;
