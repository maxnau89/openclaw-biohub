import type { Metadata } from 'next';
import './globals.css';
import { TopNav } from '@/components/layout/TopNav';

export const metadata: Metadata = {
  title: 'Mission Control',
  description: 'OpenClaw Agent Command Center',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen">
        <TopNav />
        <main className="pt-12 px-4 lg:px-8 py-6 min-h-screen max-w-[1600px] mx-auto">
          {children}
        </main>
      </body>
    </html>
  );
}
