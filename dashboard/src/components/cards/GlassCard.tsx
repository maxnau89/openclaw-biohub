'use client';

import { motion } from 'framer-motion';
import { ReactNode } from 'react';

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  span?: number;
  delay?: number;
}

export function GlassCard({ children, className = '', span, delay = 0 }: GlassCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, type: 'spring', stiffness: 200, damping: 24 }}
      className={`glass-card p-5 transition-all duration-300 ${span ? `col-span-${span}` : ''} ${className}`}
    >
      {children}
    </motion.div>
  );
}

export function CardHeader({ icon, title, badge }: { icon: ReactNode; title: string; badge?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-4">
      <div className="flex items-center gap-2.5">
        <span className="text-white/30">{icon}</span>
        <h3 className="text-sm font-semibold text-white/80 tracking-tight">{title}</h3>
      </div>
      {badge}
    </div>
  );
}
