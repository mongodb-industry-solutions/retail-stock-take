# Verification

Phase 1 is "done" when this checklist passes on a freshly brought-up kind cluster.

## Automated

```bash
./scripts/verify.sh
```

Runs: ingress/health through the proxy, **host-access ports** (27017/8080/8333),
MongoDB CR status, `changeStreamPreAndPostImages` assertion, JWKS + JWT issuance,
the SeaweedFS storage round-trip, a real photo capture (if a sample exists), and
the retention reconciler. Exits non-zero on any hard failure with debug hints.
Vector search / MongoDBSearch is reported as a non-fatal **WARN** (deferred — it
needs MongoDB 8.2+, while the in-cluster Ops Manager 8.0 provisions 8.0.9-ent).

A convenience for the manual steps below — grab the admin password once:

```bash
ADMIN_PW=$(kubectl -n mongodb get secret retail-mongodb-retail-admin-admin \
  -o jsonpath='{.data.password}' | base64 -d)
```

## Manual (the demo script for a viewer)

### 1. Stack is up

```bash
curl -s http://frontend.localtest.me/api/health | jq
# expect: {"status":"ok","mongo":"ok","storage":"ok","ollama":"ok","powersync":"ok"}

curl -s -o /dev/null -w "%{http_code}\n" http://powersync.localtest.me/probes/liveness
# expect: 200

kubectl -n retail get pods
# expect: backend, frontend, powersync, seaweedfs all Running 1/1
```

### 2. Host access (always-on, no port-forward)

```bash
# MongoDB via Compass / mongosh (directConnection — the RS URI advertises
# in-cluster hostnames that don't resolve from the host):
mongosh "mongodb://admin:${ADMIN_PW}@localhost:27017/?authSource=admin&directConnection=true" \
  --quiet --eval 'db.adminCommand({ping:1})'
# expect: { ok: 1 }

# Ops Manager web UI (login with the ops-manager-admin-secret creds setup printed):
open http://localhost:8080

# S3 (SeaweedFS):
AWS_ACCESS_KEY_ID=retaildemo AWS_SECRET_ACCESS_KEY=retaildemo-secret \
  aws s3 ls s3://store-media/ --endpoint-url http://localhost:8333 --region us-east-1
```

If any of these fail, the kind port-mappings aren't in place — `make reset && make
setup` (they're fixed at cluster creation). See `troubleshooting.md`.

### 3. Pre/post images are enabled

```bash
mongosh "mongodb://admin:${ADMIN_PW}@localhost:27017/?authSource=admin&directConnection=true" \
  --quiet --eval '
  const opts = db.getSiblingDB("retail_demo")
                  .getCollectionInfos({name:"inventory_captures"})[0].options;
  print(JSON.stringify(opts.changeStreamPreAndPostImages));'
# expect: {"enabled":true}
```

### 4. PowerSync sync rules loaded

```bash
kubectl -n retail logs deploy/retail-stock-take-powersync-web-app | grep -i "sync rules\|streams"
# expect: lines indicating sync rules loaded and the global_inventory stream registered
```

### 5. JWT issuance + JWKS (through the proxy)

```bash
curl -s http://frontend.localtest.me/api/auth/keys | jq '.keys[0] | {kty,alg,kid}'
# expect: {"kty":"RSA","alg":"RS256","kid":"retail-key-1"}

curl -s -X POST http://frontend.localtest.me/api/auth/token | jq '.token' | cut -c2-50
# expect: a JWT (eyJ...)
```

### 6. Web app connects

Open http://frontend.localtest.me.

- The sync diagnostics panel shows `connected: true`, `connecting: false`, and a
  `last sync` that updates every few seconds.
- DevTools → Console: `[powersync] connected`, no red errors.
- Application → Storage → Origin Private File System: a local SQLite db is present.
- Network tab: a WebSocket to `powersync.localtest.me` shows `101 Switching Protocols`.

### 7. Load-bearing test — server-initiated sync

```bash
mongosh "mongodb://admin:${ADMIN_PW}@localhost:27017/?authSource=admin&directConnection=true" \
  --quiet --eval '
  db.getSiblingDB("retail_demo").inventory_captures.insertOne({
    _id: "smoke-001",
    captured_at: new Date().toISOString(),
    device_id: "mongosh-test",
    operator_id: "alberto",
    cv_model: "manual",
    status: "ACTIVE",
    items: [{name: "Test SKU", count: 7, confidence: 1.0}]
  })'
```

Within 1–2 s the row appears in the browser inventory list. **If this works,
end-to-end sync is proven** — the CV pipeline is polish on top.

### 8. Full pipeline — photo → CV → MongoDB → sync

In the web UI click **Choose photo** → pick any shelf image → **Capture**.

Within 10–60 s (Ollama time) a new row appears with `cv_model: "qwen2.5vl:7b"` and
a plausible `items` array. Verify:

```bash
mongosh "mongodb://admin:${ADMIN_PW}@localhost:27017/?authSource=admin&directConnection=true" \
  --quiet --eval '
  db.getSiblingDB("retail_demo").inventory_captures
    .find().sort({captured_at: -1}).limit(1).pretty()'
```

### 9. The punchline — offline / reconnect

1. DevTools → Network → throttling → **Offline**.
2. The browser inventory list still renders (read from local SQLite).
3. Insert another row via mongosh (step 7).
4. The browser does **not** see it (offline).
5. Network → **Online**.
6. Within ~3 s the new row appears.

This is what Phase 2 mobile generalizes — same flow, different client.

### 10. Dev tooling (local only)

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://s3.localtest.me/           # → 200
curl -s -o /dev/null -w "%{http_code}\n" http://backend.localtest.me/docs  # → 200
open http://s3.localtest.me/buckets/store-media/   # filer directory tree
open http://backend.localtest.me/docs              # FastAPI Swagger UI
```

## Debug ladder when sync breaks

Most failures are one of these, in roughly this order:

1. `curl http://powersync.localtest.me/probes/readiness` — is PowerSync ready? If
   not: `kubectl -n retail logs deploy/retail-stock-take-powersync-web-app`.
2. After a `mongosh` insert, look in the PowerSync logs for `processed_operation` /
   `Replicated batch`. If none, change streams aren't reaching PowerSync:
   - pre/post images not enabled on the collection (step 3)
   - wrong DB name in the sync rule (`FROM inventory_captures` assumes `retail_demo`)
   - replica-set name mismatch in `PS_DATA_SOURCE_URI`
3. DevTools → Network → confirm the WebSocket. If absent, check the JWT (jwt.io):
   `aud="powersync"` and `exp` in the future.
4. DevTools → Console: uncaught errors from `@powersync/web` / `@powersync/react`?
5. PowerSync logs → "loaded sync rules" on startup; a parse error means malformed YAML.

If step 2 shows replicated ops but they don't reach SQLite, the issue is the client
(schema mismatch, hook not firing). If step 2 shows no ops, the issue is the server
(rule, permissions, change stream).

See `docs/troubleshooting.md` for known failure modes and fixes.
