#!/usr/bin/env bash
# Preflight checks for the kind-based local stack: verifies the required CLI
# tools, that the ingress ports are free, and that there's enough RAM.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib.sh
. "$ROOT/scripts/lib.sh"

step "preflight checks"

# ---- required tooling -----------------------------------------------------
command -v docker  >/dev/null 2>&1 || die "docker not found"
docker info        >/dev/null 2>&1 || die "docker daemon not running"
ok "docker daemon reachable"

command -v kind    >/dev/null 2>&1 || die "kind not found (https://kind.sigs.k8s.io)"
command -v kubectl >/dev/null 2>&1 || die "kubectl not found"
command -v helm    >/dev/null 2>&1 || die "helm not found"
command -v openssl >/dev/null 2>&1 || die "openssl not found"
ok "kind + kubectl + helm + openssl"

# Ollama runs in-cluster (infra/k8s/ollama/ollama.yaml) — no host Ollama required.

# ---- host ports -----------------------------------------------------------
# kind maps host :80/:443 (ingress) and :27017/:8080/:8333 (MongoDB / Ops
# Manager / S3). They must be free at cluster-creation time. We only enforce
# 80/443 (the ingress ports kind needs to create the node); the others surface
# as a clear kind error if taken. Skip entirely when the cluster already exists
# (the listener IS the kind node and the check would be a false positive).
CLUSTER="${KIND_CLUSTER:-retail-stock-take}"
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER"; then
  ok "host ports (skipped — kind cluster already exists)"
else
  for port in 80 443; do
    if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$port" -P -sTCP:LISTEN >/dev/null 2>&1; then
      die "port $port is in use — kind ingress needs it (stop the process using it)"
    fi
  done
  ok "ports 80, 443 free"
  # Soft check for the always-on access ports (non-fatal — kind will error if taken).
  for port in 27017 8080 8333; do
    if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$port" -P -sTCP:LISTEN >/dev/null 2>&1; then
      warn "port $port is in use — host access mapping for it will fail (free it or edit kind-cluster.yaml)"
    fi
  done
fi

# ---- RAM ------------------------------------------------------------------
# Ops Manager (~4 GB) + its app DB + operator + Enterprise mongod + SeaweedFS +
# app services. 24 GB recommended; 16 GB is the practical floor.
TOTAL_GB=0
if [ "$(uname)" = "Darwin" ]; then
  TOTAL_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
elif [ -r /proc/meminfo ]; then
  TOTAL_GB=$(( $(awk '/MemTotal/ {print $2}' /proc/meminfo) / 1048576 ))
fi
if [ "$TOTAL_GB" -gt 0 ] && [ "$TOTAL_GB" -lt 16 ]; then
  warn "only ${TOTAL_GB}GB RAM — 24 GB recommended (Ops Manager alone needs ~4 GB)"
elif [ "$TOTAL_GB" -gt 0 ] && [ "$TOTAL_GB" -lt 24 ]; then
  warn "${TOTAL_GB}GB RAM — may be tight with Ops Manager; 24 GB recommended"
elif [ "$TOTAL_GB" -gt 0 ]; then
  ok "${TOTAL_GB}GB RAM"
fi

ok "preflight complete"
