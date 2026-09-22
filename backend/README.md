# Backend — retail-stock-take API

FastAPI + Python 3.13 (managed with [`uv`](https://docs.astral.sh/uv/)). It runs
the CV pipeline, owns the idempotent write path to MongoDB + object storage, issues
the JWTs PowerSync trusts, and runs the retention reconciler.

It is **internal-only**: the browser never calls it directly — it's reached through
the frontend's same-origin `/api/*` proxy and over in-cluster DNS (PowerSync →
JWKS). For the project overview see [`../README.md`](../README.md); to run the
whole stack locally see [`../docs/RUN_LOCAL.md`](../docs/RUN_LOCAL.md).

## Structure

```
api/         routes — auth (token/keys), health, inventory capture
cv/          Ollama client + strict-JSON prompt (moondream primary; qwen2.5vl optional)
db/          mdb.py (Mongo connector) + bootstrap.py (startup assertions)
storage/     vendor-agnostic S3 adapter — get_storage_adapter() (boto3; common S3 subset)
retention/   reconciler (promotes/expires docs, deletes objects past expires_at)
main.py      app wiring + startup hooks
```

## What it does

- **Capture FSM (idempotent, retry-safe):** `POST /api/inventory/capture` →
  CV (Ollama) → insert doc `status=PENDING_UPLOAD` with an embedded `asset` ref +
  deterministic key → `put_object` to S3 → update `status=ACTIVE` (+size+checksum)
  → `201`. The MongoDB change stream then drives PowerSync. The reconciler cleans
  up stuck/expired records — retention is **not** done via bucket lifecycle.
- **Storage is vendor-agnostic.** All object I/O goes through
  `storage/get_storage_adapter()`; local = SeaweedFS endpoint + path-style + static
  keys, cloud = AWS S3 via IRSA. Business logic never touches provider-native APIs.
- **Auth:** RS256 JWTs via JWKS. `/api/auth/token` returns a short-lived token
  (`aud=powersync`, `iss=retail-stock-take`) plus the PowerSync URL;
  `/api/auth/keys` serves the public JWKS that PowerSync validates against.
- **Startup assertions** (`db/bootstrap.py`): refuses to start unless the source
  collection has `changeStreamPreAndPostImages` enabled (otherwise PowerSync would
  silently miss update/delete events).

## Config

Env-driven; the contract is documented in the root `.env.example`. Local cluster
values live in `infra/local/backend.yaml`, cloud values in `environment/*.yaml`.

## Local dev

Normally the backend runs **inside the kind cluster** via `./scripts/setup.sh`
(builds `backend/Dockerfile`). To iterate on it directly:

```bash
make uv_sync                 # install deps into backend/.venv
cd backend
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

It needs `MONGODB_URI`, the JWT key paths, and `STORAGE_*` / `OLLAMA_*` env set —
see `infra/local/backend.yaml` for the full list.
