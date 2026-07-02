import './globals.css';
import { Providers } from './providers';

export const metadata = {
  title: 'Retail Stock Take — MongoDB + PowerSync',
  description:
    'Offline-first retail inventory demo. MongoDB Enterprise + PowerSync self-hosted + local CV via Ollama.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full" style={{ backgroundColor: 'var(--mdb-bg)' }}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
