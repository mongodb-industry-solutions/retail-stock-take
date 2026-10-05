'use client';

import { useEffect, useState } from 'react';

// Curated shelf gallery for presenters. Reads the sample-shelf list through the
// same-origin /api proxy; when storage is disabled or no samples prefix is
// configured, the backend returns enabled:false and the UI hides the gallery.
export function useSampleShelves() {
  const [enabled, setEnabled] = useState(false);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await fetch('/api/sample-shelves');
        if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
        const data = await res.json();
        if (!active) return;
        setEnabled(!!data?.enabled);
        setItems(Array.isArray(data?.items) ? data.items : []);
      } catch (e) {
        if (!active) return;
        setEnabled(false);
        setItems([]);
        setError(String(e?.message || e));
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  return { enabled, items, loading, error };
}
