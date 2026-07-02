# Troubleshooting

Common failure modes and their fixes for the **local kind stack**. Skim this when
something goes sideways — most issues are one of these.

All commands assume the kind cluster is up. Namespaces: `mongodb` (operator +
Ops Manager + MongoDB), `retail` (backend, frontend, powersync, SeaweedFS).

## Setup

### `preflight: port 80 / 443 is in use`

kind needs host ports 80/443 for the ingress controller. Stop whatever is bound
(local Nginx/Apache/Caddy, another container). UDP/outbound 443 (WARP, Slack,
browser QUIC) is harmless — preflight already filters those with
`lsof -iTCP -sTCP:LISTEN`.

### Setup hangs at "Ops Manager" or "replica set"

These are the long provisioning steps (Ops Manager ~10–15 min first run, the RS
~5–10 min). setup.sh shows a live spinner with the current phase. If it stalls or
fails:

```bash
kubectl -n mongodb describe opsmanager ops-manager
kubectl -n mongodb describe mongodb retail-mongodb
kubectl -n mongodb logs deploy/mongodb-kubernetes-operator
kubectl -n mongodb get events --sort-by='.lastTimestamp' | tail -30
```

Most common cause: not enough RAM for Ops Manager (~4 GB). Increase Docker
Desktop's memory (Settings → Resources → Memory) and re-run `./scripts/setup.sh`
(idempotent). The pinned MongoDB version (`8.0.9-ent`) must be one the in-cluster
Ops Manager 8.0 supports — do not bump it to 8.1/8.2 without upgrading Ops Manager.

## Mongo / replica set

### Replica set never reaches `Running`

Provisioning runs through the in-cluster Ops Manager automation agent. Check:

```bash
kubectl -n mongodb get mongodb retail-mongodb -o jsonpath='{.status}' | jq
kubectl -n mongodb describe mongodb retail-mongodb
# Ops Manager UI (automation state): http://localhost:8080  (creds in setup output)
```

If you changed the MongoDB version, delete and re-apply the CR:

```bash
kubectl -n mongodb delete mongodb retail-mongodb
kubectl apply -f infra/k8s/mongodb/10-mongodb-enterprise.yaml
```

### Pre/post images aren't enabled

The post-init Job enables `changeStreamPreAndPostImages` on
`retail_demo.inventory_captures`, and the backend asserts it at startup. If the
Job failed:

```bash
kubectl -n mongodb logs job/retail-mongodb-postinit
# re-run it:
kubectl -n mongodb delete job retail-mongodb-postinit --ignore-not-found
kubectl apply -f infra/k8s/mongodb/40-postinit-job.yaml
```

### Backend `CrashLoopBackOff` with `changeStreamPreAndPostImages not enabled`

Intentional — PowerSync would silently miss update/delete events. Fix the Job
(above), then restart the backend:

```bash
kubectl -n retail rollout restart deploy/retail-stock-take-backend-web-app
```

### Backend can't authenticate to MongoDB

The connection-string secrets are built from the operator-generated password
secrets (`retail-mongodb-<user>-admin`), not the seed secrets. If the URI is
stale, re-run `./scripts/setup.sh` (it rewrites `retail-mongodb-uri` and
`retail-powersync-secrets`).

## PowerSync

### `mongosh` insert doesn't appear in the browser

Walk the debug ladder in [`verification.md`](verification.md). The single most
common cause is the JWT `aud` claim — decode the token at jwt.io and confirm
`aud === "powersync"` matches the `audience` in `powersync/powersync.yaml`.

### PowerSync logs: "loaded sync rules" missing / parse error

YAML error in `powersync/sync-rules.yaml`. Lint it, then refresh the ConfigMap and
restart the pod (see `powersync/README.md`):

```bash
kubectl -n retail logs deploy/retail-stock-take-powersync-web-app | head -20
```

### PowerSync logs: "connection refused" to JWKS

PowerSync validates JWTs against the backend's JWKS over in-cluster DNS
(`PS_JWKS_URL=http://retail-stock-take-backend-web-app-80/api/auth/keys`). If the
backend is down or not ready, fix it first, then:

```bash
kubectl -n retail rollout restart deploy/retail-stock-take-powersync-web-app
```

### OPFS errors / `wa-sqlite` won't load

OPFS persistence requires the page to be **cross-origin isolated**. The headers
are set in `frontend/next.config.mjs`:

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

Verify in DevTools → Network → the document request → Response Headers. Use
Chrome/Edge — Safari restricts OPFS in private windows.

### Stale local SQLite after schema changes

The browser keeps the PowerSync DB in OPFS. After changing
`frontend/lib/powersync/schema.js` (or a fresh cluster), clear it:
DevTools → Application → Storage → **Clear site data** for
`http://frontend.localtest.me`. `make reset` does NOT touch browser OPFS.

## Ollama / CV

### `/api/inventory/capture` returns 503 "computer vision unavailable"

Ollama runs **in-cluster** — diagnose with:

```bash
kubectl -n retail get pod -l app=ollama          # pod running?
kubectl -n retail logs deploy/ollama             # startup errors?
kubectl -n retail exec deploy/ollama -- ollama list  # models present?
```

If models are missing (e.g. after a `make reset`), re-pull:

```bash
bash scripts/pull-models.sh
```

If the pod is in `CrashLoopBackOff`, it likely needs more memory — increase Docker
Desktop's RAM allocation (Settings → Resources → Memory).

### CV returns unexpected items / hallucinations, or capture is slow

Docker Desktop on Mac runs containers CPU-only (no Metal/MPS pass-through).
`moondream` (~10–30 s/capture) is the default. `qwen2.5vl:7b` is available as the
fallback but is significantly slower on CPU (~2–5 min/capture). Switch primary model
by setting `OLLAMA_MODEL=qwen2.5vl:7b` in `deploy/local/backend.yaml`, then:

```bash
kubectl -n retail rollout restart deploy/retail-stock-take-backend-web-app
```

## Web app

### `Initializing local database…` never goes away

The PowerSync provider is stuck. Check the browser console. Most likely:

- Backend unreachable through the proxy — `curl -s http://frontend.localtest.me/api/health`.
- Token request failed — check `/api/auth/token` in the Network tab.
- Schema mismatch — clear OPFS (above).

### Inventory list empty after a successful insert

- The watched query fired before sync completed — wait ~2 s.
- Local SQLite schema differs from the server — clear OPFS.
- The sync rule's SQL doesn't match the doc shape — check
  `kubectl -n retail logs deploy/retail-stock-take-powersync-web-app` for
  per-document replication lines.

## Host access (NodePort) not working

The always-on host endpoints are published by kind `extraPortMappings`, which are
**fixed at cluster creation**. If `localhost:27017` / `:8080` / `:8333` don't
respond:

```bash
# the mappings only exist if the cluster was created with the current kind-cluster.yaml:
make reset && make setup
```

Then confirm the NodePort Services exist:

```bash
kubectl -n mongodb get svc retail-mongodb-ext ops-manager-ext
kubectl -n retail  get svc seaweedfs        # type should be NodePort
```

- **MongoDB :27017** — connect with `directConnection=true` (a replica-set URI
  advertises in-cluster DNS names that don't resolve from the host):
  `mongodb://admin:<pw>@localhost:27017/?authSource=admin&directConnection=true`
- **Ops Manager :8080** — open `http://localhost:8080`.
- **S3 :8333** — `aws s3 ls s3://store-media/ --endpoint-url http://localhost:8333 --region us-east-1`.

If a port is taken on the host, free it (e.g. a local `mongod` on 27017) or change
the mapping in `infra/k8s/kind-cluster.yaml` and recreate.

## Reset / start over

```bash
./scripts/reset.sh         # deletes the kind cluster + all in-cluster state
# clear browser OPFS for http://frontend.localtest.me manually
./scripts/setup.sh
```

To also rotate the JWT keys, delete `.secrets/` before re-running setup.
