# Running the demo locally (kind)

The local stack runs entirely in a **kind** (Kubernetes-in-Docker) cluster on your
machine. **No external cloud account is required.** MongoDB Enterprise is managed by
a self-hosted Ops Manager instance running inside the same kind cluster — fully
air-gapped after images are pulled.

---

## Prerequisites

### Tools

| Tool | How to install |
|---|---|
| Docker Desktop ≥ 24 (or Engine) | https://docs.docker.com/get-docker/ |
| `kind` | `brew install kind` or https://kind.sigs.k8s.io |
| `kubectl` | `brew install kubectl` |
| `helm` | `brew install helm` |
| `openssl` | ships with macOS; `brew install openssl` on Linux |

### Hardware

- **24 GB RAM strongly recommended.** Ops Manager alone needs ~4 GB. The full
  stack (Ops Manager + its app DB + MCK operator + Enterprise mongod + mongot
  Search + SeaweedFS + Ollama + backend + frontend + PowerSync) will be tight at
  16 GB. Ollama adds ~2 GB requests.
- **~15 GB free disk** for Docker images and kind node layers (Ops Manager image
  is large).
- **~2 GB extra** for the Moondream model (downloaded into the Ollama PVC on
  first run).

### Host ports the cluster publishes

kind maps these host ports into the cluster (fixed at cluster-creation time):

| Host port | Goes to | Used for |
|---|---|---|
| 80, 443 | ingress-nginx | `http://*.localtest.me` (the app) |
| 27017 | MongoDB (NodePort) | Compass / mongosh |
| 8080 | Ops Manager (NodePort) | Ops Manager web UI |
| 8333 | SeaweedFS (NodePort) | S3 API (AWS CLI / Cyberduck) |

**80 and 443 must be free** before `setup.sh` creates the cluster, or creation
fails. The other three should ideally be free too (if one is taken — e.g. a local
`mongod` on 27017 — that mapping won't work, but the cluster still comes up; free the
port or edit `infra/k8s/kind-cluster.yaml`, then `make reset && make setup`).

To check the ingress ports:

```bash
sudo lsof -iTCP:80 -P -sTCP:LISTEN
sudo lsof -iTCP:443 -P -sTCP:LISTEN
```

Common culprits: local Nginx/Apache, other Docker containers binding `:80`, Caddy.
Cloudflare WARP, Slack, and browser UDP connections to remote port 443 are
**harmless** — they are outbound connections, not local listeners.

### Ollama (CV)

Ollama runs **inside the kind cluster** — no host installation needed. The setup
script deploys it and pulls `moondream` (~1.5 GB) in the background automatically.
Docker Desktop on Mac runs containers CPU-only (no Metal/MPS pass-through), so
inference is ~10–30 s per capture. The higher-quality `qwen2.5vl:7b` can be
enabled via `OLLAMA_MODEL=qwen2.5vl:7b` in `.env`, but is ~2–5 min/capture on CPU.

If models need to be re-pulled after a `make reset`:

```bash
bash scripts/pull-models.sh
```

---

## First-time setup

### 1. (Optional) Create a `.env` file for overrides

No credentials are required. The `.env` file is only needed if you want to
override defaults (cluster name, operator version, Ollama model, etc.):

```bash
cp .env.example .env
# Edit .env and uncomment/change the values you want to override.
```

`setup.sh` loads `.env` automatically if present. The file is gitignored.

### 2. Run setup

```bash
./scripts/setup.sh
```

The script is **idempotent** — re-running after a partial failure resumes from where
it stopped. What it does, in order:

| Step | What happens | Typical wait |
|---|---|---|
| Preflight | Checks tools, ports, RAM | instant |
| kind cluster | Creates one control-plane node + host port mappings (80/443/27017/8080/8333) | ~30 s |
| ingress-nginx | Deploys the kind-flavoured ingress controller | ~60 s |
| MCK operator | Installs the MongoDB Kubernetes operator via Helm | ~60 s |
| OM admin secret | Generates random Ops Manager admin password | instant |
| Ops Manager CR | Provisions Ops Manager + its application DB in-cluster | **~10–15 min** |
| Wait for OM secret | MCK creates the `mongodb-ops-manager-admin-key` Secret once OM is Running | ~30 s |
| OM project ConfigMap | Fetches the orgId from the OM API and writes the project ConfigMap | instant |
| JWT keypair | Generates a fresh RS256 keypair into `.secrets/` | instant |
| MongoDB passwords | Generates random SCRAM passwords as Secrets | instant |
| MongoDB CR | Submits the `MongoDB` CR; Ops Manager provisions the RS | **~5–10 min** |
| MongoDBSearch CR | Applied but **deferred** (Preview; needs MongoDB 8.2+) | instant |
| Connection secrets | Builds SCRAM URIs from the operator-published passwords | instant |
| Post-init Job | Enables `changeStreamPreAndPostImages` on the collection | ~30 s |
| SeaweedFS | Deploys the S3-compatible object store (StatefulSet, NodePort) | ~60 s |
| Host access | Applies the MongoDB + Ops Manager NodePort Services | instant |
| PowerSync ConfigMap | Mounts `powersync.yaml` + `sync-rules.yaml` | instant |
| Ollama Deployment | Deploys Ollama in-cluster (PVC + ClusterIP Service); waits for pod ready | ~60 s |
| Docker builds | Builds backend + frontend images and loads them into kind | ~2–4 min |
| Helm releases | Deploys backend, frontend, powersync via `mongodb/web-app` | ~60 s each |
| Ingress | Creates `*.localtest.me` ingress rules | instant |
| Rollout waits | Waits for all three app Deployments to go Ready | ~60 s |
| Model pull (bg) | Pulls moondream + qwen2.5vl:7b in background inside the Ollama pod (logs → `/tmp/retail-ollama-pull.log`) | ~5–10 min |

Total: **25–35 minutes** on first run (Ops Manager provisioning dominates).

### 3. Smoke test

```bash
./scripts/verify.sh
```

Checks: ingress reachability, backend health, PowerSync liveness/readiness, the
host-access ports (27017/8080/8333), MongoDB CR status, `changeStreamPreAndPostImages`,
JWKS/token endpoints, SeaweedFS round-trip, a real photo capture (if a sample photo
exists in `scripts/sample-photos/`), and the retention reconciler. Vector search is
reported as a non-fatal WARN (deferred — needs MongoDB 8.2+).

`setup.sh` itself ends by printing ready-to-use access details for all five
endpoints (app, MongoDB/Compass, Ops Manager, S3, dev tooling) with live credentials.

### 4. Open the app

```
http://localhost
```

Use `http://localhost`, not `http://frontend.localtest.me` — same app, same
Service, but only the literal `localhost` hostname is a browser "secure
context." PowerSync's local database (wa-sqlite/OPFS) needs the Web Locks API,
which Chrome disables outside a secure context, so the app silently never
syncs (stuck "offline") if opened via `frontend.localtest.me`.

| URL | What it is |
|---|---|
| http://localhost | Web app (use this) |
| http://frontend.localtest.me | Same web app — alias for curl/devtools use only, PowerSync sync will not work here |
| http://frontend.localtest.me/api/health | Backend health (via proxy) |
| http://powersync.localtest.me/probes/liveness | PowerSync liveness |
| http://powersync.localtest.me/probes/readiness | PowerSync readiness |
| http://s3.localtest.me/buckets/store-media/ | SeaweedFS filer UI — S3 browser (local dev only) |
| http://backend.localtest.me/docs | Backend Swagger UI (local dev only) |

The backend has **no production ingress** — the browser reaches it only through
the frontend's `/api/*` proxy and over in-cluster DNS (PowerSync → JWKS). That proxy is a runtime
Route Handler (`frontend/app/api/[...path]/route.js`) that reads `BACKEND_URL` at
request time, so the same image works in every environment with no `NEXT_PUBLIC_*`.

### 5. Connect to MongoDB, Ops Manager, and S3

These are exposed on host ports automatically — **no `kubectl port-forward`
needed**. `setup.sh` prints the exact strings (with live credentials) when it
finishes; you can also reconstruct them as below.

**MongoDB (Compass / mongosh)** — connect to the single replica-set member with
`directConnection=true` (the in-cluster RS member names don't resolve from the host):

```bash
ADMIN_PW=$(kubectl -n mongodb get secret retail-mongodb-retail-admin-admin \
  -o jsonpath='{.data.password}' | base64 -d)
echo "mongodb://admin:${ADMIN_PW}@localhost:27017/?authSource=admin&directConnection=true"
# paste that into Compass; data is in db retail_demo, collection inventory_captures
```

**Ops Manager web UI** — open <http://localhost:8080> and log in:

```bash
kubectl -n mongodb get secret ops-manager-admin-secret -o jsonpath='{.data.Username}' | base64 -d; echo
kubectl -n mongodb get secret ops-manager-admin-secret -o jsonpath='{.data.Password}' | base64 -d; echo
```

**S3 (SeaweedFS)** — endpoint `http://localhost:8333`, bucket `store-media`,
path-style, keys `retaildemo` / `retaildemo-secret`:

```bash
AWS_ACCESS_KEY_ID=retaildemo AWS_SECRET_ACCESS_KEY=retaildemo-secret \
  aws s3 ls s3://store-media/ --endpoint-url http://localhost:8333 --region us-east-1
```

### Dev tooling (local only)

**SeaweedFS filer UI** — browse the `store-media` bucket in the browser with no credentials:

```
http://s3.localtest.me/buckets/store-media/
```

Files uploaded by the backend appear under `raw/{store}/{device}/YYYY/MM/DD/HH/{id}.jpg`.
The filer runs on port 8888 inside the SeaweedFS pod (started implicitly by `weed server
-s3` — S3 is built on the filer). Only the Service port and an ingress rule are added;
no new host port mapping or container image is required.

**FastAPI Swagger / ReDoc** — interactive API docs served directly from the backend:

```
http://backend.localtest.me/docs         # Swagger UI (try-it-out enabled)
http://backend.localtest.me/redoc        # ReDoc (read-only)
http://backend.localtest.me/openapi.json # raw OpenAPI schema
```

> These are local dev tooling only. The backend has no ingress in cloud/Kanopy —
> cloud intentionally exposes no backend externally.

> These host ports come from `extraPortMappings` in `infra/k8s/kind-cluster.yaml`,
> which are fixed at cluster creation. If a port doesn't respond, recreate the
> cluster: `make reset && make setup`.

---

## Day-2 operations

### Useful commands

```bash
make status     # kubectl -n retail get pods,svc,ingress
make logs       # tail backend + frontend + powersync logs
make verify     # run smoke tests
make reset      # tear down kind cluster (see below)
```

### Checking Ops Manager and MongoDB provisioning

```bash
kubectl -n mongodb describe mongodbopsmanager ops-manager
kubectl -n mongodb describe mongodb retail-mongodb
kubectl -n mongodb describe mongodbsearch retail-search
kubectl -n mongodb logs deploy/mongodb-kubernetes-operator
```

### Tail app logs directly

```bash
kubectl -n retail logs deploy/retail-stock-take-backend-web-app -f
kubectl -n retail logs deploy/retail-stock-take-frontend-web-app -f
kubectl -n retail logs deploy/retail-stock-take-powersync-web-app -f
```

### Rebuilding after a code change

```bash
docker build -t retail-stock-take-backend:local -f backend/Dockerfile .
kind load docker-image retail-stock-take-backend:local --name retail-stock-take
kubectl -n retail rollout restart deploy/retail-stock-take-backend-web-app
```

Replace `backend` with `frontend` for frontend changes.

### Tear down

```bash
./scripts/reset.sh
```

Deletes the kind cluster and all in-cluster state (including Ops Manager and its
data). The `.secrets/` JWT keypair on disk is kept — delete it to rotate on the
next bring-up.

Also clear the browser's OPFS storage (which holds the PowerSync SQLite database)
so the next run doesn't show stale data:
**DevTools → Application → Storage → Clear site data** for `http://localhost`.

---

## Caveats

### Ops Manager is heavy — 24 GB RAM recommended

Ops Manager is a Java application that uses 2–4 GB in practice, plus its own
application database. The full stack may be tight at 16 GB. If pods get OOM-killed
during bring-up, increase Docker Desktop's memory allocation in
**Settings → Resources → Memory**.

### MongoDBOpsManager and MongoDBSearch are Preview / version-sensitive

Both CRDs (`MongoDBOpsManager`, `MongoDBSearch`) may have field names that differ
from what's in the manifests depending on the exact MCK version installed. If either
CR fails to apply or stalls, check the installed spec:

```bash
kubectl explain mongodbopsmanager.spec
kubectl explain mongodbsearch.spec
```

Key things setup.sh assumes that need live-cluster verification:
- Ops Manager Service name: `ops-manager-svc` (adjust `ops-manager-project`
  ConfigMap's `baseUrl` if different)
- API key Secret name: `mongodb-ops-manager-admin-key` (setup.sh polls for this)
- Status jsonpath: `{.status.opsManager.phase}` and `{.status.applicationDatabase.phase}`

### MongoDB Enterprise version must be available in Ops Manager

`infra/k8s/mongodb/10-mongodb-enterprise.yaml` pins `version: "8.0.9-ent"`. The
self-hosted Ops Manager 8.0 in `05-ops-manager.yaml` only supports 8.0.x — do not
bump to 8.1/8.2 without first upgrading Ops Manager. If provisioning stalls, check
which versions Ops Manager offers via the UI (port-forward to `:8080` →
Deployment → Modify → Version) and update the manifest to match.

### First capture is slow

The first `/api/inventory/capture` request causes Moondream to load into CPU memory
inside the Ollama pod. Expect ~30 s before the response. Subsequent captures are
faster (~10–15 s).

If the model hasn't finished pulling yet (setup pulls in the background), capture
returns **503**. Check pull progress:

```bash
tail -f /tmp/retail-ollama-pull.log
# or watch from inside the pod:
kubectl -n retail exec deploy/ollama -- ollama list
```

### localtest.me DNS

`*.localtest.me` resolves to `127.0.0.1` via public DNS — no `/etc/hosts` edit
required. If you're on a network that blocks external DNS, add these lines to
`/etc/hosts`:

```
127.0.0.1 frontend.localtest.me
127.0.0.1 powersync.localtest.me
127.0.0.1 s3.localtest.me
127.0.0.1 backend.localtest.me
```

Note this doesn't apply to the app itself — always open the app at
`http://localhost` (see [Open the app](#4-open-the-app)), which resolves
without any `/etc/hosts` entry since it's the literal loopback hostname. The
`*.localtest.me` names above are only needed for the PowerSync WebSocket, the
S3 browser, and the backend Swagger UI.

### kind cluster survives Docker restarts — but pods may not

If Docker Desktop restarts, the kind cluster node container will stop. Restart it:

```bash
docker start retail-stock-take-control-plane
```

Then wait for pods to recover (`make status`). If pods don't come back, re-run
`./scripts/setup.sh` (idempotent).

### PowerSync SQLite persists across page reloads (OPFS)

The browser-side PowerSync database lives in OPFS (Origin Private File System).
After a `make reset` + fresh cluster bring-up, clear it manually via DevTools or the
app's debug panel to avoid stale sync state.

---

## Troubleshooting

### `setup.sh` hangs at "waiting for Ops Manager … to reach Running"

Ops Manager provisioning is the longest step. If it stalls past 15 minutes:

```bash
kubectl -n mongodb describe mongodbopsmanager ops-manager
kubectl -n mongodb get events --sort-by='.lastTimestamp'
kubectl -n mongodb logs deploy/mongodb-kubernetes-operator
```

Common causes:
- Docker Desktop doesn't have enough memory — increase it and re-run `setup.sh`.
- The Ops Manager image version (`spec.version` in `05-ops-manager.yaml`) is not
  available in the MCK image registry. Try a different version string.
- The applicationDatabase is stuck (check its phase separately):
  `kubectl -n mongodb get mongodbopsmanager ops-manager -o jsonpath='{.status}'`

### `setup.sh` hangs at "wait for mongodb-ops-manager-admin-key Secret"

The MCK operator should create this Secret automatically once Ops Manager is Running.
If it never appears:

```bash
kubectl -n mongodb get secrets | grep ops-manager
```

The Secret name may differ from `mongodb-ops-manager-admin-key` in your MCK version.
Find the actual name, then update both the poll in `scripts/setup.sh` and the
`credentials` field in `infra/k8s/mongodb/10-mongodb-enterprise.yaml`, and re-run.

### `setup.sh` hangs at "waiting for replica set to reach Running"

MongoDB Enterprise provisioning runs through the local Ops Manager automation agent.
If it stalls:

```bash
kubectl -n mongodb describe mongodb retail-mongodb
kubectl -n mongodb logs deploy/mongodb-kubernetes-operator
# Ops Manager UI is already on the host — open http://localhost:8080 → Deployment
# to inspect the automation state.
```

If you changed `version` in the MongoDB CR, delete and re-apply it:
```bash
kubectl -n mongodb delete mongodb retail-mongodb
kubectl apply -f infra/k8s/mongodb/10-mongodb-enterprise.yaml
```

### Ingress returns 404 for all routes

ingress-nginx may not have finished starting. Check:

```bash
kubectl -n ingress-nginx rollout status deploy/ingress-nginx-controller
kubectl -n retail get ingress
```

Re-apply the ingress if needed: `kubectl apply -f infra/k8s/ingress/ingress.yaml`

### MongoDB / Ops Manager / S3 not reachable on the host

The host ports (27017 / 8080 / 8333) come from `extraPortMappings` in
`infra/k8s/kind-cluster.yaml`, which are applied **only at cluster creation**. If a
cluster was created before these mappings existed, recreate it:

```bash
make reset && make setup
```

Otherwise confirm the backing NodePort Services exist:

```bash
kubectl -n mongodb get svc retail-mongodb-ext ops-manager-ext
kubectl -n retail  get svc seaweedfs        # type should be NodePort
```

For MongoDB specifically, you **must** use `directConnection=true` in the connection
string — without it the driver tries to reach the replica-set members by their
in-cluster DNS names, which don't resolve from your laptop.

### Backend pod in `CrashLoopBackOff`

Most likely a missing Secret or a failed startup assertion. Check:

```bash
kubectl -n retail logs deploy/retail-stock-take-backend-web-app --previous
```

Common causes:
- `retail-mongodb-uri` Secret missing → `setup.sh` step "connection-string secrets"
  failed. Re-run `setup.sh`.
- `changeStreamPreAndPostImages` not enabled → the post-init Job failed. Check:
  `kubectl -n mongodb logs job/retail-mongodb-postinit`
- SeaweedFS not ready → backend startup probes the S3 bucket. Check:
  `kubectl -n retail logs statefulset/seaweedfs`

### PowerSync won't connect (WebSocket fails in browser)

1. Check `http://powersync.localtest.me/probes/readiness` — must return 200.
2. PowerSync needs a valid JWKS from the backend. Check:
   `curl http://frontend.localtest.me/api/auth/keys`
3. If the backend is down, PowerSync can't validate JWTs. Fix backend first.
4. Check PowerSync logs: `kubectl -n retail logs deploy/retail-stock-take-powersync-web-app`

### `lsof -i :443` reports processes when nothing is blocking

UDP outbound connections (QUIC/HTTP3 from browsers, Slack, Cloudflare WARP) show up
under port 443 in `lsof` output but do **not** bind to the local port. The preflight
script uses `-iTCP:443 -sTCP:LISTEN` to filter these out correctly. If you run
`lsof` manually, use the same flags.

### Capture returns 503

Ollama runs in-cluster — diagnose with:

```bash
kubectl -n retail get pod -l app=ollama          # pod running?
kubectl -n retail logs deploy/ollama             # startup errors?
kubectl -n retail exec deploy/ollama -- ollama list  # models present?
```

If models are missing, re-pull:

```bash
bash scripts/pull-models.sh
```

If the pod is in `CrashLoopBackOff`, increase Docker Desktop's memory allocation
(Settings → Resources → Memory) and restart the pod.

### Helm error: "no Service objects specified with ingress: true"

The `mongodb/web-app` chart requires a service entry with `ingress: true` when
`ingress.enabled=true`. Check `infra/local/*.yaml` — each service with an ingress
must have `ingress: true` on its port entry. The backend intentionally sets
`ingress: false`.
