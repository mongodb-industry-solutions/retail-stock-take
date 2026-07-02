#!/usr/bin/env bash
# End-to-end smoke test for the kind-based local stack. Exits non-zero if any
# hard check fails (Preview/best-effort items only WARN).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/lib.sh
. "$ROOT/scripts/lib.sh"

NS_DB="mongodb"
NS_APP="retail"
FRONT="http://frontend.localtest.me"
PSYNC="http://powersync.localtest.me"
BACKEND_DEPLOY="deploy/retail-stock-take-backend-web-app"
MONGO_POD="retail-mongodb-0"

PASS=0; FAIL=0
# check <name> <cmd...> : run cmd, PASS on exit 0 else FAIL (counts toward total).
check() { local n="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$n"; PASS=$((PASS+1)); else err "$n"; FAIL=$((FAIL+1)); fi; }
pass()  { ok  "$1"; PASS=$((PASS+1)); }   # record a PASS with a custom message
fail()  { err "$1"; FAIL=$((FAIL+1)); }   # record a FAIL with a custom message
# port_open <port> : succeed if something is listening on localhost:<port>.
port_open() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
http_up()   { [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' "$1" 2>/dev/null)" != "000" ]; }

mongosh_eval() { # <eval-js>  (admin auth, in the mongod pod)
  # MCK writes the actual password it set into retail-mongodb-retail-admin-admin,
  # not into the seed secret (mongodb-admin-password).
  # MCK-managed Enterprise images don't put mongosh in PATH; find the versioned binary.
  local pw; pw="$(kubectl -n "$NS_DB" get secret retail-mongodb-retail-admin-admin -o jsonpath='{.data.password}' 2>/dev/null | base64 -d)"
  local mongosh_bin; mongosh_bin="$(kubectl -n "$NS_DB" exec "$MONGO_POD" -- \
    find /var/lib/mongodb-mms-automation -name mongosh -type f 2>/dev/null | head -1)"
  kubectl -n "$NS_DB" exec "$MONGO_POD" -- "$mongosh_bin" --quiet \
    "mongodb://admin:${pw}@localhost:27017/?authSource=admin&replicaSet=retail-mongodb" \
    --eval "$1" 2>/dev/null | tail -n1 | tr -d '[:space:]'
}

step "ingress / health (through the frontend proxy)"
check "frontend reachable"            curl -s -f "$FRONT/"
check "backend /api/health via proxy" curl -s -f "$FRONT/api/health"
check "powersync liveness"            curl -s -f "$PSYNC/probes/liveness"
check "powersync readiness"           curl -s -f "$PSYNC/probes/readiness"

step "dev tooling (ingress)"
check "SeaweedFS filer UI (s3.localtest.me)"      http_up "http://s3.localtest.me/"
check "backend Swagger UI (backend.localtest.me)" http_up "http://backend.localtest.me/docs"

step "ollama (CV provider, in-cluster)"
check "ollama pod ready" bash -c "kubectl -n $NS_APP get deploy ollama -o jsonpath='{.status.readyReplicas}' 2>/dev/null | grep -q '^1'"
_ollama_model="${OLLAMA_MODEL:-moondream}"
if kubectl -n "$NS_APP" exec deploy/ollama -- ollama list 2>/dev/null | grep -q "$_ollama_model"; then
  pass "$_ollama_model pulled"
else
  warn "$_ollama_model not yet pulled — CV will 503 until pull completes (tail /tmp/retail-ollama-pull.log)"
fi

step "host access (NodePort → kind port-mappings)"
# These require the cluster to have been created with the access port-mappings.
# If they fail, recreate the cluster: make reset && make setup.
check "MongoDB on localhost:27017"      port_open 27017
check "Ops Manager on localhost:8080"   http_up "http://localhost:8080"
check "S3 (SeaweedFS) on localhost:8333" http_up "http://localhost:8333"

step "mongodb (operator-managed)"
check "MongoDB CR Running"   bash -c "[ \"\$(kubectl -n $NS_DB get mongodb retail-mongodb -o jsonpath='{.status.phase}')\" = Running ]"
if [ "$(kubectl -n "$NS_DB" get mongodbsearch retail-search -o jsonpath='{.status.phase}' 2>/dev/null)" = "Running" ]; then
  pass "MongoDBSearch (mongot) Running"
else
  warn "MongoDBSearch not Running (Preview; needs MongoDB 8.2+, deferred on 8.0.9-ent)"
fi

step "change stream pre/post images"
PREPOST=$(mongosh_eval 'const i=db.getSiblingDB("retail_demo").getCollectionInfos({name:"inventory_captures"})[0]||{}; print(((i.options||{}).changeStreamPreAndPostImages||{}).enabled)')
if [ "$PREPOST" = "true" ]; then pass "pre/post images enabled"; else fail "pre/post images not enabled (got '$PREPOST')"; fi

step "self-hosted vector search (mongot)"
VS=$(mongosh_eval '
  const c = db.getSiblingDB("retail_demo").vs_smoke;
  try { c.dropSearchIndex("vs"); } catch(e) {}
  try {
    c.createSearchIndex("vs", "vectorSearch", { fields: [{ type:"vector", path:"e", numDimensions:3, similarity:"cosine" }] });
    print("created");
  } catch(e) { print("err:"+e.codeName); }
')
if [ "$VS" = "created" ]; then pass "\$vectorSearch index created on self-hosted Enterprise"; else warn "vector index not created (got '$VS') — needs mongot/Search (deferred on 8.0.9-ent)"; fi

step "auth (through the proxy)"
check "JWKS returns a key" bash -c "curl -s '$FRONT/api/auth/keys' | grep -q '\"kty\"'"
TOK=$(curl -s -X POST "$FRONT/api/auth/token" 2>/dev/null)
if echo "$TOK" | grep -q '"token"' && echo "$TOK" | grep -q '"powersync_url"'; then
  pass "/api/auth/token returns token + powersync_url"
else
  fail "/api/auth/token missing token/powersync_url"
fi

step "storage adapter round-trip (in backend pod, against SeaweedFS)"
if kubectl -n "$NS_APP" exec "$BACKEND_DEPLOY" -- uv run python -c '
from storage import get_storage_adapter
a = get_storage_adapter()
a.put_object("verify/probe.txt", b"hello", "text/plain")
assert a.get_object("verify/probe.txt") == b"hello"
assert a.head_object("verify/probe.txt") is not None
a.delete_object("verify/probe.txt")
assert a.head_object("verify/probe.txt") is None
print("ok")' >/dev/null 2>&1; then
  pass "put/get/head/delete via the adapter"
else
  fail "storage adapter round-trip failed"
fi

step "capture flow (best-effort; needs Ollama)"
SAMPLE=$(ls scripts/sample-photos/*.{jpg,jpeg,png} 2>/dev/null | head -1 || true)
if [ -n "$SAMPLE" ]; then
  RESP=$(curl -s -o /tmp/retail_capture.json -w '%{http_code}' \
    -F "photo=@${SAMPLE}" -F "device_id=verify" -F "operator_id=verify" -F "store_id=verify-store" \
    "$FRONT/api/inventory/capture" 2>/dev/null)
  if [ "$RESP" = "201" ]; then
    ST=$(grep -o '"status":"[^"]*"' /tmp/retail_capture.json | head -1 | sed 's/.*://;s/"//g')
    if [ "$ST" = "ACTIVE" ]; then pass "capture → 201, status ACTIVE"; else fail "capture status='$ST' (expected ACTIVE)"; fi
  elif [ "$RESP" = "503" ]; then
    warn "capture returned 503 (Ollama/CV unavailable) — run: bash scripts/pull-models.sh"
  else
    fail "capture returned HTTP $RESP"
  fi
else
  warn "no sample photo in scripts/sample-photos/ — skipping capture"
fi

step "retention reconciler (run once)"
check "reconciler run_once exits 0" kubectl -n "$NS_APP" exec "$BACKEND_DEPLOY" -- uv run python -m retention.reconciler

if [ "$FAIL" -gt 0 ]; then
  printf '\n%s%d passed, %d failed%s\n' "$C_RED$C_BOLD" "$PASS" "$FAIL" "$C_RESET"
  cat <<HINT

${C_GREY}Debug hints:${C_RESET}
  host-access fails? recreate to apply kind port-mappings: make reset && make setup
  kubectl -n $NS_APP get pods,svc,ingress
  kubectl -n $NS_APP logs $BACKEND_DEPLOY
  kubectl -n $NS_APP logs deploy/retail-stock-take-powersync-web-app
  kubectl -n $NS_DB describe mongodb retail-mongodb
  curl -s $FRONT/api/health
HINT
  exit 1
else
  printf '\n%s%d passed, 0 failed%s\n' "$C_GREEN$C_BOLD" "$PASS" "$C_RESET"
fi
