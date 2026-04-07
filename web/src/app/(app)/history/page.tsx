'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Clock, ChevronRight } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { listExecutions } from '@/lib/api';
import type { ExecutionRecord } from '@/lib/types';
import { formatDistanceToNow, format } from 'date-fns';
import { es } from 'date-fns/locale';

export default function HistoryPage() {
  const [executions, setExecutions] = useState<ExecutionRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    listExecutions(50).then(setExecutions).catch(console.error).finally(() => setLoading(false));
  }, []);

  return (
    <div className="p-8 space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Historial</h1>
        <p className="text-muted-foreground mt-1">Todas las ejecuciones del Strategy Crew</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Clock className="h-4 w-4" /> {executions.length} ejecuciones
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <p className="px-6 py-4 text-sm text-muted-foreground">Cargando…</p>
          ) : (
            <div className="divide-y divide-border">
              {executions.map((exec) => (
                <div key={exec.id}>
                  <button
                    className="w-full flex items-center justify-between px-6 py-4 hover:bg-secondary/50 text-left"
                    onClick={() => setExpanded(expanded === exec.id ? null : exec.id)}
                  >
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">{exec.input_text}</p>
                      <div className="flex items-center gap-2 mt-1 text-xs text-muted-foreground">
                        <span>{format(new Date(exec.started_at), 'dd/MM/yyyy HH:mm', { locale: es })}</span>
                        <span>•</span>
                        <span>{formatDistanceToNow(new Date(exec.started_at), { addSuffix: true, locale: es })}</span>
                        {exec.foco && <><span>•</span><span className="font-mono">{exec.foco}</span></>}
                        {exec.initiative_id && <><span>•</span><span className="font-mono">{exec.initiative_id}</span></>}
                      </div>
                    </div>
                    <div className="flex items-center gap-3 ml-4">
                      <StatusBadge status={exec.status} />
                      <ChevronRight className={`h-4 w-4 text-muted-foreground transition-transform ${expanded === exec.id ? 'rotate-90' : ''}`} />
                    </div>
                  </button>

                  {expanded === exec.id && (
                    <div className="px-6 pb-4 space-y-3 bg-secondary/20">
                      {/* Steps timeline */}
                      <p className="text-xs font-semibold text-muted-foreground pt-2">PASOS DE EJECUCIÓN</p>
                      <ol className="space-y-2">
                        {exec.steps.map((step, i) => (
                          <li key={i} className="flex gap-3 text-xs">
                            <span className="w-4 h-4 rounded-full bg-primary/20 text-primary flex items-center justify-center shrink-0 font-mono text-[10px] mt-0.5">
                              {i + 1}
                            </span>
                            <div>
                              <span className="font-medium text-foreground capitalize">{step.agent}</span>
                              {' · '}
                              <span className="text-muted-foreground">{step.event}</span>
                              {step.payload && Object.keys(step.payload).length > 0 && (
                                <pre className="mt-1 text-[10px] text-muted-foreground/70 whitespace-pre-wrap break-all">
                                  {JSON.stringify(step.payload, null, 2)}
                                </pre>
                              )}
                            </div>
                          </li>
                        ))}
                      </ol>

                      {/* Error */}
                      {exec.error && (
                        <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                          {exec.error}
                        </div>
                      )}

                      {/* Result */}
                      {exec.result && (
                        <details className="text-xs">
                          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">Ver resultado completo</summary>
                          <pre className="mt-2 rounded bg-secondary p-3 text-[10px] overflow-auto max-h-60">
                            {JSON.stringify(exec.result, null, 2)}
                          </pre>
                        </details>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { variant: 'success' | 'destructive' | 'warning' | 'secondary'; label: string }> = {
    approved: { variant: 'success',     label: '✓ Aprobada' },
    rejected: { variant: 'destructive', label: '✗ Rechazada' },
    running:  { variant: 'warning',     label: '⟳ Ejecutando' },
    pending:  { variant: 'secondary',   label: '● Pendiente' },
    error:    { variant: 'destructive', label: '⚠ Error' },
  };
  const cfg = map[status] ?? { variant: 'secondary' as const, label: status };
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
}
