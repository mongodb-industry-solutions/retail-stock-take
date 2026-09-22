'use client';

import { useRef, useState } from 'react';
import Button from '@leafygreen-ui/button';
import Icon from '@leafygreen-ui/icon';
import { Banner } from '@leafygreen-ui/banner';
import { Body, Description } from '@leafygreen-ui/typography';
import { useCapture } from './useCapture';
import { useSampleShelves } from './useSampleShelves';

export function CaptureForm() {
  const { submit, busy, error, lastResult } = useCapture();
  const samples = useSampleShelves();
  const fileInput = useRef(null);
  const [file, setFile] = useState(null);
  const [fileName, setFileName] = useState('');
  const [previewUrl, setPreviewUrl] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [pickingName, setPickingName] = useState(null);
  const [sampleError, setSampleError] = useState(null);

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

  async function pickSample(name) {
    setSampleError(null);
    setPickingName(name);
    try {
      const res = await fetch(`/api/sample-shelves/image?name=${encodeURIComponent(name)}`);
      if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
      const blob = await res.blob();
      const f = new File([blob], name, { type: blob.type || 'image/jpeg' });
      applyFile(f); // show in the dropzone
      await submit(f); // same capture -> CV -> store -> sync path
      clearFile();
    } catch (e) {
      setSampleError(String(e?.message || e));
    } finally {
      setPickingName(null);
    }
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

      {/* Curated sample shelves (cloud only) */}
      {samples.enabled && (
        <div
          className="pt-2 border-t"
          style={{ borderColor: 'var(--mdb-border)' }}
        >
          <Description style={{ marginBottom: 8 }}>Or pick a sample shelf</Description>
          {sampleError && <Banner variant="danger">{sampleError}</Banner>}
          {samples.error && <Banner variant="warning">{samples.error}</Banner>}
          {samples.loading ? (
            <Description style={{ color: 'var(--mdb-muted)' }}>Loading…</Description>
          ) : (
            <div className="grid grid-cols-3 gap-2">
              {samples.items.map((s) => (
                <button
                  key={s.name}
                  type="button"
                  onClick={() => pickSample(s.name)}
                  disabled={busy || pickingName !== null}
                  className="rounded overflow-hidden focus:outline-none disabled:opacity-60"
                  style={{ border: '1px solid var(--mdb-border)' }}
                  title={s.name}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={`/api/sample-shelves/image?name=${encodeURIComponent(s.name)}`}
                    alt={s.name}
                    className="w-full aspect-square object-cover"
                    style={{ display: 'block' }}
                  />
                </button>
              ))}
            </div>
          )}
        </div>
      )}

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
