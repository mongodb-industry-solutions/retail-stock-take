# Cloud Deployment — Kanopy (internal)

Internal reference for deploying and maintaining the demo on the Industry Solutions
Kanopy cluster. Not intended for demo participants.

---

## Overview

Three `mongodb/web-app` (chart 4.30.0) Helm releases, deployed via Drone:

| Release | Ingress | Notes |
|---|---|---|
| `retail-stock-take-backend` | None (internal) | FastAPI; reached via frontend proxy + PS JWKS |
| `retail-stock-take-frontend` | Yes (app) | Next.js standalone |
| `retail-stock-take-powersync` | Yes (WebSocket) | upstream `journeyapps/powersync-service` image |

Images (backend + frontend) are built by Drone → pushed to ECR. PowerSync uses the
upstream image directly (no build step).

MongoDB → **Atlas**. CV capture in cloud runs through **Grove** (MongoDB's
GenAI gateway — OpenAI-compatible, vision). The **photo store is disabled in
cloud for now** (`STORAGE_PROVIDER=none`): capture keeps the inventory metadata
and syncs it, but does not persist the raw frame — so **no AWS S3 bucket / IRSA
is required**. (Re-enable object storage later; see Known limitations.)

---

## Environments

| Git branch | Drone pipeline | Kanopy API server | Namespace |
|---|---|---|---|
| `staging` | `staging` | `api.staging.corp.mongodb.com` | `industrysolutions` |
| `main` | `production` | `api.prod.corp.mongodb.com` | `industrysolutions` |

### URLs

| | Staging | Production |
|---|---|---|
| App (frontend) | `https://retail-stock-take-frontend.industrysolutions.staging.corp.mongodb.com` | `https://retail-stock-take-frontend.industrysolutions.prod.corp.mongodb.com` |
| PowerSync | `https://retail-stock-take-powersync.industrysolutions.staging.corp.mongodb.com` | `https://retail-stock-take-powersync.industrysolutions.prod.corp.mongodb.com` |
| Health (via proxy) | `<frontend-url>/api/health` | `<frontend-url>/api/health` |

---

## First-time setup (per environment)

All of the following must be done **once per environment** before the first Drone
push. Drone will fail silently if secrets/configmaps are missing.

### 1. Atlas cluster

- Create an Atlas cluster (M10+ for change streams).
- Create three database users: `app` (readWrite on `retail-stock-take`), `powersync`
  (readWrite on `rs-powersync`, read on `retail-stock-take`, clusterMonitor), `admin` (root).
- **The collection + change-stream pre/post images are created automatically.**
  On startup the backend runs `ensure_collection_ready()`, which creates
  `inventory_captures` **with `changeStreamPreAndPostImages` enabled** if it's
  missing — this uses only `createCollection` (granted by `readWrite`), so no
  manual step and no `dbAdmin` are needed for a fresh deploy. (Locally, mongo-init
  already does this.)
  - **Only if the collection already exists *without* pre/post images** does the
    backend fall back to `collMod` — which requires **`dbAdmin`**. If your `app`
    user lacks it, the backend logs a warning (non-fatal) and you enable it once
    with an admin user:

    ```js
    db.getSiblingDB("retail-stock-take").runCommand({
      collMod: "inventory_captures",
      changeStreamPreAndPostImages: { enabled: true }
    })
    ```

- Whitelist the Kanopy egress IPs in Atlas Network Access.

### 2. Grove (cloud CV provider)

Request access at **grove.aix.prod.corp.mongodb.com/requests** — a **service
(tier-2) key** for a vision model (default `gpt-5.5`, fallback `gpt-4o`; any
vision-capable Grove model works). The request's **Usage** section shows the
provisioned base URL + model; override `GROVE_BASE_URL` / `GROVE_MODEL` in
`environment/*-backend.yaml` if they differ from the defaults. The key goes into
the `retail-stock-take` Secret as `GROVE_API_KEY` (next step).

> **AWS S3 is not required right now.** The photo store is disabled in cloud
> (`STORAGE_PROVIDER=none`). To enable it later: create buckets
> `retail-stock-take-media-staging` / `-prod` in `us-east-1` (no public access),
> grant the IRSA role (`kanopy-staging-cicd-irsa` / `kanopy-prod-cicd-irsa`)
> `s3:PutObject/GetObject/HeadObject/DeleteObject/ListBucket`, then set
> `STORAGE_PROVIDER=s3` + `STORAGE_BUCKET` in `environment/*-backend.yaml`.

### 3. JWT keypair

Generate once and reuse across environments (or generate separately per env):

```bash
openssl genrsa -out jwt-private.pem 2048
openssl rsa -in jwt-private.pem -pubout -out jwt-public.pem
```

Keep the private key out of the repo. Store it in a password manager.

### 4. Kubernetes secrets and configmap — cloud secrets checklist

Three namespace objects must exist **before** the Drone deploy runs — Helm only
*references* them, it never creates them. Create all three in **each** target
cluster (staging **and** prod). A missing/renamed object → pods crash-loop.

- [ ] **Secret `retail-stock-take`** — `MONGODB_URI`, `PS_DATA_SOURCE_URI`,
      `PS_MONGO_URI` (Atlas SRV strings) + `GROVE_API_KEY` (Grove gateway key).
      Consumed via `envSecrets` in `environment/*-backend.yaml` + `*-powersync.yaml`.
- [ ] **Secret `jwt-keys`** — files `jwt-private.pem` + `jwt-public.pem` (from
      §3). Mounted at `/secrets` by the backend (`volumeSecrets`); `JWT_PRIVATE_KEY_PATH`
      / `JWT_PUBLIC_KEY_PATH` point at those files.
- [ ] **ConfigMap `powersync-config`** — `powersync.yaml` + `sync-rules.yaml`.
      Mounted at `/config` by the PowerSync release. It's a snapshot — recreate
      it whenever either file changes.

Run once per cluster from the repo root (after generating the JWT keypair, §3).
The `--dry-run | apply` form is **idempotent** — safe to re-run, e.g. to add
`GROVE_API_KEY` to an existing secret:

```bash
# 1. Pick the cluster + namespace (run this whole block again for prod)
kubectl config use-context api.staging.corp.mongodb.com   # api.prod.corp.mongodb.com for prod
NAMESPACE=industrysolutions

# 2. App secrets — Atlas SRV strings + Grove key. Replace <PASSWORD> / <GROVE_API_KEY>.
kubectl -n "$NAMESPACE" create secret generic retail-stock-take \
  --from-literal=MONGODB_URI="mongodb+srv://app:<PASSWORD>@<cluster>.mongodb.net/retail-stock-take?authSource=admin" \
  --from-literal=PS_DATA_SOURCE_URI="mongodb+srv://powersync:<PASSWORD>@<cluster>.mongodb.net/retail-stock-take?authSource=admin" \
  --from-literal=PS_MONGO_URI="mongodb+srv://powersync:<PASSWORD>@<cluster>.mongodb.net/rs-powersync?authSource=admin" \
  --from-literal=GROVE_API_KEY="<GROVE_API_KEY>" \
  --dry-run=client -o yaml | kubectl -n "$NAMESPACE" apply -f -

# 3. JWT keypair (the PEMs generated in §3, in the current directory).
kubectl -n "$NAMESPACE" create secret generic jwt-keys \
  --from-file=jwt-private.pem=./jwt-private.pem \
  --from-file=jwt-public.pem=./jwt-public.pem \
  --dry-run=client -o yaml | kubectl -n "$NAMESPACE" apply -f -

# 4. PowerSync config (mounted at /config).
kubectl -n "$NAMESPACE" create configmap powersync-config \
  --from-file=powersync.yaml=powersync/powersync.yaml \
  --from-file=sync-rules.yaml=powersync/sync-rules.yaml \
  --dry-run=client -o yaml | kubectl -n "$NAMESPACE" apply -f -

# 5. Verify all three exist.
kubectl -n "$NAMESPACE" get secret retail-stock-take jwt-keys -o name
kubectl -n "$NAMESPACE" get configmap powersync-config -o name
```

> **No AWS S3 secret/bucket needed** — the cloud photo store is off
> (`STORAGE_PROVIDER=none`). Re-enable per §2 if you later want persisted frames.

### 5. Drone secrets

In Drone CI (drone.corp.mongodb.com), add these repository secrets:

| Secret name | Value |
|---|---|
| `ecr_access_key` | AWS access key with ECR push rights |
| `ecr_secret_key` | Corresponding secret key |
| `staging_kubernetes_token` | Kanopy staging service account token |
| `prod_kubernetes_token` | Kanopy production service account token |

### 6. Trigger the first deploy

Push to `staging` (or `main` for production). Drone builds both images, pushes to
ECR, and runs the three Helm deploys in sequence.

---

## How deployment works

On every push to `staging` or `main`, Drone:

1. Builds `Dockerfile.backend` → ECR (`industrysolutions/retail-stock-take-backend`)
2. Builds `Dockerfile.frontend` → ECR (`industrysolutions/retail-stock-take-frontend`)
3. `helm upgrade --install` for backend, frontend, powersync in sequence

Each deploy step merges:
- A shared base (`environment/staging.yaml` or `environment/production.yaml`) — IRSA,
  data classification, owner email, `AWS_REGION`
- A per-service file (`environment/<env>-<service>.yaml`) — ports, probes, env vars,
  secret refs

The image tag is `git-<7-char-sha>` (pinned per deploy) plus a rolling `latest` /
`prod-latest` tag.

PowerSync is **not built** — the Drone step sets `image.repository` +
`image.tag=1.21.0` directly on the upstream image.

---

## Configuration reference

### Shared env (all services, both envs)

| Key | Value | Notes |
|---|---|---|
| `AWS_REGION` | `us-east-1` | Set in the base `environment/*.yaml` |

### Backend env

| Key | Staging | Production | Notes |
|---|---|---|---|
| `STORAGE_PROVIDER` | `none` | `none` | Photo store off in cloud (metadata only). Set `s3` + `STORAGE_BUCKET` to re-enable |
| `CV_PROVIDER` | `grove` | `grove` | Cloud vision backend (local uses `ollama`) |
| `GROVE_BASE_URL` | Grove gateway URL | same | OpenAI-compatible endpoint; from your Grove request |
| `GROVE_MODEL` | `gpt-5.5` | `gpt-5.5` | Primary vision model (env-overridable) |
| `GROVE_FALLBACK_MODEL` | `gpt-4o` | `gpt-4o` | Auto-fallback on failure |
| `GROVE_API_KEY` | from secret | from secret | Grove key, key in `retail-stock-take` |
| `RETENTION_DAYS` | `7` | `30` | Days before docs expire (no-op while photo store off) |
| `POWERSYNC_PUBLIC_URL` | `https://…staging.corp.mongodb.com` | `https://…prod.corp.mongodb.com` | Delivered to browser via `/api/auth/token` |
| `POWERSYNC_INTERNAL_URL` | `http://retail-stock-take-powersync-web-app-80` | same | In-cluster health probe |
| `MONGODB_URI` | from secret | from secret | Atlas SRV string, key in `retail-stock-take` |

### Frontend env

| Key | Value | Notes |
|---|---|---|
| `BACKEND_URL` | `http://retail-stock-take-backend-web-app-80` | In-cluster Service name (`<release>-web-app-80`) |
| `NODE_ENV` | `production` | |

### PowerSync env

| Key | Value | Notes |
|---|---|---|
| `PS_JWKS_URL` | `http://retail-stock-take-backend-web-app-80/api/auth/keys` | In-cluster; backend need not have ingress |
| `PS_DATA_SOURCE_URI` | from secret | Atlas SRV for the source (`retail-stock-take`) DB |
| `PS_MONGO_URI` | from secret | Atlas SRV for the PowerSync bucket (`rs-powersync`) DB |
| `POWERSYNC_CONFIG_PATH` | `/config/powersync.yaml` | Mounted from `powersync-config` ConfigMap |

---

## Maintenance

### Updating the app

Push to `staging` or `main`. Drone deploys automatically. No manual `helm` commands
needed.

### Updating PowerSync

Change `image.tag` in the Drone deploy step for powersync (both `staging` and
`production` pipelines in `.drone.yml`), then push to trigger a redeploy:

```yaml
- "image.tag=1.22.0"   # was 1.21.0
```

### Rotating JWT keys

1. Generate a new keypair (see step 3 above).
2. Update the `jwt-keys` secret in each namespace:
   ```bash
   kubectl -n industrysolutions create secret generic jwt-keys \
     --from-file=jwt-private.pem=./jwt-private-new.pem \
     --from-file=jwt-public.pem=./jwt-public-new.pem \
     --dry-run=client -o yaml | kubectl apply -f -
   ```
3. Restart the backend deployment (PowerSync fetches the JWKS on every token
   validation, so no restart needed there):
   ```bash
   kubectl -n industrysolutions rollout restart deploy/retail-stock-take-backend-web-app
   ```

### Updating PowerSync sync rules

Edit `powersync/sync-rules.yaml`, then update the ConfigMap and restart PowerSync:

```bash
kubectl -n industrysolutions create configmap powersync-config \
  --from-file=powersync.yaml=powersync/powersync.yaml \
  --from-file=sync-rules.yaml=powersync/sync-rules.yaml \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n industrysolutions rollout restart deploy/retail-stock-take-powersync-web-app
```

### Rotating Atlas credentials

1. Update the Atlas user password.
2. Update the `retail-stock-take` secret:
   ```bash
   kubectl -n industrysolutions create secret generic retail-stock-take \
     --from-literal=MONGODB_URI="mongodb+srv://app:<NEW_PASSWORD>@..." \
     --from-literal=PS_DATA_SOURCE_URI="..." \
     --from-literal=PS_MONGO_URI="..." \
     --dry-run=client -o yaml | kubectl apply -f -
   ```
3. Restart all three deployments.

---

## Known limitations

- **No photo store in cloud (for now).** `STORAGE_PROVIDER=none`, so capture
  runs CV + writes inventory metadata + syncs via PowerSync, but the raw frame
  is **not** persisted (`doc.asset` is null). No AWS S3 bucket / IRSA is
  required. Re-enable object storage by creating the buckets + IRSA S3
  permissions and setting `STORAGE_PROVIDER=s3` + `STORAGE_BUCKET` (see
  Prerequisites §2). The retention reconciler runs but has no objects to expire
  while disabled.
- **Cloud CV depends on a valid Grove key.** If `GROVE_API_KEY` is missing or
  the model isn't provisioned, capture returns 503 and `/api/health` shows the
  `cv` field as `GROVE_API_KEY not set` (or the Grove error). Local capture is
  unaffected (it uses Ollama).
- **No `NEXT_PUBLIC_*` vars.** All runtime config (PowerSync URL, backend URL) is
  delivered at runtime via the Next.js proxy and `/api/auth/token`. Do not bake
  env vars into the image at build time.
- **PowerSync config is a ConfigMap** — it is not part of the image. Sync rule
  changes require the ConfigMap to be updated separately from the Drone deploy
  (see Maintenance above).

---

## Troubleshooting

### Drone deploy step fails — "release not found"

Helm can't find the release on the cluster. Usually the Kanopy token is stale or
missing. Re-generate the token and update the `staging_kubernetes_token` /
`prod_kubernetes_token` Drone secret.

### Backend pod in CrashLoopBackOff

```bash
kubectl -n industrysolutions logs deploy/retail-stock-take-backend-web-app --previous
```

Common causes:
- `retail-stock-take` Secret missing or has wrong key names.
- `jwt-keys` Secret missing.
- Atlas connection string wrong (typo in SRV, password special chars not URL-encoded).
- `changeStreamPreAndPostImages` not enabled on Atlas — the backend asserts this at startup.

### PowerSync not syncing

1. Check readiness: `curl https://retail-stock-take-powersync.industrysolutions.staging.corp.mongodb.com/probes/readiness`
2. Check PowerSync logs: `kubectl -n industrysolutions logs deploy/retail-stock-take-powersync-web-app`
3. Common causes:
   - `PS_DATA_SOURCE_URI` wrong (can't connect to Atlas).
   - Backend down (PowerSync can't reach JWKS endpoint).
   - `powersync-config` ConfigMap missing.

### Frontend shows blank / API errors

Check `BACKEND_URL` resolves correctly in-cluster:

```bash
kubectl -n industrysolutions exec deploy/retail-stock-take-frontend-web-app -- \
  wget -qO- http://retail-stock-take-backend-web-app-80/api/health
```

The in-cluster Service is always `<release>-web-app-80` (web-app chart convention).
If the backend release name changes, `BACKEND_URL` in `environment/staging-frontend.yaml`
must be updated to match.
