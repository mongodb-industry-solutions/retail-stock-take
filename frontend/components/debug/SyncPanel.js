'use client';

import { useEffect, useState } from 'react';
import { usePowerSync, useStatus } from '@powersync/react';
import { Code } from '@leafygreen-ui/code';
import { Badge } from '@leafygreen-ui/badge';
import { Body, Description, Overline, InlineCode } from '@leafygreen-ui/typography';
import Icon from '@leafygreen-ui/icon';

const STAGES = [
  { glyph: 'Camera', label: 'Browser capture', sub: 'POST /api/inventory/capture' },
  { glyph: 'Beaker', label: 'FastAPI + CV model', sub: 'Moondream → JSON' },
  { glyph: 'Database', label: 'MongoDB', sub: 'retail_demo.inventory_captures' },
  { glyph: 'Refresh', label: 'PowerSync', sub: 'global_inventory · WebSocket' },
  { glyph: 'Cloud', label: 'All clients', sub: 'SQLite · live query' },
];

const SYNC_RULE = `SELECT
  _id AS id,
  captured_at,
  device_id,
  operator_id,
  cv_model,
  items,
  status
FROM inventory_captures`;

export function SyncPanel() {
  const status = useStatus();
  const ps = usePowerSync();
  const [rowCount, setRowCount] = useState(null);

  useEffect(() => {
    if (!ps) return undefined;
    let cancelled = false;
    async function tick() {
      try {
        const r = await ps.getAll('SELECT COUNT(*) AS c FROM inventory_captures');
        if (!cancelled) setRowCount(r?.[0]?.c ?? 0);
      } catch {
        if (!cancelled) setRowCount(null);
      }
    }
    tick();
    const id = setInterval(tick, 1500);
    return () => { cancelled = true; clearInterval(id); };
  }, [ps]);

  const connected = !!status?.connected;

  return (
    <div className="space-y-5">

      {/* Pipeline stages */}
      <div>
        {STAGES.map((stage, i) => (
          <div key={i}>
            <div className="flex items-center gap-2.5 py-1">
              <div
                className="w-8 h-8 flex items-center justify-center rounded flex-none"
                style={{
                  backgroundColor: 'var(--mdb-surface-2)',
                  border: '1px solid var(--mdb-border)',
                }}
              >
                <Icon glyph={stage.glyph} fill="var(--mdb-green-mid)" />
              </div>
              <div className="min-w-0">
                <Body weight="medium">{stage.label}</Body>
                <Description className="truncate">{stage.sub}</Description>
              </div>
            </div>
            {i < STAGES.length - 1 && (
              <div style={{ paddingLeft: '15px' }}>
                <div style={{ width: '1px', height: '12px', backgroundColor: 'var(--mdb-border)' }} />
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Status */}
      <div
        className="rounded-lg p-3 space-y-2"
        style={{
          backgroundColor: 'var(--mdb-surface-2)',
          border: '1px solid var(--mdb-border)',
        }}
      >
        <div className="flex justify-between items-center">
          <Description>Status</Description>
          <Badge variant={connected ? 'green' : 'red'}>
            {connected ? 'connected' : 'offline'}
          </Badge>
        </div>
        <div className="flex justify-between items-center">
          <Description>Local rows</Description>
          <Body weight="medium">{rowCount ?? '—'}</Body>
        </div>
        <div className="flex justify-between items-center">
          <Description>Last sync</Description>
          <Body weight="medium">
            {status?.lastSyncedAt
              ? new Date(status.lastSyncedAt).toLocaleTimeString()
              : 'never'}
          </Body>
        </div>
      </div>

      {/* Sync rule */}
      <div className="space-y-2">
        <Overline style={{ color: 'var(--mdb-muted)' }}>Sync rule</Overline>
        <Code language="sql" copyButtonAppearance="none">
          {SYNC_RULE}
        </Code>
        <Description>
          Edition-3 stream <InlineCode>global_inventory</InlineCode>, auto-subscribed.
          Rewrites <InlineCode>_id</InlineCode> → <InlineCode>id</InlineCode> for SQLite
          compatibility.
        </Description>
      </div>
    </div>
  );
}
