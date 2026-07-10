'use client';

import { useEffect, useState } from 'react';
import { useStatus } from '@powersync/react';
import { MongoDBLogoMark } from '@leafygreen-ui/logo';
import { Body, Overline } from '@leafygreen-ui/typography';
import { Badge } from '@leafygreen-ui/badge';
import Button from '@leafygreen-ui/button';
import Icon from '@leafygreen-ui/icon';
import Modal from '@leafygreen-ui/modal';
import { useInventory } from '@/components/inventory/useInventory';
import { CaptureForm } from '@/components/capture/CaptureForm';
import { InventoryList } from '@/components/inventory/InventoryList';
import { MongoDocViewer } from '@/components/inventory/MongoDocViewer';
import { SyncPanel } from '@/components/debug/SyncPanel';
import InfoWizard from '@/components/infoWizard/InfoWizard';
import { useTheme } from './providers';

export default function Home() {
  const { rows, isLoading, error } = useInventory();
  const status = useStatus();
  const { isDark, toggle } = useTheme();
  const [selectedId, setSelectedId] = useState(null);
  const [pipelineOpen, setPipelineOpen] = useState(false);

  useEffect(() => {
    if (!rows?.length) {
      if (selectedId !== null) setSelectedId(null);
      return;
    }
    if (!selectedId || !rows.find((r) => r.id === selectedId)) {
      setSelectedId(rows[0].id);
    }
  }, [rows, selectedId]);

  const selectedDoc = rows?.find((r) => r.id === selectedId) || null;
  const connected = !!status?.connected;

  return (
    <div
      className="flex flex-col h-screen overflow-hidden"
      style={{ backgroundColor: 'var(--mdb-bg)' }}
    >
      {/* ── HEADER ──────────────────────────────────────────────── */}
      <header
        className="flex-none flex items-center justify-between px-6 h-16 border-b"
        style={{ backgroundColor: 'var(--mdb-surface)', borderColor: 'var(--mdb-border)' }}
      >
        <div className="flex items-center gap-3">
          <MongoDBLogoMark color={isDark ? 'green-base' : 'green-dark-2'} height={26} />
          <Body weight="medium" style={{ color: 'var(--mdb-text)', fontSize: 16 }}>
            Stock Take
          </Body>
          <span
            className="hidden sm:block border-l pl-3 ml-1"
            style={{ borderColor: 'var(--mdb-border)' }}
          >
            <Overline style={{ color: 'var(--mdb-muted)' }}>MongoDB · PowerSync</Overline>
          </span>
        </div>
        <div className="flex items-center gap-3">
          <Badge variant="green">MongoDB</Badge>
          <Badge variant={connected ? 'green' : 'red'}>
            {connected ? 'PowerSync · live' : 'PowerSync · offline'}
          </Badge>
          <Button
            size="small"
            leftGlyph={<Icon glyph={isDark ? 'Sun' : 'Moon'} />}
            onClick={toggle}
            aria-label="Toggle color theme"
          >
            {isDark ? 'Light' : 'Dark'}
          </Button>
          <InfoWizard />
        </div>
      </header>

      {/* ── BODY ────────────────────────────────────────────────── */}
      <div className="flex flex-1 overflow-hidden">

        {/* LEFT: scanner panel (60%) */}
        <div
          className="flex flex-col w-[60%] border-r overflow-hidden"
          style={{ borderColor: 'var(--mdb-border)' }}
        >
          {/* Capture */}
          <div
            className="flex-none px-6 py-5 border-b"
            style={{ borderColor: 'var(--mdb-border)' }}
          >
            <Overline style={{ color: 'var(--mdb-muted)', marginBottom: 12, display: 'block' }}>
              Capture
            </Overline>
            <CaptureForm />
          </div>

          {/* Scan log */}
          <div className="flex-1 overflow-y-auto px-6 py-5">
            <div className="flex items-center justify-between mb-3">
              <Overline style={{ color: 'var(--mdb-muted)' }}>Scan Log</Overline>
              <Body style={{ color: 'var(--mdb-muted)', fontSize: 12 }}>
                {rows?.length ?? 0}&nbsp;capture{(rows?.length ?? 0) === 1 ? '' : 's'}
              </Body>
            </div>
            <InventoryList
              rows={rows}
              isLoading={isLoading}
              error={error}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </div>
        </div>

        {/* RIGHT: document panel (40%) */}
        <div
          className="flex flex-col w-[40%] overflow-hidden"
          style={{ backgroundColor: 'var(--mdb-surface-2)' }}
        >
          {/* Right panel header */}
          <div
            className="flex-none flex items-center justify-between px-5 py-4 border-b"
            style={{ borderColor: 'var(--mdb-border)' }}
          >
            <div className="flex items-center gap-3">
              <Overline style={{ color: 'var(--mdb-muted)' }}>Document</Overline>
              {selectedId && (
                <Body style={{ color: 'var(--mdb-muted)', fontSize: 12 }}>
                  {selectedId.slice(0, 8)}…
                </Body>
              )}
            </div>
            <div className="flex items-center gap-2.5">
              <Badge variant={connected ? 'green' : 'red'}>
                {connected ? 'live' : 'offline'}
              </Badge>
              <Button
                size="xsmall"
                leftGlyph={<Icon glyph="Diagram3" />}
                onClick={() => setPipelineOpen(true)}
              >
                Pipeline
              </Button>
            </div>
          </div>

          {/* Document viewer */}
          <div className="flex-1 overflow-auto px-5 py-5">
            <MongoDocViewer
              doc={selectedDoc}
              collectionName="retail_demo.inventory_captures"
            />
          </div>
        </div>
      </div>

      {/* Pipeline modal */}
      <Modal open={pipelineOpen} setOpen={setPipelineOpen} size="default">
        <Overline style={{ color: 'var(--mdb-muted)', marginBottom: 16, display: 'block' }}>
          Data Pipeline
        </Overline>
        <SyncPanel />
      </Modal>
    </div>
  );
}
