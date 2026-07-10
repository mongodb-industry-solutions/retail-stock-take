#!/usr/bin/env bash
# Pull CV models into the in-cluster Ollama pod.
# setup.sh runs this automatically; also run manually after a make reset.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib.sh
. "$ROOT/scripts/lib.sh"

NS_APP="${NS_APP:-retail}"
MODEL="${OLLAMA_MODEL:-moondream}"
FALLBACK="${OLLAMA_FALLBACK_MODEL:-qwen2.5vl:7b}"

step "ollama models (in-cluster)"
say "pulling $MODEL (primary)"
kubectl -n "$NS_APP" exec deploy/ollama -- ollama pull "$MODEL"
ok "$MODEL ready"

say "pulling $FALLBACK (fallback)"
kubectl -n "$NS_APP" exec deploy/ollama -- ollama pull "$FALLBACK" && ok "$FALLBACK ready" || warn "$FALLBACK pull failed; continuing"

kubectl -n "$NS_APP" exec deploy/ollama -- ollama list
