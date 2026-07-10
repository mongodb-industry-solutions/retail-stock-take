# PowerSync service config

Two files; both mounted into the PowerSync container at `/config/`.

## `powersync.yaml`

Top-level service config. References `sync-rules.yaml` via `sync_config.path`.

- `replication`: MongoDB source. `post_images: auto_configure` lets PowerSync
  enable `changeStreamPreAndPostImages` on watched collections (the post-init Job,
  `infra/k8s/mongodb/40-postinit-job.yaml`, also enables it defensively, and the
  backend asserts it at startup).
- `storage`: bucket storage on the same MongoDB cluster, separate `powersync`
  database.
- `client_auth`: pulls JWKS from the backend at `PS_JWKS_URL`. Audience must
  match `PS_JWT_AUDIENCE` and the `aud` claim in tokens FastAPI issues.

Env vars (prefix `PS_`) are substituted via the `!env VARNAME` YAML tag.

## `sync-rules.yaml`

Edition-3 streams syntax. One global stream `global_inventory` projects
`_id AS id` to satisfy PowerSync's PK convention. To partition later,
add a parameter query like `SELECT request.jwt() ->> 'store_id' AS store_id`.

## Iterating

Both files are mounted from the `powersync-config` ConfigMap and read on pod start.
After editing either, refresh the ConfigMap and restart the pod:

```bash
kubectl -n retail create configmap powersync-config \
  --from-file=powersync.yaml=powersync/powersync.yaml \
  --from-file=sync-rules.yaml=powersync/sync-rules.yaml \
  --dry-run=client -o yaml | kubectl apply -f -
kubectl -n retail rollout restart deploy/retail-stock-take-powersync-web-app
kubectl -n retail logs -f deploy/retail-stock-take-powersync-web-app
```

Look for `loaded sync rules` and `connected to <mongo-uri>` in the logs.
