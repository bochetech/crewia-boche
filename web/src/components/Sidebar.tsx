'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  Play,
  History,
  BotMessageSquare,
  ClipboardList,
  Wrench,
  GitFork,
  ChevronRight,
  Cpu,
  Bot,
  Radio,
  Settings,
} from 'lucide-react';
import { cn } from '@/lib/utils';

const NAV_SECTIONS = [
  {
    label: 'Panel',
    items: [
      { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
      { href: '/run',       label: 'Ejecutar',  icon: Play },
      { href: '/history',   label: 'Historial', icon: History },
      { href: '/settings',  label: 'Ajustes',   icon: Settings },
    ],
  },
  {
    label: 'Configuración',
    items: [
      { href: '/nia',      label: 'Nia',          icon: Bot },
      { href: '/channels', label: 'Canales',       icon: Radio },
      { href: '/agents',   label: 'Agentes',       icon: BotMessageSquare },
      { href: '/tasks',    label: 'Tareas',         icon: ClipboardList },
      { href: '/tools',    label: 'Herramientas',   icon: Wrench },
      { href: '/flows',    label: 'Flujos',         icon: GitFork },
    ],
  },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="flex h-screen w-60 flex-col border-r border-border bg-card">
      {/* Logo */}
      <div className="flex items-center gap-2 px-6 py-5 border-b border-border">
        <Cpu className="h-6 w-6 text-primary" />
        <span className="text-lg font-bold tracking-tight">CrewIA</span>
        <span className="ml-auto text-xs text-muted-foreground font-mono">v1.0</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-5 overflow-y-auto">
        {NAV_SECTIONS.map((section) => (
          <div key={section.label}>
            <p className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/60">
              {section.label}
            </p>
            <div className="space-y-0.5">
              {section.items.map(({ href, label, icon: Icon }) => {
                const active = pathname === href || pathname.startsWith(href + '/');
                return (
                  <Link
                    key={href}
                    href={href}
                    className={cn(
                      'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors',
                      active
                        ? 'bg-primary/10 text-primary'
                        : 'text-muted-foreground hover:bg-secondary hover:text-foreground',
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="flex-1">{label}</span>
                    {active && <ChevronRight className="h-3 w-3 opacity-50" />}
                  </Link>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-border">
        <p className="text-xs text-muted-foreground">crewia-boche • bochetech</p>
      </div>
    </aside>
  );
}
