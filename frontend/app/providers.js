'use client';

import { createContext, useContext, useEffect, useState } from 'react';
import LeafyGreenProvider from '@leafygreen-ui/leafygreen-provider';
import { PowerSyncContext } from '@powersync/react';
import { createDb } from '@/lib/powersync/client';
import { RetailBackendConnector } from '@/lib/powersync/auth';

// Module-level singleton so React strict-mode double-mount doesn't open
// two databases.
let dbSingleton = null;

function getOrCreateDb() {
  if (dbSingleton) return dbSingleton;
  dbSingleton = createDb();
  const connector = new RetailBackendConnector();
  dbSingleton
    .connect(connector)
    .then(() => console.info('[powersync] connected'))
    .catch((e) => console.error('[powersync] connect failed:', e));
  return dbSingleton;
}

// ── Theme context ───────────────────────────────────────────────
// Single source of truth for light/dark. Drives BOTH the LeafyGreen
// components (via LeafyGreenProvider darkMode) and the custom layout
// shell (via the `.light` class on <html> that globals.css keys off).
// Default is dark; the choice is persisted to localStorage.
const ThemeContext = createContext({ isDark: true, toggle: () => {} });

export function useTheme() {
  return useContext(ThemeContext);
}

export function Providers({ children }) {
  const [db, setDb] = useState(null);
  const [isDark, setIsDark] = useState(true);

  useEffect(() => {
    setDb(getOrCreateDb());
  }, []);

  useEffect(() => {
    const saved = localStorage.getItem('mdb-theme');
    if (saved === 'light') {
      setIsDark(false);
      document.documentElement.classList.add('light');
    } else {
      document.documentElement.classList.remove('light');
    }
  }, []);

  function toggle() {
    setIsDark((prev) => {
      const next = !prev;
      if (next) {
        document.documentElement.classList.remove('light');
        localStorage.setItem('mdb-theme', 'dark');
      } else {
        document.documentElement.classList.add('light');
        localStorage.setItem('mdb-theme', 'light');
      }
      return next;
    });
  }

  return (
    <ThemeContext.Provider value={{ isDark, toggle }}>
      <LeafyGreenProvider darkMode={isDark}>
        {db ? (
          <PowerSyncContext.Provider value={db}>
            {children}
          </PowerSyncContext.Provider>
        ) : (
          <div style={{ padding: 24, color: '#666', fontFamily: 'system-ui' }}>
            Initializing local database…
          </div>
        )}
      </LeafyGreenProvider>
    </ThemeContext.Provider>
  );
}
