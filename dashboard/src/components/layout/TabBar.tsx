'use client';

import { motion } from 'framer-motion';
import { useSearchParams, useRouter, usePathname } from 'next/navigation';

interface Tab {
  id: string;
  label: string;
  icon?: React.ReactNode;
}

export function TabBar({ tabs, defaultTab, id }: { tabs: Tab[]; defaultTab?: string; id?: string }) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const activeTab = searchParams.get('tab') || defaultTab || tabs[0]?.id;
  const layoutId = id || `tab-pill-${pathname}`;

  return (
    <div className="flex items-center gap-1 mb-6 p-1 rounded-2xl bg-white/[0.02] border border-white/[0.06] w-fit relative z-10">
      {tabs.map(tab => {
        const isActive = activeTab === tab.id;
        return (
          <button
            key={tab.id}
            type="button"
            onClick={() => {
              const params = new URLSearchParams(searchParams.toString());
              params.set('tab', tab.id);
              router.push(`${pathname}?${params.toString()}`);
            }}
            className={`
              relative px-4 py-1.5 rounded-xl text-xs font-medium transition-colors duration-200 cursor-pointer
              ${isActive ? 'text-white/90' : 'text-white/35 hover:text-white/55'}
            `}
          >
            {isActive && (
              <motion.div
                layoutId={layoutId}
                className="absolute inset-0 rounded-xl bg-white/[0.08] border border-white/[0.1]"
                transition={{ type: 'spring', stiffness: 400, damping: 30 }}
              />
            )}
            <span className="relative z-[1] flex items-center gap-1.5">
              {tab.icon}
              {tab.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
