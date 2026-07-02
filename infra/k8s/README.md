# infra/k8s — local kind stack (live)

This is the **local deployment** for retail-stock-take. The whole stack runs on a
kind cluster with **no external cloud dependency** — MongoDB Enterprise is managed
by a **self-hosted Ops Manager** running in the same cluster. `scripts/setup.sh`
applies everything in order; this README documents what each piece is.

## Layout

```
infra/k8s/
  kind-cluster.yaml          # kind config: host port mappings + ingress-ready node
  00-namespaces.yaml         # namespaces: mongodb (operator+OM+DB), retail (app)
  mongodb/
    05-ops-manager.yaml         # MongoDBOpsManager: in-cluster control plane (+ app DB)
    10-mongodb-enterprise.yaml  # MongoDB (Enterprise RS 8.0.9-ent, Ops Manager managed)
    20-mongodbusers.yaml        # MongoDBUser CRs: admin, app, powersync
    30-mongodbsearch.yaml       # MongoDBSearch (mongot) — Preview, DEFERRED (needs 8.2+)
    40-postinit-job.yaml        # creates inventory_captures + changeStreamPreAndPostImages
  access/
    mongodb-nodeport.yaml       # NodePort 30017 -> MongoDB pod-0 (host :27017, Compass)
    opsmanager-nodeport.yaml    # NodePort 30080 -> Ops Manager web UI (host :8080)
  seaweedfs/seaweedfs.yaml      # S3 gateway (StatefulSet + NodePort 30333 + PVC + s3 identities)
  ingress/ingress.yaml          # frontend.localtest.me + powersync.localtest.me
```

The app itself (backend, frontend, powersync) is deployed by `setup.sh` via the
`mongodb/web-app` Helm chart with values in `deploy/local/*.yaml`.

> The `cloud-manager/` directory is **dead/legacy** — leftover from an earlier
> Cloud-Manager-SaaS design. Nothing applies it (`setup.sh` provisions the
> self-hosted Ops Manager via `05-ops-manager.yaml` and writes the
> `ops-manager-project` ConfigMap inline). Safe to delete: `rm -rf infra/k8s/cloud-manager`.

## Bring-up

```bash
./scripts/setup.sh     # no cloud credentials required
./scripts/verify.sh
```

Ops Manager bootstraps itself in-cluster; `setup.sh` creates the admin secret,
waits for it to reach Running, then fetches the orgId from its API to build the
project ConfigMap the MongoDB CR references. See `RUN_LOCAL.md` for timings.

## Always-on host access

kind `extraPortMappings` (in `kind-cluster.yaml`) publish three NodePorts to the
host so you can reach the cluster directly — **these are fixed at cluster creation**:

| Host port | NodePort | Service | Use |
|---|---|---|---|
| 27017 | 30017 | `retail-mongodb-ext` (ns mongodb) | Compass / mongosh (`directConnection=true`) |
| 8080  | 30080 | `ops-manager-ext` (ns mongodb)    | Ops Manager web UI |
| 8333  | 30333 | `seaweedfs` (ns retail, NodePort)  | S3 API (AWS CLI / Cyberduck) |

The MongoDB / Ops Manager NodePorts are **separate** Services that select the
operator-owned pods (we never modify the operator's headless Services). The MongoDB
one pins to `retail-mongodb-0` for a stable single-node endpoint.

## Key facts / gotchas

- **MongoDBSearch is Preview and deferred** — it needs MongoDB 8.2+, but the
  in-cluster Ops Manager 8.0 provisions 8.0.9-ent. The CR is applied (ready for an
  Ops Manager upgrade) but not expected to run; `verify.sh` WARNs. Confirm CR
  fields with `kubectl explain mongodb.spec` / `mongodbsearch.spec`.
- **Self-hosted Ops Manager** is the control plane (in-cluster, ~4 GB) and the
  heaviest component. The `mongod` data plane runs alongside it in kind.
- **Footprint** ≈ 16–24 GB RAM (Ops Manager + its app DB + operator + Enterprise
  mongod + SeaweedFS + Ollama + app). `preflight.sh` warns under 16 GB; 24 GB
  recommended.
- **Ollama** runs in-cluster (`ollama/ollama.yaml`): Deployment + 10 Gi PVC + ClusterIP
  Service. `OLLAMA_ORIGINS` is baked in so the Host-header check never fires. No host
  Ollama process is required.
- The `mongodb/web-app` chart names Services `<release>-web-app-80` — referenced by
  the ingress and by inter-service env (`BACKEND_URL`, `PS_JWKS_URL`, …).

## Cloud (Kanopy) counterpart

The same app images + the same `mongodb/web-app` chart deploy to Kanopy via
`.drone.yml`, with MongoDB→Atlas and storage→AWS S3. That path is **internal
maintenance only** — see `INTERNAL_DEPLOY_MAINTENANCE.md`.
