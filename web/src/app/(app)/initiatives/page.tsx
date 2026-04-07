'use client';
import { useEffect, useState } from 'react';
import { Zap, Search } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { listInitiatives } from '@/lib/api';
import type { Initiative } from '@/lib/types';

const FOCO_COLORS: Record<string, string> = {
  F1: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
  F2: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  F3: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30',
  F4: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
};

const STATUS_COLORS: Record<string, string> = {
  'Planificado':  'secondary',
  'En progreso':  'warning',
  'Completado':   'success',
  'Cancelado':    'destructive',
};

export default function InitiativesPage() {
  const [initiatives, setInitiatives] = useState<Initiative[]>([]);
  const [loading, setLoading]         = useState(true);
  const [query, setQuery]             = useState('');

  useEffect(() => {
    listInitiatives()
      .then((data) => setInitiatives(data.initiatives ?? []))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const filtered = initiatives.filter(
    (i) =>
      i.title.toLowerCase().includes(query.toLowerCase()) ||
      i.id.toLowerCase().includes(query.toLowerCase()) ||
      i.foco?.toLowerCase().includes(query.toLowerCase()),
  );

  const byFoco: Record<string, Initiative[]> = {};
  for (const ini of filtered) {
    const f = ini.foco ?? 'Sin Foco';
    if (!byFoco[f]) byFoco[f] = [];
    byFoco[f].push(ini);
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Iniciativas</h1>
          <p className="text-muted-foreground mt-1">
            {initiatives.length} iniciativas en el HTML SSOT
          </p>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          className="w-full rounded-lg border border-border bg-secondary pl-10 pr-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          placeholder="Buscar por título, ID o foco…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {/* By Foco */}
      {loading ? (
        <p className="text-sm text-muted-foreground">Cargando…</p>
      ) : (
        <div className="space-y-8">
          {['F1', 'F2', 'F3', 'F4', 'Sin Foco'].map((foco) => {
            const items = byFoco[foco];
            if (!items || items.length === 0) return null;
            return (
              <div key={foco}>
                <div className="flex items-center gap-3 mb-4">
                  <Zap className="h-4 w-4 text-primary" />
                  <h2 className="text-sm font-semibold">{foco}</h2>
                  <span className="text-xs text-muted-foreground">{items.length} iniciativas</span>
                </div>
                <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
                  {items.map((ini) => (
                    <Card key={ini.id} className="hover:border-primary/50 transition-colors cursor-default">
                      <CardHeader className="pb-3">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-semibold leading-tight">{ini.title}</p>
                            <p className="text-xs font-mono text-muted-foreground mt-0.5">{ini.id}</p>
                          </div>
                          <span className={`shrink-0 inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-bold ${FOCO_COLORS[ini.foco] ?? ''}`}>
                            {ini.foco}
                          </span>
                        </div>
                      </CardHeader>
                      <CardContent className="pb-4 space-y-2">
                        {ini.objective && (
                          <p className="text-xs text-muted-foreground line-clamp-2">{ini.objective}</p>
                        )}
                        <div className="flex flex-wrap gap-2 pt-1">
                          <Badge variant={(STATUS_COLORS[ini.status] as any) ?? 'secondary'}>
                            {ini.status}
                          </Badge>
                          {ini.owner && ini.owner !== 'TBD' && (
                            <span className="text-xs text-muted-foreground">👤 {ini.owner}</span>
                          )}
                          {ini.deadline && ini.deadline !== 'TBD' && (
                            <span className="text-xs text-muted-foreground">📅 {ini.deadline}</span>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
