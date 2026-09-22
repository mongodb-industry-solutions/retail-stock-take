# retail-stock-take — Claude context

MongoDB ↔ PowerSync demo for **disconnected retail field-work**: web/mobile
client photographs a shelf, the backend runs a CV model to produce a structured
JSON inventory, the **raw frame is persisted to S3-compatible object storage**,
MongoDB stores the inventory + an asset reference, and PowerSync syncs it to
every connected client (including offline ones).

Phase 1 = local web stack + CV pipeline + PowerSync end-to-end from the browser.
Phase 2 = React Native mobile client + true offline capture.

Built on top of the Industry Solutions demo template
(FastAPI/uv + Next.js 16 + LeafyGreen + Tailwind 4). **Local runs on Kubernetes
(kind); cloud deploys to Kanopy via the existing Drone pipelines.**

## Two deployment targets, one codebase (config-only switch)

- **Local = kind.** Full self-hosted stack in-cluster: MongoDB **Enterprise**
  replica set + **`mongot` Search nodes** (via the **MCK operator**, managed by
  **self-hosted Ops Manager** — fully air-gapped, no external cloud dependency),
  **SeaweedFS** (S3), self-hosted **PowerSync**, backend, frontend.
- **Cloud = Kanopy** (Drone, separate-pods). MongoDB→**Atlas** (native Vector
  Search), object storage→**AWS S3** (IRSA, no static keys), PowerSync→
  **self-hosted as a 3rd `mongodb/web-app` release**.
- Migration is **configuration only**: the storage adapter and the Mongo URI
  switch backends by env; business logic is identical. MongoDB = metadata plane,
  S3-compatible store = blob plane.

## Architecture (local, kind)

```
Browser ── http://localhost (ingress-nginx; must be the literal "localhost"
   │        hostname, not frontend.localtest.me — Chrome only treats
   │        localhost/127.0.0.1/https:// as a secure context, and PowerSync's
   │        wa-sqlite/OPFS needs the Web Locks API, which is secure-context-only)
   │  same-origin /api/* ── Next.js proxy ──▶ backend (internal Service, no ingress)
   │  WebSocket ── http://powersync.localtest.me ──▶ PowerSync
   ▼
backend (FastAPI)  ── /api/auth/{token,keys}, /api/inventory/capture, /api/health
   │  ├─ put raw frame ─▶ SeaweedFS (S3 gateway, in-cluster)
   │  └─ insert metadata + asset ref ─▶ MongoDB
PowerSync ── change streams (pre/post images) ─▶ WebSocket push ─▶ browser SQLite
MongoDB Enterprise RS + mongot Search (MCK operator, Ops Manager managed — in-cluster)
Ollama IN-CLUSTER (Moondream primary; Qwen2.5-VL 7B optional) — ClusterIP Service
  `ollama:11434`, models on 10 Gi PVC (no host Ollama needed)
```

Capture flow (idempotent, retry-safe): browser → POST `/api/inventory/capture`
(multipart, via the frontend proxy) → CV (Ollama) → insert doc `status=PENDING_UPLOAD`
with embedded `asset` ref + deterministic key → `put_object` to S3 → update
`status=ACTIVE` (+size+checksum) → change stream → PowerSync → browser re-renders.
A retention reconciler promotes/expires docs and deletes objects past `expires_at`.

## Locked decisions (don't change without re-planning)

- **Local = kind, cloud = Kanopy.** (Docker Compose is retired.)
- Local MongoDB = **Enterprise replica set** via the **MCK operator**,
  **self-hosted Ops Manager**-managed (fully in-cluster, no external cloud
  dependency). Local runs **8.0.9-ent** because Ops Manager 8.0 only supports
  8.0.x. `MongoDBSearch`/Vector Search is **Preview and DEFERRED** locally (needs
  8.2+); the CR is applied but won't run until Ops Manager is upgraded. Live-cluster
  facts: API key Secret is `mongodb-ops-manager-admin-key`, Service is
  `ops-manager-svc`, status jsonpath `{.status.opsManager.phase}` /
  `{.status.applicationDatabase.phase}`.
- **Always-on host access** (no port-forward): kind `extraPortMappings` publish host
  27017→MongoDB, 8080→Ops Manager, 8333→S3, backed by NodePort Services in
  `infra/k8s/access/` (+ seaweedfs.yaml). Mappings are fixed at cluster creation, so
  changing them needs `make reset && make setup`. Compass uses `directConnection=true`
  against pinned pod `retail-mongodb-0`.
- Cloud MongoDB = **Atlas**. Cloud object storage = **AWS S3** (IRSA), **ON**:
  frames go to the shared `industry-solutions-demos` bucket under
  `industry/mobile/retail-stock-take/uploads/` (`STORAGE_UPLOAD_PREFIX`),
  retained **3 months** (`RETENTION_DAYS=90`), then the reconciler deletes the
  object **and** the doc. A curated `sample-shelves/` prefix is served read-only
  via `/api/sample-shelves` (image bytes proxied to the browser). Local
  always uses SeaweedFS (photos on).
- **Object storage is vendor-agnostic** behind one `boto3` S3 adapter
  (`backend/storage/`). Use only the common S3 subset (Put/Get/Head/Delete/
  ListV2 + presign). **Never** depend on SeaweedFS-/MinIO-native or admin APIs.
  Local = SeaweedFS endpoint + path-style + static keys; cloud = AWS S3 + IRSA.
  `STORAGE_PROVIDER=none` disables the store entirely (`storage_enabled()` gates
  capture/reconciler/health/startup; capture then writes `asset: null`, ACTIVE).
- **Photos are persisted when storage is on** (reverses the old "ephemeral"
  rule). MongoDB stores metadata + an `asset` reference; the bytes live in
  object storage. With `STORAGE_PROVIDER=none` the frame is not stored and
  `asset` is null. `crops/` keys are reserved for a future detection pass.
- **Idempotent write FSM**: `PENDING_UPLOAD → ACTIVE`; on expiry the reconciler
  **deletes the object and the doc** (no `DELETED` tombstone persists). Retention is
  enforced by a **reconciler** (`backend/retention/`), NOT by bucket lifecycle.
- Same Mongo cluster for source + PowerSync bucket storage, **distinct DBs**:
  `retail_demo` (source) vs `powersync` (bucket).
- `post_images: auto_configure` in `powersync.yaml`; the post-init Job
  (`infra/k8s/mongodb/40-postinit-job.yaml`) also enables
  `changeStreamPreAndPostImages` (FastAPI startup asserts it).
- Sync rules **edition 3** (`streams:`). Single `global_inventory` stream,
  `auto_subscribe: true`. Projects `_id AS id` and includes `status`.
- Auth: **RS256 JWTs via JWKS URI** (PowerSync trusts `/api/auth/keys`).
  Claims: `sub`, `iat`, `exp`, `aud="powersync"`, `iss="retail-stock-take"`.
- **No `NEXT_PUBLIC_*`.** The browser only talks to the frontend origin; Next.js
  proxies `/api/*` to the backend at runtime (`BACKEND_URL`), and the PowerSync
  WebSocket URL is delivered at runtime by `/api/auth/token` (`POWERSYNC_PUBLIC_URL`).
- Web app is a real PowerSync client; it does NOT write via the SDK upload queue
  (photo uploads go to `/api/inventory/capture`).
- MongoDB documents: `_id` is a UUID **string** (not ObjectId).
- **CV provider is config-selected** via `CV_PROVIDER` (`backend/cv/__init__.py`):
  local = **Ollama** (in-cluster), cloud = **Grove** (MongoDB's GenAI gateway —
  OpenAI-compatible + vision, `api-key` header). Both share the
  `analyze_shelf_image(bytes, model, fallback) -> (CVResponse, str)` contract and
  a unified `CVError`. Cloud default `GROVE_MODEL=gpt-5.5`, fallback `gpt-4o`
  (env-overridable); `GROVE_API_KEY` from `retail-stock-take`. Add a new
  provider = new `cv/<name>_client.py` + a branch in `cv/__init__.py`.

## Tech stack (pinned)

- Operator: MCK `mck/mongodb-kubernetes` ~1.8.1 (helm repo alias `mck` → `https://mongodb.github.io/helm-charts`; CRDs `MongoDB`,
  `MongoDBUser`, `MongoDBSearch`, all `mongodb.com/v1`).
- MongoDB Enterprise **8.0.9-ent** locally (Ops Manager 8.0 ceiling). 8.2.x-ent +
  `mongot` ~0.64.0 is the target for Search, deferred until Ops Manager is upgraded.
- PowerSync: `journeyapps/powersync-service:1.21.0`
- SeaweedFS: `chrislusf/seaweedfs` (all-in-one `weed server -s3`)
- Kanopy chart: `mongodb/web-app` 4.30.0 (Service is `<release>-web-app-80`)
- Node 22, Python 3.13, Next.js 16 / React 19 (App Router, **JS not TS**)
- LeafyGreen UI + Tailwind 4
- `@powersync/web` ^1.20, `@powersync/react` ^1.5.2, `@journeyapps/wa-sqlite` ^1.2.6
- FastAPI 0.115+, `pyjwt[crypto]` 2.10+, `httpx` 0.27+, `boto3` 1.35+

## Conventions

- Repo layout: **`backend/` + `frontend/` at root** (no npm workspace). Each has its
  own `Dockerfile` (`backend/Dockerfile`, `frontend/Dockerfile` — what Drone expects).
- **Single source of truth for the sync schema: `frontend/lib/powersync/schema.js`.**
  When you change a synced column, update three places in lockstep: this schema,
  `powersync/sync-rules.yaml`, and the writer in `backend/api/inventory.py`.
- Storage access goes through `backend/storage/get_storage_adapter()` only.
- Config: env-driven. `.env.example` documents the contract; local cluster values
  live in `infra/local/*.yaml`, cloud (Kanopy) values in `environment/*.yaml`
  (a shared base + per-service file). PowerSync needs `PS_*` vars for `!env`.
- Backend split: routes in `backend/api/`, CV in `backend/cv/`, storage in
  `backend/storage/`, retention in `backend/retention/`, DB connector in
  `backend/db/mdb.py`.
- Frontend split: feature-folder components (`capture/`, `inventory/`, `debug/`)
  with sibling hooks; same-origin `/api/*` proxy is a **runtime Route Handler**
  (`frontend/app/api/[...path]/route.js`) reading `BACKEND_URL` per-request — NOT
  `next.config.mjs` rewrites (those bake at build time and broke the no-`NEXT_PUBLIC_*`
  rule).
- COOP/COEP headers in `frontend/next.config.mjs` — needed for OPFS persistence
  of wa-sqlite. Don't remove. Frontend builds `output: 'standalone'`.
- `.env.example` lives at root (note: the harness blocks direct `.env*` writes — use `mv` or have the user rename it).
- Kanopy/Drone is live: `.drone.yml` (separate pods, 3 releases) + `environment/`.
  Cloud needs manual prereqs: Atlas + the k8s secrets/configmap + the Drone CI
  secrets (see `.drone.yml` header and `docs/KANOPY_DEPLOYMENT_README.md`).

## Key commands

| | |
|---|---|
| `./scripts/setup.sh` | one-shot kind bring-up (no external account; prints access details) |
| `make status` | `kubectl -n retail get pods,svc,ingress` |
| `make logs` | tail app pod logs |
| `./scripts/verify.sh` | end-to-end smoke test |
| `./scripts/reset.sh` | delete the kind cluster |
| `kubectl -n retail logs deploy/retail-stock-take-powersync-web-app` | sync debugging |
| `kubectl -n mongodb describe mongodb retail-mongodb` | DB provisioning status |
| `curl -s http://frontend.localtest.me/api/health \| jq` | service health (via proxy) |

URLs/host access (local): app `http://localhost` (use this, not
`frontend.localtest.me` — see Architecture above), PowerSync
`http://powersync.localtest.me`, Ops Manager `http://localhost:8080`, MongoDB
`localhost:27017` (`directConnection=true`), S3 `http://localhost:8333`. Backend is
internal-only. `scripts/lib.sh` holds shared color/spinner helpers for all scripts.

## Don't

- Don't depend on provider-specific object-store behavior (folder semantics,
  bucket notifications/replication, lifecycle/transition tiers). Common S3 only.
- Don't reintroduce `NEXT_PUBLIC_*` — it bakes at build time and breaks Kanopy.
  Use the runtime proxy + `/api/auth/token` for the PowerSync URL.
- Don't add ObjectId to synced collections — the `_id AS id` projection assumes
  a string `_id`. Use `str(uuid.uuid4())`.
- Don't change the JWT `aud` claim without updating both `backend/api/auth.py`
  AND `powersync/powersync.yaml`. Silent 401s if mismatched.
- Don't move the `Dockerfile`s out of `backend/` / `frontend/` — their paths are
  referenced in `.drone.yml`, `scripts/setup.sh`, and docs.
- Don't rely on bucket lifecycle for retention — the reconciler is the source of
  truth.
- Don't move the PowerSync config files; they're mounted at `/config/` (ConfigMap
  `powersync-config`).

## Phase 2 reminders

- The shared `AppSchema` now lives in `frontend/lib/powersync/schema.js` (the
  `packages/schema` workspace was folded in). Phase 2 mobile re-shares it from there.
- Auth contract `/api/auth/token` + `/api/auth/keys` is stable; RN client reuses it.
- Upload contract `POST /api/inventory/capture` is stable; mobile holds the photo
  until 201, then deletes.
- Sync is a single global stream; partition by `store_id`/`operator_id` once the
  JWT carries those claims (`store_id` is already stored on each doc).

## Plan reference

Full plan (context, decisions, risk register, verification, implementation order):
`/Users/alberto.camarena/.claude/plans/feel-free-to-ask-bubbly-teapot.md`
