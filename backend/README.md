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
cv/          Ollama client + strict-JSON prompt (qwen2.5vl:3b primary) + tolerant parse
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

Env-driven; local cluster values live in `infra/local/backend.yaml`, cloud values
in `environment/*-backend.yaml`.
