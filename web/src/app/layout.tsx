import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'CrewIA Panel',
  description: 'Panel de configuración y monitoreo para crewia-boche',
};

// Inline script that applies the saved theme before first paint (no flash).
const themeScript = `
(function(){
  try {
    var t = localStorage.getItem('crewia-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', t);
  } catch(e) {}
})();
`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      {/* eslint-disable-next-line @next/next/no-before-interactive-script-outside-document */}
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body style={{ fontFamily: 'system-ui, -apple-system, sans-serif' }}>
        {children}
      </body>
    </html>
  );
}
