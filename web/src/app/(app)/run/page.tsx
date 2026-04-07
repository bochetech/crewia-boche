'use client';
import { useState, useRef, useEffect } from 'react';
import { Play, ChevronRight, X, GitFork } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { ExecutionGraph } from '@/components/ExecutionGraph';
import { runCrew, getExecution, createExecutionSocket, listFlows } from '@/lib/api';
import type { AgentStepEvent, ExecutionRecord, Flow } from '@/lib/types';

export default function RunPage() {
  const [input, setInput]                   = useState('');
  const [execution, setExecution]           = useState<ExecutionRecord | null>(null);
  const [selectedAgent, setSelectedAgent]   = useState<string | null>(null);
  const [loading, setLoading]               = useState(false);
  const [flows, setFlows]                   = useState<Flow[]>([]);
  const [selectedFlowId, setSelectedFlowId] = useState<string>('');
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    listFlows().then(f => {
      setFlows(f);
      if (f.length > 0) setSelectedFlowId(f[0].id);
    }).catch(console.error);
  }, []);

  const activeFlow = flows.find(f => f.id === selectedFlowId) ?? null;

  async function handleRun() {
    if (!input.trim()) return;
    setLoading(true);
    setSelectedAgent(null);
    try {
      const { execution_id } = await runCrew(input, selectedFlowId || undefined);
      const rec = await getExecution(execution_id);
      setExecution(rec);

      wsRef.current = createExecutionSocket(
        execution_id,
        (raw) => {
          try {
            const event: AgentStepEvent = JSON.parse(raw);
            setExecution((prev) => {
              if (!prev) return prev;
              return { ...prev, steps: [...prev.steps, event] };
            });
          } catch { /* ignore parse errors */ }
        },
        async () => {
          const final = await getExecution(execution_id);
          setExecution(final);
          setLoading(false);
        },
      );
    } catch (err) {
      console.error(err);
      setLoading(false);
    }
  }

  useEffect(() => {
    return () => { wsRef.current?.close(); };
  }, []);

  const agentSteps = execution?.steps.filter((s) => s.agent === selectedAgent) ?? [];

  return (
    <div className="flex h-full flex-col p-8 gap-6">
      {/* Header + input */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Ejecutar Crew</h1>
        <p className="text-muted-foreground mt-1">
          Describe una iniciativa y observa el proceso multi-agente en tiempo real
        </p>
      </div>

      <div className="space-y-3">
        {/* Flow selector */}
        {flows.length > 0 && (
          <div className="flex items-center gap-3">
            <GitFork className="h-4 w-4 text-primary shrink-0" />
            <label className="text-sm text-muted-foreground shrink-0">Flujo:</label>
            <select
              value={selectedFlowId}
              onChange={e => setSelectedFlowId(e.target.value)}
              disabled={loading}
              className="rounded-md border border-border bg-secondary px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {flows.map(f => (
                <option key={f.id} value={f.id}>{f.name}</option>
              ))}
            </select>
            {activeFlow?.goal && (
              <span className="text-xs text-muted-foreground truncate max-w-xs">
                {activeFlow.goal.slice(0, 80)}…
              </span>
            )}
          </div>
        )}

        <div className="flex gap-3">
          <textarea
            className="flex-1 rounded-lg border border-border bg-secondary px-4 py-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary h-24"
            placeholder="Ej: Implementar integración SAP con Shopify para sincronizar inventario en tiempo real…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={loading}
          />
          <button
            onClick={handleRun}
            disabled={loading || !input.trim()}
            className="flex items-center gap-2 rounded-lg bg-primary px-6 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors self-start py-3"
          >
            <Play className="h-4 w-4" />
            {loading ? 'Ejecutando…' : 'Iniciar'}
          </button>
        </div>
      </div>

      {/* Main area: graph + side panel */}
      <div className="flex flex-1 gap-6 min-h-0">
        {/* Execution graph */}
        <div className="flex-1 min-h-0">
          {execution ? (
            <div className="h-full flex flex-col gap-3">
              <div className="flex items-center gap-3 text-sm">
                <span className="text-muted-foreground font-mono text-xs">{execution.id.slice(0, 8)}…</span>
                <StatusBadge status={execution.status} />
                {execution.foco && <Badge variant="secondary">{execution.foco}</Badge>}
                {execution.initiative_id && <Badge variant="outline">{execution.initiative_id}</Badge>}
                <span className="ml-auto text-xs text-muted-foreground">{execution.steps.length} eventos</span>
              </div>
              <div className="flex-1 min-h-0">
                <ExecutionGraph
                  execution={execution}
                  flow={activeFlow}
                  onSelectAgent={setSelectedAgent}
                />
              </div>
            </div>
          ) : (
            <div className="h-full flex items-center justify-center rounded-lg border border-dashed border-border text-muted-foreground text-sm">
              <div className="text-center space-y-2">
                {activeFlow ? (
                  <>
                    <GitFork className="h-10 w-10 mx-auto opacity-30" />
                    <p>Flujo: <strong>{activeFlow.name}</strong></p>
                    <p className="text-xs opacity-70">{activeFlow.steps.length} pasos · Ingresa una iniciativa y presiona <strong>Iniciar</strong></p>
                  </>
                ) : (
                  <>
                    <ChevronRight className="h-10 w-10 mx-auto opacity-30" />
                    <p>Ingresa una iniciativa y presiona <strong>Iniciar</strong></p>
                  </>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Agent detail panel */}
        {selectedAgent && (
          <div className="w-80 shrink-0">
            <Card className="h-full flex flex-col">
              <CardHeader className="flex flex-row items-center justify-between pb-3">
                <CardTitle className="text-sm">{selectedAgent}</CardTitle>
                <button onClick={() => setSelectedAgent(null)} className="text-muted-foreground hover:text-foreground">
                  <X className="h-4 w-4" />
                </button>
              </CardHeader>
              <CardContent className="flex-1 overflow-auto p-4 pt-0 space-y-2">
                {agentSteps.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Sin eventos aún para este agente</p>
                ) : (
                  agentSteps.map((step, i) => (
                    <div key={i} className="rounded-md border border-border p-3 text-xs space-y-1">
                      <div className="flex items-center justify-between">
                        <EventBadge event={step.event} />
                        <span className="text-muted-foreground font-mono">
                          {new Date(step.timestamp).toLocaleTimeString()}
                        </span>
                      </div>
                      {Object.keys(step.payload).length > 0 && (
                        <pre className="mt-1 text-[10px] text-muted-foreground whitespace-pre-wrap break-all overflow-auto max-h-40">
                          {JSON.stringify(step.payload, null, 2)}
                        </pre>
                      )}
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </div>
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

function EventBadge({ event }: { event: string }) {
  const map: Record<string, string> = {
    started:     'bg-blue-500/20 text-blue-400',
    completed:   'bg-emerald-500/20 text-emerald-400',
    error:       'bg-red-500/20 text-red-400',
    tool_call:   'bg-violet-500/20 text-violet-400',
    tool_result: 'bg-cyan-500/20 text-cyan-400',
    finished:    'bg-emerald-500/20 text-emerald-400',
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${map[event] ?? 'bg-secondary text-muted-foreground'}`}>
      {event}
    </span>
  );
}
