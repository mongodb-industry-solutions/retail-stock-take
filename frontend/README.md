# Frontend — retail-stock-take web client

Next.js 15 (App Router, **JavaScript** — not TypeScript) + LeafyGreen + Tailwind 4.
It's a real **PowerSync** web client: it renders shelf inventory from a local
SQLite database that PowerSync keeps in sync with MongoDB, and it works offline.

For the project overview see [`../README.md`](../README.md); to run the whole
stack locally see [`../RUN_LOCAL.md`](../RUN_LOCAL.md).

## How it fits together

- **PowerSync client.** The synced schema lives in
  [`lib/powersync/schema.js`](lib/powersync/schema.js) — the single source of
  truth (Phase 2 mobile re-shares it). The browser reads inventory from local
  SQLite (`@journeyapps/wa-sqlite`) backed by **OPFS**, so reads survive offline.
- **OPFS needs cross-origin isolation.** `next.config.mjs` sets
  `Cross-Origin-Opener-Policy: same-origin` and
  `Cross-Origin-Embedder-Policy: require-corp`. Don't remove them or wa-sqlite
  won't persist.
- **Same-origin API proxy.** The browser only ever talks to the frontend origin.
  `/api/*` is proxied to the backend by a **runtime Route Handler** at
  [`app/api/[...path]/route.js`](app/api/[...path]/route.js), which reads
  `BACKEND_URL` **at request time**. (We do *not* use `next.config.mjs` rewrites:
  those bake the target at build time, which breaks the no-`NEXT_PUBLIC_*` rule
  and the one-image-per-environment goal.) The PowerSync WebSocket URL is likewise
  delivered at runtime by `/api/auth/token`.
- **Writes don't use the PowerSync upload queue.** Photo capture POSTs multipart
  to `POST /api/inventory/capture`; the backend runs CV, stores the frame, and
  writes MongoDB. The change stream then syncs the new row back down.

## Layout

```
app/                 App Router: layout.js, page.js, providers.js
  api/[...path]/route.js   runtime proxy to BACKEND_URL
components/          feature folders: capture/, inventory/, debug/ (+ sibling hooks)
lib/powersync/       schema.js (AppSchema) + client setup
```

## Local dev

Normally you run the frontend **inside the kind cluster** via `./scripts/setup.sh`
(it builds `Dockerfile.frontend`, `output: 'standalone'`, and serves it behind the
ingress at http://frontend.localtest.me).

To iterate on the UI alone against an already-running backend:

```bash
npm install
BACKEND_URL=http://localhost:8000 npm run dev   # http://localhost:3000
```

(You need the backend reachable at `BACKEND_URL` for `/api/*` and PowerSync to work.)
