# Architecture

## Goal

Demonstrate MongoDB ↔ PowerSync solving disconnected environments. A retail
worker captures shelf inventory by photo; a CV model turns the photo into
structured data; the raw frame is persisted to S3-compatible object storage; the
inventory data (plus an object reference) syncs across all clients in real time,
including ones returning from offline.

Two deployment targets share one codebase, switched by configuration only:

- **Local** runs entirely on a **kind** cluster (self-hosted, no cloud deps).
- **Cloud** deploys to **Kanopy** via Drone (Atlas + AWS S3 + self-hosted PowerSync).

MongoDB is the **metadata plane**; an S3-compatible store is the **blob plane**.

## Data flow (per capture)

```
Browser ── http://frontend.localtest.me (ingress-nginx)
  │   same-origin /api/*  ── Next.js runtime proxy ──▶ backend (internal Service)
  │   WebSocket           ── http://powersync.localtest.me ──▶ PowerSync
  ▼
backend (FastAPI)
  (1) CV: POST bytes ──▶ Ollama (in-cluster) ──▶ items JSON (Pydantic-validated)
  (2) insert doc status=PENDING_UPLOAD + asset{bucket,key,expires_at,…}  ──▶ MongoDB
  (3) put_object(raw/{store}/{device}/YYYY/MM/DD/HH/{id}.jpg)            ──▶ SeaweedFS/S3
  (4) update doc status=ACTIVE (+size +sha256)                           ──▶ MongoDB
                                   │
        change stream (pre/post images) ─▶ PowerSync ─▶ WebSocket ─▶ browser SQLite
```

1. The browser POSTs the photo to the **frontend origin** (`/api/inventory/capture`);
   Next.js proxies it to the backend at runtime. The browser also calls
   `/api/auth/token`, which returns a JWT **and** the PowerSync WebSocket URL, then
   opens the sync WebSocket directly to PowerSync.
2. The backend runs CV, then writes metadata **first** (`PENDING_UPLOAD`) with an
   embedded `asset` reference and a deterministic object key.
3. It uploads the bytes to object storage via the vendor-agnostic adapter.
4. It promotes the doc to `ACTIVE` with size + checksum, and returns `201`.
5. The MongoDB change stream (with pre/post images) drives PowerSync replication;
   PowerSync pushes the op to every subscribed client; the browser's watched
   query re-renders.

This is **retry-safe**: a crash between steps leaves a reconcilable record. The
retention reconciler (`backend/retention/`) promotes stuck `PENDING_UPLOAD` docs
(or deletes abandoned ones) and **expires** `ACTIVE` docs past `expires_at` by
deleting the object **and** the doc. Retention is enforced by the reconciler,
**not** by bucket lifecycle (kept backend-agnostic).

## Idempotent write FSM

`PENDING_UPLOAD → ACTIVE`; on expiry the reconciler **removes the doc** (no
`DELETED` tombstone persists — the change stream emits a delete op so clients
drop the row). The detailed `asset` sub-document stays server-side until then.

## Services (local kind)

| Component | Image / source | Role |
|---|---|---|
| MCK operator | `mongodb/mongodb-kubernetes` ~1.8.1 | Manages the MongoDB + MongoDBSearch CRs (self-hosted Ops Manager-backed). |
| Ops Manager | `MongoDBOpsManager` (operator) | In-cluster control plane (automation agent) for the Enterprise deployment. |
| MongoDB | Enterprise 8.0.9-ent (operator) | Single-node replica set; source DB + PowerSync bucket DB. |
| mongot (Search) | `MongoDBSearch` ~0.64.0 (**Preview**) | Self-hosted `$vectorSearch` / `$search`. **Deferred** locally — needs MongoDB 8.2+; Ops Manager 8.0 provisions 8.0.9-ent. |
| SeaweedFS | `chrislusf/seaweedfs` (`weed server -s3`) | Local S3 gateway (the AWS S3 stand-in). S3 on :8333, filer UI on :8888 (dev tooling). |
| backend | local `backend/Dockerfile` | FastAPI: auth, health, inventory ingest, storage adapter, reconciler. Internal Service (no ingress). |
| powersync | `journeyapps/powersync-service:1.21.0` | Replication + sync API (unified). Config from a ConfigMap. |
| frontend | local `frontend/Dockerfile` | Next.js (standalone), COOP/COEP headers, `/api/*` proxy. |
| Ollama | `ollama/ollama:latest` | In-cluster VLM server (CPU inference). Moondream primary; qwen2.5vl:7b optional (set OLLAMA_FALLBACK_MODEL). OLLAMA_ORIGINS baked in — no host process needed. Models on a 10 Gi PVC. |

backend / frontend / powersync all deploy through the **same `mongodb/web-app`
Helm chart** used on Kanopy — local (`infra/local/*.yaml`) vs cloud
(`environment/*.yaml`) differ only by values/secrets.

## Vendor-agnostic object storage

`backend/storage/` exposes a thin `StorageAdapter` (Put/Get/Head/Delete/ListV2 +
presign) with a single `boto3` `S3StorageAdapter`. Business logic never touches
provider-native APIs.

- **Local**: SeaweedFS endpoint + path-style + static keys.
- **Cloud**: AWS S3, no endpoint/keys (boto3 default chain → **IRSA**).

Only `STORAGE_*` env differs between environments. Key layout:
`raw/{storeId}/{cameraId}/YYYY/MM/DD/HH/{frameId}.jpg` (`crops/…` reserved for a
future detection pass).

## MongoDB ↔ PowerSync wiring

- Single replica set; **SCRAM auth** (operator-managed users). The source
  collection `retail_demo.inventory_captures` has `changeStreamPreAndPostImages`
  enabled by the post-init Job; `post_images: auto_configure` also enables it.
  The FastAPI startup hook (`db/bootstrap.py`) asserts it.
- `powersync` is a separate DB on the same cluster for bucket storage.
- `client_auth.jwks_uri` points at the backend's `/api/auth/keys`.
- Sync rules: **edition 3**, single `global_inventory` stream, `auto_subscribe`,
  projection `SELECT _id AS id, …, status FROM inventory_captures`.

## Authentication

RS256 + JWKS: the backend signs short-lived JWTs (`aud=powersync`,
`iss=retail-stock-take`) and exposes the public key at `/api/auth/keys`; PowerSync
validates against that JWKS. Keys are mounted from the `jwt-keys` Secret. No
`NEXT_PUBLIC_*`: the PowerSync URL is delivered at runtime in the token response.

## Computer vision

Ollama runs **in-cluster** as a Deployment (`infra/k8s/ollama/ollama.yaml`).
No host Ollama process is needed. Docker Desktop on Mac runs containers
CPU-only (no Metal/MPS pass-through), so `moondream` (~10–30 s/capture) is
the practical primary model; `qwen2.5vl:7b` is optional. `OLLAMA_ORIGINS`
is baked into the manifest, so the Host-header DNS-rebinding check never blocks
in-cluster requests. Models persist on a 10 Gi PVC and survive pod restarts.
Strict-JSON prompt + Pydantic validation; 503 on failure rather than writing garbage.
**Cloud has no Ollama** — the capture CV step is local-only until a cloud provider
(e.g. Bedrock — deps would need re-adding) is wired. Storage + sync work everywhere;
**Vector Search is a Preview feature deferred on the local stack** (it needs
MongoDB 8.2+, while the in-cluster Ops Manager 8.0 provisions 8.0.9-ent) and
activates once Ops Manager is upgraded. Cloud (Atlas) has native Vector Search.

## Repo layout

```
backend/   — FastAPI (api/, cv/, db/, storage/, retention/)
frontend/  — Next.js client; AppSchema lives in lib/powersync/schema.js
powersync/ — powersync.yaml + sync-rules.yaml (mounted via ConfigMap)
infra/k8s/ — kind manifests (operator, ops-manager, mongodb, seaweedfs, ingress, access/)
infra/local/   — web-app Helm values for local (kind)
environment/    — web-app Helm values for Kanopy (base + per-service)
.drone.yml      — Kanopy CI/CD (separate pods, 3 releases)
```

## Why kind + self-hosted Ops Manager (not Compose)

Self-managed MongoDB **Vector Search** needs `mongot` Search nodes, which MongoDB
supports via the **MCK operator** + a `MongoDBSearch` CR — so local must be
Kubernetes (kind). To get true **Enterprise** with **no external cloud
dependency**, the deployment is managed by a **self-hosted Ops Manager** running
**in the same kind cluster** (fully air-gapped after images are pulled); the
operator drives Ops Manager, and Ops Manager's automation agent provisions the
`mongod` data plane. Running the **full** stack inside kind (not split with
host-side PowerSync) sidesteps the old kind↔host DNS pitfall. Ops Manager is the
heaviest component (~4 GB) — see RUN_LOCAL.md for the RAM budget.

## Why photos are now persisted

The demo now showcases the metadata-plus-object-store pattern: MongoDB holds
inventory + an asset reference; raw frames live in an S3-compatible store
(SeaweedFS local, AWS S3 cloud). This is the standard pattern for media-heavy
workloads and sets up future per-product crops + vector search over them.

## Dev tooling (local only)

Two local-only ingress routes with no cloud equivalent:

- `http://s3.localtest.me` → SeaweedFS filer UI (port 8888). The filer is already
  started by `weed server -s3` (S3 requires the filer); only port 8888 is additionally
  exposed in the Service. Browse the bucket at `/buckets/store-media/`. No credentials
  needed — the `anonymous` identity in `s3.json` applies.
- `http://backend.localtest.me` → FastAPI Swagger (`/docs`) and ReDoc (`/redoc`).
  A local-only Ingress routes to the existing `retail-stock-take-backend-web-app-80`
  Service; no change to the Deployment or the cloud/Kanopy setup.

## Phase 2 commitments

- `frontend/lib/powersync/schema.js` is the single source of truth for the client
  SQLite schema; the RN client re-shares the same `AppSchema`.
- `/api/auth/{token,keys}` and `/api/inventory/capture` are stable contracts.
- Mobile photo upload is a separate offline queue (large binary); PowerSync's
  upload queue handles structured writes when inventory edits land.
- Sync is one global stream; partition by `store_id`/`operator_id` (already stored
  per doc) once the JWT carries those claims.
