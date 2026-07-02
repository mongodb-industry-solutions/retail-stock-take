'use client';

import { Code, Panel } from '@leafygreen-ui/code';
import { Body, Overline } from '@leafygreen-ui/typography';
import Icon from '@leafygreen-ui/icon';

export function MongoDocViewer({ doc, collectionName }) {
  if (!doc) {
    return (
      <div className="flex flex-col items-center justify-center py-16 text-center gap-3">
        <Icon glyph="Database" size={40} fill="var(--mdb-muted)" />
        <Body>Select a capture to inspect its document</Body>
      </div>
    );
  }

  const { id, items: itemsRaw, ...rest } = doc;
  let items = itemsRaw;
  if (typeof itemsRaw === 'string') {
    try { items = JSON.parse(itemsRaw); } catch { items = itemsRaw; }
  }
  const mongoDoc = { _id: id, ...rest, items };

  return (
    <div className="space-y-2">
      <Overline style={{ color: 'var(--mdb-muted)' }}>{collectionName}</Overline>
      <Code language="json" panel={<Panel />}>
        {JSON.stringify(mongoDoc, null, 2)}
      </Code>
    </div>
  );
}
