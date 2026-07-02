'use client';

import { useQuery } from '@powersync/react';

function parseItems(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  if (typeof value !== 'string') return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function useInventory() {
  const { data, isLoading, error } = useQuery(
    `SELECT id, captured_at, device_id, operator_id, cv_model, items
     FROM inventory_captures
     ORDER BY captured_at DESC`,
  );

  const rows = (data || []).map((row) => ({
    ...row,
    items: parseItems(row.items),
  }));

  return { rows, isLoading, error };
}
