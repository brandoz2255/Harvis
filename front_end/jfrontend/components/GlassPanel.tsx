import { ReactNode } from 'react';

interface Props {
  className?: string;
  children: ReactNode;
}

export default function GlassPanel({ className = '', children }: Props) {
  return (
    <div
      className={`rounded-3xl border border-stroke bg-surface backdrop-blur-xs shadow-glass ${className}`}
    >
      {children}
    </div>
  );
}