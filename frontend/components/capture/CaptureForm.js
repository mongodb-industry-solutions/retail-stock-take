'use client';

import { useRef, useState } from 'react';
import Button from '@leafygreen-ui/button';
import Icon from '@leafygreen-ui/icon';
import { Banner } from '@leafygreen-ui/banner';
import { Body, Description } from '@leafygreen-ui/typography';
import { useCapture } from './useCapture';

export function CaptureForm() {
  const { submit, busy, error, lastResult } = useCapture();
  const fileInput = useRef(null);
  const [file, setFile] = useState(null);
  const [fileName, setFileName] = useState('');
  const [previewUrl, setPreviewUrl] = useState(null);
  const [dragging, setDragging] = useState(false);

  function applyFile(f) {
    setFile(f);
    setFileName(f.name);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(URL.createObjectURL(f));
  }

  function clearFile() {
    setFile(null);
    setFileName('');
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    if (fileInput.current) fileInput.current.value = '';
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const f = file || fileInput.current?.files?.[0];
    if (!f) return;
    try {
      await submit(f);
      clearFile();
    } catch {
      // error surfaced via hook state
    }
  }

  function handleFileChange(e) {
    const f = e.target.files?.[0];
    if (!f) { clearFile(); return; }
    applyFile(f);
  }

  function handleDrop(e) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (!f || !f.type.startsWith('image/')) return;
    applyFile(f);
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">

      {/* Drop zone */}
      <label
        className={`dropzone ${dragging ? 'drag-over' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <input
          ref={fileInput}
          type="file"
          name="photo"
          accept="image/*"
          capture="environment"
          onChange={handleFileChange}
          disabled={busy}
          className="hidden"
        />

        {previewUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={previewUrl}
            alt="preview"
            className="w-full object-contain"
            style={{
              maxHeight: '220px',
              backgroundColor: 'var(--mdb-surface-2)',
              display: 'block',
            }}
          />
        ) : (
          <div className="flex flex-col items-center justify-center py-10 select-none gap-2">
            <Icon glyph="Camera" size={32} fill="var(--mdb-muted)" />
            <Description>
              {dragging ? 'Drop to load' : 'Drop a shelf photo or click to browse'}
            </Description>
          </div>
        )}
      </label>

      {/* Action row */}
      <div className="flex items-center gap-3">
        {fileName && (
          <Body
            className="truncate flex-1 min-w-0"
            style={{ color: 'var(--mdb-muted)', fontSize: 12 }}
          >
            {fileName}
          </Body>
        )}
        <Button
          type="submit"
          variant="primary"
          disabled={busy || !fileName}
          isLoading={busy}
          loadingText="Analyzing…"
          leftGlyph={<Icon glyph="Camera" />}
          className="ml-auto"
        >
          Capture
        </Button>
      </div>

      {error && <Banner variant="danger">{error}</Banner>}
      {lastResult && !error && (
        <Banner variant="success">
          {lastResult.items?.length || 0} item
          {(lastResult.items?.length || 0) === 1 ? '' : 's'} detected via{' '}
          {lastResult.cv_model}
        </Banner>
      )}
    </form>
  );
}
