// PowerSync connector. The browser talks ONLY to same-origin /api/* (Next.js
// proxies it to the backend at runtime — see next.config.mjs rewrites). The
// PowerSync WebSocket endpoint is the one external URL, and it is delivered at
// runtime in the /api/auth/token response (no NEXT_PUBLIC_* baking).

export class RetailBackendConnector {
  async fetchCredentials() {
    const res = await fetch('/api/auth/token', { method: 'POST' });
    if (!res.ok) {
      throw new Error(`auth/token ${res.status}: ${await res.text()}`);
    }
    const { token, powersync_url } = await res.json();
    if (!powersync_url) {
      throw new Error('auth/token did not return powersync_url');
    }
    return {
      endpoint: powersync_url,
      token,
    };
  }

  async uploadData(database) {
    // Phase 1: writes do not flow through the PowerSync upload queue.
    // Photo uploads go directly to /api/inventory/capture (multipart).
    // Phase 2 will route inventory edits through this hook.
    const tx = await database.getNextCrudTransaction();
    if (!tx) return;
    console.warn('[powersync] unexpected CRUD transaction; draining', tx.crud);
    await tx.complete();
  }
}
