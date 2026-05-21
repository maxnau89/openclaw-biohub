import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'openclaw-biohub',
  description: 'Self-hosted personal-health hub: WHOOP, Oura, Fitbit, Apple Health, Garmin.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen">
        <main className="pt-12 px-4 lg:px-8 py-6 min-h-screen max-w-[1600px] mx-auto">
          {children}
        </main>
      </body>
    </html>
  );
}
