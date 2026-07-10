'use client';

import { useState } from 'react';

// Same-origin; Next.js proxies /api/* to the backend at runtime (next.config.mjs).
const OPERATOR = 'demo-operator';

function deviceId() {
  if (typeof window === 'undefined') return 'ssr';
  let id = window.localStorage.getItem('device_id');
  if (!id) {
    id = 'web-' + Math.random().toString(36).slice(2, 10);
    window.localStorage.setItem('device_id', id);
  }
  return id;
}

export function useCapture() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [lastResult, setLastResult] = useState(null);

  async function submit(file) {
    if (!file) return;
    setBusy(true);
    setError(null);

    try {
      const fd = new FormData();
      fd.append('photo', file);
      fd.append('device_id', deviceId());
      fd.append('operator_id', OPERATOR);

      const res = await fetch('/api/inventory/capture', {
        method: 'POST',
        body: fd,
      });

      if (!res.ok) {
        const body = await res.text();
        throw new Error(`${res.status}: ${body}`);
      }

      const data = await res.json();
      setLastResult(data);
      return data;
    } catch (e) {
      setError(String(e?.message || e));
      throw e;
    } finally {
      setBusy(false);
    }
  }

  return { submit, busy, error, lastResult };
}
