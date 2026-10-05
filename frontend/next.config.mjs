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

  // Next 16 defaults to Turbopack. The old webpack crypto:false fallback
  // (defensive, no app source imports node:crypto) isn't needed under
  // Turbopack; an empty turbopack config enables the default bundler cleanly.
  turbopack: {},
};

export default nextConfig;
