import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'CrewIA Panel',
  description: 'Panel de configuración y monitoreo para crewia-boche',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className="dark">
      <body style={{ fontFamily: 'system-ui, -apple-system, sans-serif' }}>
        {children}
      </body>
    </html>
  );
}
