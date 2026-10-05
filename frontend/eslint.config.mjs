import { defineConfig, globalIgnores } from 'eslint/config';
import nextVitals from 'eslint-config-next/core-web-vitals';

// eslint-config-next@16 ships a native flat config; @eslint/eslintrc is not
// needed. The app is JS (no TS), so only the core-web-vitals preset applies.
export default defineConfig([
  ...nextVitals,
  globalIgnores(['node_modules', '.next', 'out', 'build', 'next-env.d.ts']),
  {
    rules: {
      // providers.js initialises the PowerSync db + theme in an effect; the
      // react-hooks v6 "set-state-in-effect" rule is a new opinion that would
      // force an unrelated refactor. Relax it for this demo.
      'react-hooks/set-state-in-effect': 'off',
    },
  },
]);
