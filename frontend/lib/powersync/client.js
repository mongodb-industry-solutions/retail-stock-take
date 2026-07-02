import { PowerSyncDatabase } from '@powersync/web';
import { AppSchema } from './schema';

export function createDb() {
  return new PowerSyncDatabase({
    schema: AppSchema,
    database: { dbFilename: 'retail-stock-take.db' },
  });
}
