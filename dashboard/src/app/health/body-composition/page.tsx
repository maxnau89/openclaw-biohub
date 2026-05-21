'use client';

// Standalone route /health/body-composition — renders the same component
// as the Body Comp tab under /health?tab=body-comp.
import { BodyCompositionTab } from '@/components/health/BodyCompTab';
import { Trophy } from 'lucide-react';

export default function BodyCompositionPage() {
  return (
    <div className="p-6 space-y-4 max-w-6xl">
      <div className="flex items-center gap-3 mb-2">
        <Trophy className="w-7 h-7 text-amber-400" />
        <h1 className="text-2xl font-bold text-white">Body Composition</h1>
      </div>
      <BodyCompositionTab />
    </div>
  );
}
