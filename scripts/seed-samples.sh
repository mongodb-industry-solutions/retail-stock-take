#!/usr/bin/env bash
# Seed the local sample-shelf gallery into SeaweedFS.
#
# The curated gallery served by GET /api/sample-shelves is gated by
# STORAGE_SAMPLES_PREFIX (infra/local/backend.yaml). This uploads the images in
# ./sample-shelves/ to that prefix in the local `store-media` bucket so the local
# demo matches the deployed one (the "Sample" picker appears in the UI).
#
# Idempotent: re-running overwrites the same keys. Called by setup.sh once the
# backend (and therefore the bucket) is up; safe to run standalone afterwards.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Shared color / status helpers (step, say, ok, warn, err, die, hl).
# shellcheck source=scripts/lib.sh
. "$ROOT/scripts/lib.sh"

# Must match infra/local/backend.yaml (STORAGE_* + STORAGE_SAMPLES_PREFIX).
# Overridable via the environment / .env for non-default setups.
SRC_DIR="${SAMPLE_SHELVES_DIR:-$ROOT/sample-shelves}"
BUCKET="${STORAGE_BUCKET:-store-media}"
PREFIX="${STORAGE_SAMPLES_PREFIX:-sample-shelves/}"
ENDPOINT="${STORAGE_ENDPOINT:-http://localhost:8333}"
REGION="${STORAGE_REGION:-us-east-1}"
ACCESS_KEY="${STORAGE_ACCESS_KEY:-retaildemo}"
SECRET_KEY="${STORAGE_SECRET_KEY:-retaildemo-secret}"

export AWS_ACCESS_KEY_ID="$ACCESS_KEY"
export AWS_SECRET_ACCESS_KEY="$SECRET_KEY"
export AWS_DEFAULT_REGION="$REGION"
# Never fall back to instance metadata (there is no IAM role on a laptop).
export AWS_EC2_METADATA_DISABLED=true

if ! command -v aws >/dev/null 2>&1; then
  warn "aws CLI not found — skipping sample-shelf seed (gallery will be empty)"
  exit 0
fi

# Collect top-level images only (skip the README and any subdirectories).
shopt -s nullglob nocaseglob
images=("$SRC_DIR"/*.{jpg,jpeg,png})
shopt -u nullglob nocaseglob

if [ "${#images[@]}" -eq 0 ]; then
  warn "no images in $SRC_DIR — gallery will be empty (add .jpg/.png shelf photos)"
  exit 0
fi

# The backend creates the bucket at startup, but ensure it exists so this is
# safe to run standalone (before the backend is up). Ignore "already exists".
if ! aws --endpoint-url "$ENDPOINT" s3api head-bucket --bucket "$BUCKET" >/dev/null 2>&1; then
  aws --endpoint-url "$ENDPOINT" s3 mb "s3://$BUCKET" >/dev/null 2>&1 || true
fi

say "uploading ${#images[@]} sample shelf image(s) → s3://$BUCKET/$PREFIX"

uploaded=0
for img in "${images[@]}"; do
  name="$(basename "$img")"
  if aws --endpoint-url "$ENDPOINT" s3 cp "$img" "s3://$BUCKET/$PREFIX$name" >/dev/null 2>&1; then
    uploaded=$((uploaded + 1))
  else
    warn "failed to upload $name"
  fi
done

if [ "$uploaded" -gt 0 ]; then
  ok "seeded $uploaded sample shelf image(s) under $PREFIX"
else
  warn "no sample shelf images were uploaded"
fi
