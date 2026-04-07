import * as React from 'react';
import { cn } from '@/lib/utils';

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'warning';
}

const variantClasses: Record<string, string> = {
  default:     'bg-primary/20 text-primary border-primary/30',
  secondary:   'bg-secondary text-secondary-foreground border-border',
  destructive: 'bg-destructive/20 text-destructive border-destructive/30',
  outline:     'border border-border text-foreground bg-transparent',
  success:     'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  warning:     'bg-amber-500/20 text-amber-400 border-amber-500/30',
};

export function Badge({ className, variant = 'default', ...props }: BadgeProps) {
  return (
    <div
      className={cn(
        'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold',
        variantClasses[variant],
        className,
      )}
      {...props}
    />
  );
}
