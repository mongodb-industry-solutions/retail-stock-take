#!/usr/bin/env bash
# Tear down the local kind stack (deletes the cluster and ALL in-cluster state:
# Ops Manager, MongoDB, SeaweedFS, the app, and their volumes).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/lib.sh
. "$ROOT/scripts/lib.sh"

CLUSTER="${KIND_CLUSTER:-retail-stock-take}"

step "deleting kind cluster '$CLUSTER'"
say "removes all in-cluster state + volumes (Ops Manager is in-cluster, so it goes too)"
kind delete cluster --name "$CLUSTER" 2>/dev/null || true
ok "cluster deleted"

step "reset complete"
cat <<EOF

  ${C_BOLD}Kept on disk:${C_RESET}
    .secrets/jwt-private.pem  .secrets/jwt-public.pem   (delete to rotate keys)

  ${C_BOLD}Browser cleanup (manual):${C_RESET}
    DevTools → Application → Storage → "Clear site data" for
    http://frontend.localtest.me — clears the OPFS-backed PowerSync SQLite db
    so the next run doesn't show stale data.

  ${C_GREY}Re-bring-up:${C_RESET} ./scripts/setup.sh

EOF
