# Retail Stock Take — MongoDB ↔ PowerSync

A demo that shows MongoDB and PowerSync solving **disconnected environments** in
retail field work.

A worker photographs a shelf. A computer-vision model turns it into a structured
JSON inventory. MongoDB stores the inventory alongside a reference to the raw frame
in object storage. PowerSync syncs everything to every connected client — including
clients that go offline and come back.

## What it demonstrates

- **Change streams** with `changeStreamPreAndPostImages` drive PowerSync sync with
  no custom triggers or polling.
- The **document model** carries the nested `items` array from the CV model directly
  into client-side SQLite.
- **Metadata + blob plane**: MongoDB owns the metadata; S3-compatible object storage
  owns the raw frames — the standard pattern for media-heavy workloads.
- **Self-hosted Vector Search** (`mongot`) is wired via the MCK operator for
  embedding shelf crops in a future phase (Preview — see note under Tech stack).

## Architecture

```
Browser ── http://frontend.localtest.me
  │  /api/*  ── Next.js proxy ──▶ backend (internal, no ingress)
  │  WebSocket ──▶ http://powersync.localtest.me
  ▼
backend (FastAPI)
  ├─ Ollama (host) ── CV → structured JSON inventory
  ├─ MongoDB Enterprise RS  (MCK operator, self-hosted Ops Manager — in-cluster)
  └─ SeaweedFS (S3 gateway) ── raw frame storage
MongoDB change stream → PowerSync → WebSocket → browser SQLite (wa-sqlite / OPFS)
```

Capture flow: browser → `POST /api/inventory/capture` → CV (Ollama) → insert doc
`status=PENDING_UPLOAD` → `put_object` to S3 → update `status=ACTIVE` → change
stream → PowerSync → browser re-renders.

## Tech stack

- MongoDB **Enterprise 8.0.9-ent** (MCK operator, self-hosted Ops Manager — fully
  in-cluster, no external account). `mongot` Search is wired but **Preview/deferred**:
  Ops Manager 8.0 provisions MongoDB 8.0.x, and Search needs 8.2+. Storage, sync, and
  capture all work today; Search activates once Ops Manager is upgraded.
- PowerSync 1.21.0 self-hosted (MongoDB-backed bucket storage)
- SeaweedFS (S3-compatible object store, in-cluster)
- FastAPI + Python 3.13 + `uv`
- Next.js 15 (App Router, JS) + LeafyGreen + Tailwind 4
- `@powersync/web` + `@journeyapps/wa-sqlite` (OPFS)
- Ollama / Qwen2.5-VL 7B (host machine)
- kind (local Kubernetes)

## Quick start

**No external cloud account is required** — the control plane (Ops Manager) runs
inside the kind cluster. See **[`RUN_LOCAL.md`](RUN_LOCAL.md)** for the full guide:
prerequisites, expected timings, caveats, and troubleshooting.

```bash
./scripts/setup.sh         # ~25–35 min on first run (Ops Manager dominates)
./scripts/verify.sh        # end-to-end smoke test
open http://frontend.localtest.me
```

`setup.sh` prints ready-to-use access details (a Compass connection string, the Ops
Manager login, and S3 keys) when it finishes. The cluster exposes them on these host
ports (always-on, no `kubectl port-forward` needed):

| What | Endpoint | Notes |
|---|---|---|
| Web app | `http://frontend.localtest.me` | |
| Backend health | `http://frontend.localtest.me/api/health` | via the frontend proxy |
| PowerSync | `http://powersync.localtest.me/probes/liveness` | |
| MongoDB (Compass) | `localhost:27017` | `…/?authSource=admin&directConnection=true` |
| Ops Manager UI | `http://localhost:8080` | login printed by `setup.sh` |
| S3 (SeaweedFS) | `http://localhost:8333` | bucket `store-media`, keys `retaildemo`/`retaildemo-secret` |
| S3 browser UI | `http://s3.localtest.me/buckets/store-media/` | local dev only; no login needed |
| Backend API docs | `http://backend.localtest.me/docs` | local dev only; Swagger + ReDoc |

## Make targets

| | |
|---|---|
| `make setup` | Bring up the kind cluster |
| `make verify` | End-to-end smoke test |
| `make status` | `kubectl -n retail get pods,svc,ingress` |
| `make logs` | Tail app pod logs |
| `make reset` | Tear down the kind cluster |
| `make uv_sync` | Refresh backend Python deps |

## Repo layout

```
backend/       FastAPI: api/, cv/, db/, storage/ (S3 adapter), retention/
frontend/      Next.js client; PowerSync schema in lib/powersync/schema.js
powersync/     powersync.yaml + sync-rules.yaml
infra/k8s/     kind manifests (operator, MongoDB, SeaweedFS, ingress, access/ NodePorts)
deploy/local/  Helm values for the local kind stack
scripts/       lib.sh (shared helpers) + setup/preflight/verify/reset/pull-models
docs/          Architecture and troubleshooting notes
```

## Phase 2 (planned)

React Native mobile client sharing the same backend contracts:
`frontend/lib/powersync/schema.js`, `/api/auth/{token,keys}`, and
`POST /api/inventory/capture`. True offline capture with reconnect-and-sync.

## License

See [LICENSE](LICENSE).
