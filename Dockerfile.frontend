# ---- build stage ----
FROM node:22-alpine AS builder

WORKDIR /app

# Install deps first for layer caching.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci || npm install

# Build the Next.js app (produces .next/standalone via output: 'standalone').
COPY frontend/ ./
RUN npm run build

# ---- runtime stage ----
FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# Standalone server bundle + static assets.
# (No public/ copy: the app has no static public assets — the favicon lives in
# app/favicon.ico and is served from the build output. Add a COPY here if a
# public/ asset is ever introduced.)
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000

CMD ["node", "server.js"]
