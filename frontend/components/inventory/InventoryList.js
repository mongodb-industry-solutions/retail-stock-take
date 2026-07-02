'use client';

import { Card } from '@leafygreen-ui/card';
import { Badge } from '@leafygreen-ui/badge';
import { Banner } from '@leafygreen-ui/banner';
import { Body, Description } from '@leafygreen-ui/typography';
import { Spinner } from '@leafygreen-ui/loading-indicator/spinner';
import Icon from '@leafygreen-ui/icon';

function fmtDateTime(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const date = d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    return `${date} · ${time}`;
  } catch {
    return iso;
  }
}

function ConfidenceBar({ value }) {
  const pct = typeof value === 'number' ? Math.round(value * 100) : null;
  if (pct === null) {
    return <span className="text-[10px] font-mono" style={{ color: 'var(--mdb-dim)' }}>—</span>;
  }
  return (
    <div className="flex items-center gap-1.5 flex-none">
      <div
        className="w-14 h-1 rounded-full overflow-hidden"
        style={{ backgroundColor: 'var(--mdb-border)' }}
      >
        <div
          className="h-full rounded-full"
          style={{
            width: `${pct}%`,
            background: 'linear-gradient(to right, var(--mdb-green-mid), var(--mdb-green))',
          }}
        />
      </div>
      <span className="text-[10px] font-mono w-7 text-right" style={{ color: 'var(--mdb-muted)' }}>
        {pct}%
      </span>
    </div>
  );
}

export function InventoryList({ rows, isLoading, error, selectedId, onSelect }) {
  if (error) {
    return (
      <Banner variant="danger">{String(error)}</Banner>
    );
  }

  if (isLoading) {
    return (
      <div className="py-6 flex justify-center">
        <Spinner description="Loading captures…" />
      </div>
    );
  }

  if (!rows?.length) {
    return (
      <Card>
        <div className="flex flex-col items-center justify-center py-10 text-center gap-2">
          <Icon glyph="EmptyDatabase" size={32} fill="var(--mdb-muted)" />
          <Body weight="medium">No captures yet</Body>
          <Description>Upload a shelf photo to start.</Description>
        </div>
      </Card>
    );
  }

  return (
    <div className="space-y-2">
      {rows.map((row) => {
        const isSelected = selectedId === row.id;
        return (
          <Card
            key={row.id}
            onClick={() => onSelect?.(row.id)}
            style={
              isSelected
                ? { boxShadow: '0 0 0 2px var(--mdb-border-active)' }
                : undefined
            }
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-2 gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className="w-1.5 h-1.5 rounded-full flex-none"
                  style={{ backgroundColor: isSelected ? 'var(--mdb-green)' : 'var(--mdb-border)' }}
                />
                <Description className="truncate">
                  {fmtDateTime(row.captured_at)} · {row.cv_model}
                </Description>
              </div>
              <Badge variant="lightgray">{row.id?.slice(0, 8)}</Badge>
            </div>

            {/* Items */}
            {row.items.length === 0 ? (
              <Description>no items detected</Description>
            ) : (
              <div className="space-y-1.5">
                {row.items.slice(0, 5).map((item, i) => (
                  <div key={i} className="flex items-center justify-between gap-2">
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <Body className="truncate">{item.name}</Body>
                      <Badge variant="blue">×{item.count}</Badge>
                    </div>
                    <ConfidenceBar value={item.confidence} />
                  </div>
                ))}
                {row.items.length > 5 && (
                  <Description>+{row.items.length - 5} more</Description>
                )}
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}
