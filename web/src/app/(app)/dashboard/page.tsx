'use client';
import { useEffect, useState } from 'react';
import { Activity, CheckCircle2, XCircle, Zap, Cpu, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { listExecutions, getLMStudioStatus } from '@/lib/api';
import type { ExecutionRecord, LMStudioStatus } from '@/lib/types';
import { formatDistanceToNow } from 'date-fns';
import { es } from 'date-fns/locale';

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { variant: 'success' | 'destructive' | 'warning' | 'secondary' | 'default'; label: string }> = {
    approved: { variant: 'success',     label: '✓ Aprobada' },
    rejected: { variant: 'destructive', label: '✗ Rechazada' },
    running:  { variant: 'warning',     label: '⟳ Ejecutando' },
    pending:  { variant: 'secondary',   label: '● Pendiente' },
    error:    { variant: 'destructive', label: '⚠ Error' },
  };
  const cfg = map[status] ?? { variant: 'secondary' as const, label: status };
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>;
}

export default function DashboardPage() {
  const [executions, setExecutions] = useState<ExecutionRecord[]>([]);
  const [lmStatus, setLmStatus] = useState<LMStudioStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([listExecutions(10), getLMStudioStatus()])
      .then(([execs, lm]) => { setExecutions(execs); setLmStatus(lm); })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const stats = {
    total:    executions.length,
    approved: executions.filter((e) => e.status === 'approved').length,
    rejected: executions.filter((e) => e.status === 'rejected').length,
    running:  executions.filter((e) => e.status === 'running').length,
  };

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground mt-1">
          Monitoreo del Multi-Agent Strategy Crew
        </p>
      </div>

      {/* LM Studio status banner */}
      {lmStatus && (
        <div className={`flex items-center gap-3 rounded-lg border px-4 py-3 text-sm ${
          lmStatus.status === 'connected'
            ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
            : 'border-amber-500/30 bg-amber-500/10 text-amber-400'
        }`}>
          <Cpu className="h-4 w-4 shrink-0" />
          {lmStatus.status === 'connected' ? (
            <span>
              <strong>LM Studio conectado</strong> — {lmStatus.models?.[0] ?? 'modelo activo'} @ {lmStatus.base_url}
            </span>
          ) : (
            <span><strong>LM Studio desconectado</strong> — {lmStatus.base_url}</span>
          )}
        </div>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        {[
          { label: 'Total',      value: stats.total,    icon: Activity,      color: 'text-primary' },
          { label: 'Aprobadas',  value: stats.approved, icon: CheckCircle2,  color: 'text-emerald-400' },
          { label: 'Rechazadas', value: stats.rejected, icon: XCircle,       color: 'text-red-400' },
          { label: 'En proceso', value: stats.running,  icon: Zap,           color: 'text-amber-400' },
        ].map(({ label, value, icon: Icon, color }) => (
          <Card key={label}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">{label}</CardTitle>
              <Icon className={`h-4 w-4 ${color}`} />
            </CardHeader>
            <CardContent>
              <p className={`text-3xl font-bold ${color}`}>{value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Recent executions */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Ejecuciones recientes</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <p className="px-6 py-4 text-sm text-muted-foreground">Cargando…</p>
          ) : executions.length === 0 ? (
            <div className="flex flex-col items-center py-12 text-muted-foreground gap-2">
              <AlertCircle className="h-8 w-8" />
              <p>No hay ejecuciones aún. ¡Inicia una desde la página Ejecutar!</p>
            </div>
          ) : (
            <div className="divide-y divide-border">
              {executions.map((exec) => (
                <div key={exec.id} className="flex items-center justify-between px-6 py-4 hover:bg-secondary/50">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{exec.input_text.slice(0, 80)}…</p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {formatDistanceToNow(new Date(exec.started_at), { addSuffix: true, locale: es })}
                      {exec.foco && <span className="ml-2 font-mono">• {exec.foco}</span>}
                      {exec.initiative_id && <span className="ml-2 font-mono">• {exec.initiative_id}</span>}
                    </p>
                  </div>
                  <div className="ml-4 shrink-0">
                    <StatusBadge status={exec.status} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
