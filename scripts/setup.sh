#!/usr/bin/env bash
# One-shot local bring-up on a kind cluster:
#   ingress-nginx + MCK operator + self-hosted Ops Manager (local control plane) +
#   MongoDB Enterprise replica set + SeaweedFS (S3) + backend + frontend +
#   PowerSync (mongodb/web-app chart), plus always-on host access to MongoDB,
#   Ops Manager and the S3 API.
#
# Idempotent: re-running after a partial failure resumes (existing resources are
# reused, secrets are not regenerated).
#
# At the end it prints ready-to-use access details (app URL, a Compass connection
# string, the Ops Manager URL + login, and the S3 endpoint + keys).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Shared color / spinner / status helpers (step, say, ok, warn, err, die, hl,
# spin_wait). See scripts/lib.sh.
# shellcheck source=scripts/lib.sh
. "$ROOT/scripts/lib.sh"

# Load .env if present (optional overrides — no credentials required).
# Create one from .env.example: cp .env.example .env
if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a; . ./.env; set +a
fi

# ---- configuration (override via .env or the environment) -----------------
CLUSTER="${KIND_CLUSTER:-retail-stock-take}"
NS_DB="mongodb"                                   # operator + MongoDB + Ops Manager
NS_APP="retail"                                   # backend/frontend/powersync + SeaweedFS
MCK_VERSION="${MCK_VERSION:-1.8.1}"
WEBAPP_CHART_VERSION="${WEBAPP_CHART_VERSION:-4.30.0}"
INGRESS_NGINX_REF="${INGRESS_NGINX_REF:-controller-v1.11.3}"
OM_ADMIN_USER="${OM_ADMIN_USER:-admin@retail-demo.local}"

# Host ports published by kind (must match nodePort mappings in
# infra/k8s/kind-cluster.yaml + the NodePort Services in infra/k8s/access/).
HOST_MONGO_PORT=27017
HOST_OM_PORT=8080
HOST_S3_PORT=8333

# ---- small helpers --------------------------------------------------------
# Decode a key from a Kubernetes Secret (base64 -> plaintext).
ksecret_val() { kubectl -n "$1" get secret "$2" -o jsonpath="{.data.$3}" 2>/dev/null | base64 -d; }

# Create a {password: <random>} Secret if it doesn't already exist.
ensure_password_secret() { # <ns> <name>
  local ns="$1" name="$2"
  if ! kubectl -n "$ns" get secret "$name" >/dev/null 2>&1; then
    kubectl -n "$ns" create secret generic "$name" \
      --from-literal="password=$(openssl rand -base64 24 | tr -d '/+=')"
    say "created secret $ns/$name"
  fi
}

# ===========================================================================
step "preflight"
bash scripts/preflight.sh

# ===========================================================================
step "kind cluster ($CLUSTER)"
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  ok "cluster already exists"
else
  # The cluster config publishes host ports 80/443 (ingress) + 27017/8080/8333
  # (MongoDB / Ops Manager / S3). These mappings only take effect at creation.
  kind create cluster --name "$CLUSTER" --config infra/k8s/kind-cluster.yaml
  ok "cluster created"
fi
kubectl config use-context "kind-$CLUSTER" >/dev/null

# ===========================================================================
step "namespaces"
kubectl apply -f infra/k8s/00-namespaces.yaml

# ===========================================================================
step "ingress-nginx (kind provider)"
kubectl apply -f "https://raw.githubusercontent.com/kubernetes/ingress-nginx/${INGRESS_NGINX_REF}/deploy/static/provider/kind/deploy.yaml"
kubectl -n ingress-nginx rollout status deploy/ingress-nginx-controller --timeout=180s || \
  warn "ingress-nginx not ready yet — continuing (re-run setup.sh if routing fails)"

# ===========================================================================
step "MCK operator (v$MCK_VERSION)"
# Use alias 'mck' for the public MCK registry — 'mongodb' may already point to the
# internal 10gen helm charts (https://10gen.github.io/helm-charts), in which case
# the add silently no-ops. 'mongodb-webapp' stays on the 10gen URL for the
# web-app chart used to deploy backend/frontend/powersync.
helm repo add mck https://mongodb.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add mongodb-webapp https://10gen.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null
helm upgrade --install mongodb-kubernetes-operator mck/mongodb-kubernetes \
  --namespace "$NS_DB" --version "$MCK_VERSION" --wait
ok "operator installed"

# ===========================================================================
step "Ops Manager admin credentials"
if ! kubectl -n "$NS_DB" get secret ops-manager-admin-secret >/dev/null 2>&1; then
  # Ops Manager enforces password complexity (upper+lower+digit+symbol) and
  # requires FirstName/LastName on the initial admin user.
  OM_PW=$(python3 -c "import secrets,string; c=string.ascii_uppercase+string.ascii_lowercase+string.digits+'@#!%'; p=secrets.choice(string.ascii_uppercase)+secrets.choice(string.ascii_lowercase)+secrets.choice(string.digits)+secrets.choice('@#!%')+''.join(secrets.choice(c) for _ in range(20)); print(p)")
  kubectl -n "$NS_DB" create secret generic ops-manager-admin-secret \
    --from-literal=Username="$OM_ADMIN_USER" \
    --from-literal=Password="$OM_PW" \
    --from-literal=FirstName="Admin" \
    --from-literal=LastName="User"
  ok "created ops-manager-admin-secret (user: $OM_ADMIN_USER)"
else
  ok "ops-manager-admin-secret already present"
fi

# ===========================================================================
step "Ops Manager (self-hosted control plane — first run ~10–15 min)"
kubectl apply -f infra/k8s/mongodb/05-ops-manager.yaml
# Poll both the application DB and the Ops Manager app until each reports Running.
# om_ready() refreshes the phase globals that om_status()/om_failed() then read.
OM_FAILS=0
om_ready() {
  OM_APPDB="$(kubectl -n "$NS_DB" get opsmanager ops-manager -o jsonpath='{.status.applicationDatabase.phase}' 2>/dev/null || true)"
  OM_WEB="$(kubectl -n "$NS_DB" get opsmanager ops-manager -o jsonpath='{.status.opsManager.phase}' 2>/dev/null || true)"
  [ "$OM_APPDB" = "Running" ] && [ "$OM_WEB" = "Running" ]
}
om_status() { printf 'appdb=%-9s web=%-9s' "${OM_APPDB:-…}" "${OM_WEB:-…}"; }
# Bail out only after several consecutive Failed observations (transient Failed
# is normal early in reconcile).
om_failed() { if [ "${OM_WEB:-}" = "Failed" ]; then OM_FAILS=$((OM_FAILS+1)); else OM_FAILS=0; fi; [ "$OM_FAILS" -ge 3 ]; }
rc=0; spin_wait "Ops Manager" 1800 5 --status om_status --abort om_failed -- om_ready || rc=$?
case "$rc" in
  0) ;;
  3) die "Ops Manager entered Failed — kubectl -n $NS_DB describe opsmanager ops-manager" ;;
  *) die "Timed out waiting for Ops Manager — kubectl -n $NS_DB describe opsmanager ops-manager" ;;
esac

# ===========================================================================
# Once Ops Manager is Running the operator publishes the API key Secret
# 'mongodb-ops-manager-admin-key' (publicKey + privateKey) the MongoDB CR needs.
step "Ops Manager API key Secret"
admin_key_ready() { kubectl -n "$NS_DB" get secret mongodb-ops-manager-admin-key >/dev/null 2>&1; }
rc=0; spin_wait "mongodb-ops-manager-admin-key" 300 5 -- admin_key_ready || rc=$?
[ "$rc" = 0 ] || die "API key Secret not created after 5m — kubectl -n $NS_DB logs deploy/mongodb-kubernetes-operator"

# ===========================================================================
step "Ops Manager project ConfigMap"
# Fetch the orgId from the running Ops Manager public API (digest auth with the
# operator-created admin key) and bake it into the project ConfigMap the
# MongoDB CR references.
OM_PUB=$(ksecret_val "$NS_DB" mongodb-ops-manager-admin-key publicKey)
OM_PRIV=$(ksecret_val "$NS_DB" mongodb-ops-manager-admin-key privateKey)
say "querying Ops Manager API for orgId…"
kubectl -n "$NS_DB" port-forward svc/ops-manager-svc 18080:8080 >/dev/null 2>&1 &
PF_PID=$!
sleep 4
OM_ORG_ID=$(curl -s --digest -u "$OM_PUB:$OM_PRIV" \
  "http://localhost:18080/api/public/v1.0/orgs" \
  | python3 -c "import sys,json; orgs=json.load(sys.stdin).get('results',[]); print(orgs[0]['id'] if orgs else '')" 2>/dev/null)
kill $PF_PID 2>/dev/null; wait $PF_PID 2>/dev/null || true
[ -n "$OM_ORG_ID" ] || die "could not retrieve orgId from Ops Manager API"
ok "orgId: $OM_ORG_ID"
kubectl -n "$NS_DB" create configmap ops-manager-project \
  --from-literal=baseUrl="http://ops-manager-svc.mongodb.svc.cluster.local:8080" \
  --from-literal=projectName="retail-stock-take" \
  --from-literal=orgId="$OM_ORG_ID" \
  --dry-run=client -o yaml | kubectl apply -f -

# ===========================================================================
step "JWT keypair (.secrets)"
mkdir -p .secrets
if [ ! -f .secrets/jwt-private.pem ]; then
  openssl genrsa -out .secrets/jwt-private.pem 2048
  openssl rsa -in .secrets/jwt-private.pem -pubout -out .secrets/jwt-public.pem
  chmod 600 .secrets/jwt-private.pem
  ok "generated RS256 keypair"
else
  ok "reusing existing RS256 keypair"
fi
kubectl -n "$NS_APP" create secret generic jwt-keys \
  --from-file=jwt-private.pem=.secrets/jwt-private.pem \
  --from-file=jwt-public.pem=.secrets/jwt-public.pem \
  --dry-run=client -o yaml | kubectl apply -f -

# ===========================================================================
step "MongoDB user password secrets"
# Seed secrets consumed by the MongoDBUser CRs. The operator later publishes the
# ACTUAL credentials it set into auto-generated secrets named
# retail-mongodb-<user>-admin (read from those below).
ensure_password_secret "$NS_DB" mongodb-admin-password
ensure_password_secret "$NS_DB" mongodb-app-password
ensure_password_secret "$NS_DB" mongodb-powersync-password

# ===========================================================================
step "MongoDB Enterprise replica set + users (Ops Manager managed)"
kubectl apply -f infra/k8s/mongodb/10-mongodb-enterprise.yaml
kubectl apply -f infra/k8s/mongodb/20-mongodbusers.yaml
RS_FAILS=0
rs_ready()  { RS_PHASE="$(kubectl -n "$NS_DB" get mongodb retail-mongodb -o jsonpath='{.status.phase}' 2>/dev/null || true)"; [ "$RS_PHASE" = "Running" ]; }
rs_status() { printf 'phase=%s' "${RS_PHASE:-…}"; }
rs_failed() { if [ "${RS_PHASE:-}" = "Failed" ]; then RS_FAILS=$((RS_FAILS+1)); else RS_FAILS=0; fi; [ "$RS_FAILS" -ge 6 ]; }
rc=0; spin_wait "replica set (provisioning via Ops Manager)" 900 5 --status rs_status --abort rs_failed -- rs_ready || rc=$?
case "$rc" in
  0) ;;
  3) die "MongoDB replica set Failed — kubectl -n $NS_DB describe mongodb retail-mongodb" ;;
  *) die "Timed out waiting for the replica set — kubectl -n $NS_DB describe mongodb retail-mongodb" ;;
esac

# MongoDBSearch (mongot / Vector Search) is a Preview feature that needs MongoDB
# 8.2+. The local Ops Manager (8.0) provisions 8.0.9-ent, so Search is DEFERRED:
# we apply the CR (so it's ready once Ops Manager is upgraded) but don't block on
# it. verify.sh reports it as a non-fatal WARN.
step "MongoDBSearch (Preview — deferred on MongoDB 8.0.x)"
kubectl apply -f infra/k8s/mongodb/30-mongodbsearch.yaml
warn "MongoDBSearch needs MongoDB 8.2+; not expected to run on 8.0.9-ent (deferred)"

# ===========================================================================
step "connection-string secrets ($NS_APP)"
# Read passwords from the operator-generated secrets (they hold what was actually
# set in MongoDB), not the seed secrets, so the URIs always authenticate.
MDB_HOST="retail-mongodb-svc.${NS_DB}.svc.cluster.local:27017"
APP_PW="$(ksecret_val "$NS_DB" retail-mongodb-retail-app-admin password)"
PS_PW="$(ksecret_val "$NS_DB" retail-mongodb-retail-powersync-admin password)"
kubectl -n "$NS_APP" create secret generic retail-mongodb-uri \
  --from-literal=MONGODB_URI="mongodb://app:${APP_PW}@${MDB_HOST}/retail_demo?authSource=admin&replicaSet=retail-mongodb" \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS_APP" create secret generic retail-powersync-secrets \
  --from-literal=PS_DATA_SOURCE_URI="mongodb://powersync:${PS_PW}@${MDB_HOST}/retail_demo?authSource=admin&replicaSet=retail-mongodb" \
  --from-literal=PS_MONGO_URI="mongodb://powersync:${PS_PW}@${MDB_HOST}/powersync?authSource=admin&replicaSet=retail-mongodb" \
  --dry-run=client -o yaml | kubectl apply -f -
ok "wrote retail-mongodb-uri + retail-powersync-secrets"

# ===========================================================================
step "collection + changeStreamPreAndPostImages (post-init Job)"
kubectl -n "$NS_DB" delete job retail-mongodb-postinit --ignore-not-found >/dev/null
kubectl apply -f infra/k8s/mongodb/40-postinit-job.yaml
postinit_done() { [ "$(kubectl -n "$NS_DB" get job retail-mongodb-postinit -o jsonpath='{.status.succeeded}' 2>/dev/null || echo 0)" = "1" ]; }
rc=0; spin_wait "post-init Job" 300 5 -- postinit_done || rc=$?
[ "$rc" = 0 ] || die "post-init Job did not complete — kubectl -n $NS_DB logs job/retail-mongodb-postinit"

# ===========================================================================
step "SeaweedFS (S3 object store)"
kubectl apply -f infra/k8s/seaweedfs/seaweedfs.yaml
sweed_ready() { [ "$(kubectl -n "$NS_APP" get statefulset seaweedfs -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)" = "1" ]; }
rc=0; spin_wait "SeaweedFS" 180 3 -- sweed_ready || rc=$?
[ "$rc" = 0 ] || warn "SeaweedFS not ready — kubectl -n $NS_APP logs statefulset/seaweedfs"

# ===========================================================================
step "host access (NodePort services)"
# Always-on access from the laptop. SeaweedFS's NodePort is in seaweedfs.yaml
# (applied above); these two expose MongoDB and the Ops Manager web UI without
# touching the operator-owned headless Services.
kubectl apply -f infra/k8s/access/mongodb-nodeport.yaml
kubectl apply -f infra/k8s/access/opsmanager-nodeport.yaml
ok "MongoDB :$HOST_MONGO_PORT · Ops Manager :$HOST_OM_PORT · S3 :$HOST_S3_PORT exposed to host"

# ===========================================================================
step "PowerSync config (ConfigMap)"
kubectl -n "$NS_APP" create configmap powersync-config \
  --from-file=powersync.yaml=powersync/powersync.yaml \
  --from-file=sync-rules.yaml=powersync/sync-rules.yaml \
  --dry-run=client -o yaml | kubectl apply -f -

# ===========================================================================
step "ollama (in-cluster)"
# Migrate: ExternalName Service from a previous setup can't be updated to ClusterIP
# in-place — delete it first (idempotent).
kubectl -n "$NS_APP" delete svc ollama --ignore-not-found=true >/dev/null
kubectl apply -f infra/k8s/ollama/ollama.yaml
ollama_ready() { kubectl -n "$NS_APP" get deploy ollama -o jsonpath='{.status.readyReplicas}' 2>/dev/null | grep -q "^1"; }
spin_wait "ollama" 300 5 -- ollama_ready || warn "ollama pod not ready — check kubectl -n $NS_APP logs deploy/ollama"

# ===========================================================================
step "build images + load into kind"
docker build -t retail-stock-take-backend:local  -f backend/Dockerfile .
docker build -t retail-stock-take-frontend:local -f frontend/Dockerfile .
kind load docker-image retail-stock-take-backend:local  --name "$CLUSTER"
kind load docker-image retail-stock-take-frontend:local --name "$CLUSTER"
ok "images built + loaded"

# ===========================================================================
step "deploy app (mongodb/web-app chart)"
for svc in backend frontend powersync; do
  helm upgrade --install "retail-stock-take-$svc" mongodb-webapp/web-app \
    --version "$WEBAPP_CHART_VERSION" -n "$NS_APP" -f "infra/local/$svc.yaml" >/dev/null
  say "released retail-stock-take-$svc"
done

# ===========================================================================
step "ingress"
kubectl apply -f infra/k8s/ingress/ingress.yaml

# ===========================================================================
step "wait for app rollouts"
for svc in backend frontend powersync; do
  dep="retail-stock-take-$svc-web-app"
  svc_ready() { local r; r="$(kubectl -n "$NS_APP" get deploy "$dep" -o jsonpath='{.status.readyReplicas}' 2>/dev/null)"; [ "${r:-0}" -ge 1 ]; }
  rc=0; spin_wait "$svc" 180 3 -- svc_ready || rc=$?
  [ "$rc" = 0 ] || warn "$svc not ready — kubectl -n $NS_APP logs deploy/$dep"
done

# ===========================================================================
step "ollama models (in-cluster)"
if kubectl -n "$NS_APP" exec deploy/ollama -- ollama list 2>/dev/null | grep -q "${OLLAMA_MODEL:-moondream}"; then
  ok "${OLLAMA_MODEL:-moondream} already present"
else
  ( "$ROOT/scripts/pull-models.sh" ) >/tmp/retail-ollama-pull.log 2>&1 &
  say "model pull running in the background → /tmp/retail-ollama-pull.log"
fi

# ===========================================================================
# Gather live credentials and Ollama status for the access summary.
ADMIN_PW="$(ksecret_val "$NS_DB" retail-mongodb-retail-admin-admin password || true)"
OM_USER="$(ksecret_val "$NS_DB" ops-manager-admin-secret Username || echo "$OM_ADMIN_USER")"
OM_PW="$(ksecret_val "$NS_DB" ops-manager-admin-secret Password || true)"
MONGO_URI="mongodb://admin:${ADMIN_PW:-<password>}@localhost:${HOST_MONGO_PORT}/?authSource=admin&directConnection=true"
if kubectl -n "$NS_APP" exec deploy/ollama -- ollama list 2>/dev/null | grep -q "${OLLAMA_MODEL:-moondream}"; then
  OLLAMA_SUMMARY="${C_GREEN}ready${C_RESET} — ${OLLAMA_MODEL:-moondream} present in cluster"
else
  OLLAMA_SUMMARY="${C_YELLOW}downloading${C_RESET} — ${OLLAMA_MODEL:-moondream} still pulling (tail /tmp/retail-ollama-pull.log)"
fi

step "ready — local stack is up"
cat <<EOF

  ${C_BOLD}1) Web app${C_RESET}
     $(hl "http://localhost")
     (use "localhost", not frontend.localtest.me — Chrome only treats
     localhost/127.0.0.1/https as a secure context, which PowerSync's
     local database needs; backend is internal-only, reached via the
     frontend /api proxy)

  ${C_BOLD}2) MongoDB — Compass / mongosh${C_RESET}
     Paste this connection string into Compass:
       $(hl "$MONGO_URI")
     Data lives in db ${C_CYAN}retail_demo${C_RESET}, collection ${C_CYAN}inventory_captures${C_RESET}.

  ${C_BOLD}3) Ops Manager — web UI${C_RESET}
     $(hl "http://localhost:${HOST_OM_PORT}")
     user: ${C_CYAN}${OM_USER}${C_RESET}   password: ${C_CYAN}${OM_PW:-<see ops-manager-admin-secret>}${C_RESET}

  ${C_BOLD}4) S3 (SeaweedFS) — AWS CLI / Cyberduck${C_RESET}
     endpoint: $(hl "http://localhost:${HOST_S3_PORT}")   bucket: ${C_CYAN}store-media${C_RESET}  (path-style)
     access key: ${C_CYAN}retaildemo${C_RESET}   secret key: ${C_CYAN}retaildemo-secret${C_RESET}
     e.g.  AWS_ACCESS_KEY_ID=retaildemo AWS_SECRET_ACCESS_KEY=retaildemo-secret \\
           aws s3 ls s3://store-media/ --endpoint-url http://localhost:${HOST_S3_PORT} --region us-east-1

  ${C_BOLD}5) Dev tooling (local only)${C_RESET}
     SeaweedFS filer UI — browse the store-media bucket in the browser:
       $(hl "http://s3.localtest.me/buckets/store-media/")   (no login needed)
     Backend API docs (Swagger / ReDoc):
       $(hl "http://backend.localtest.me/docs")
       $(hl "http://backend.localtest.me/redoc")

  ${C_GREY}Ollama / CV:${C_RESET}  ${OLLAMA_SUMMARY}

  ${C_GREY}Smoke test:${C_RESET} ./scripts/verify.sh      ${C_GREY}Status:${C_RESET} make status      ${C_GREY}Tear down:${C_RESET} ./scripts/reset.sh

EOF
