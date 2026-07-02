import { column, Schema, Table } from '@powersync/web';

// Single source of truth for the PowerSync sync schema.
// (Folded in from the former packages/schema workspace; Phase 2 mobile will
// import this same module.)
//
// MongoDB convention: documents use `_id` as the primary key, but PowerSync
// sync rules require a string column named `id`. The sync rule projects
// `_id AS id`, so on the client side the table's PK column is `id` (text).
//
// Nested MongoDB fields (e.g. `items`) arrive as JSON-text columns and are
// parsed by consumers (see useInventory hook).
//
// When you change a column here, update two more places in lockstep:
//   - powersync/sync-rules.yaml  (the global_inventory projection)
//   - backend/api/inventory.py   (the document writer)

export const APP_DB_NAME = 'retail_demo';
export const INVENTORY_COLLECTION = 'inventory_captures';

const inventoryCaptures = new Table({
  captured_at: column.text,
  device_id: column.text,
  operator_id: column.text,
  cv_model: column.text,
  items: column.text,
  // Lifecycle of the captured frame's stored object:
  // PENDING_UPLOAD -> ACTIVE -> DELETED (set by the backend / reconciler).
  status: column.text,
});

export const AppSchema = new Schema({
  inventory_captures: inventoryCaptures,
});
