'use client';
import { useEffect, useState } from 'react';
import {
  GitFork, Plus, Trash2, Save, ChevronDown, ChevronUp,
  ArrowRight, GripVertical, Users,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { listFlows, createFlow, updateFlow, deleteFlow, listAgents, listTasks } from '@/lib/api';
import type { AgentConfig, Flow, FlowStep, TaskConfig } from '@/lib/types';

const EMPTY_FLOW: Flow = {
  id: '', name: '', description: '', goal: '', steps: [],
};
const EMPTY_STEP: FlowStep = {
  agent_id: '', task_id: '', label: '', parallel_group: null,
};

export default function FlowsPage() {
  const [flows, setFlows]       = useState<Flow[]>([]);
  const [agents, setAgents]     = useState<AgentConfig[]>([]);
  const [tasks, setTasks]       = useState<TaskConfig[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newFlow, setNewFlow]   = useState<Flow>({ ...EMPTY_FLOW });
  const [saving, setSaving]     = useState<string | null>(null);
  const [error, setError]       = useState<string | null>(null);

  useEffect(() => {
    listFlows().then(setFlows).catch(console.error);
    listAgents().then(setAgents).catch(console.error);
    listTasks().then(setTasks).catch(console.error);
  }, []);

  const agentName = (id: string) => agents.find(a => a.id === id)?.role || id;
  const taskName  = (id: string) => tasks.find(t => t.id === id)?.title || id;
  const tasksByAgent = (agentId: string) => tasks.filter(t => t.agent_id === agentId);

  async function handleSave(flow: Flow) {
    setSaving(flow.id);
    try {
      const updated = await updateFlow(flow.id, flow);
      setFlows(prev => prev.map(f => f.id === updated.id ? updated : f));
    } catch (e) { setError(String(e)); }
    finally { setSaving(null); }
  }

  async function handleCreate() {
    if (!newFlow.name.trim()) { setError('El nombre del flujo es obligatorio'); return; }
    setSaving('new');
    try {
      const id = newFlow.name.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
      const created = await createFlow({ ...newFlow, id });
      setFlows(prev => [...prev, created]);
      setNewFlow({ ...EMPTY_FLOW });
      setCreating(false);
      setExpanded(created.id);
    } catch (e) { setError(String(e)); }
    finally { setSaving(null); }
  }

  async function handleDelete(id: string) {
    if (!confirm(`¿Eliminar el flujo "${id}"?`)) return;
    try {
      await deleteFlow(id);
      setFlows(prev => prev.filter(f => f.id !== id));
      if (expanded === id) setExpanded(null);
    } catch (e) { setError(String(e)); }
  }

  return (
    <div className="p-8 space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <GitFork className="h-7 w-7 text-primary" /> Flujos
          </h1>
          <p className="text-muted-foreground mt-1">
            Un flujo define el objetivo y la secuencia de pasos (agente + tarea) que el crew ejecuta.
            Los pasos con el mismo <strong>grupo paralelo</strong> se ejecutan al mismo tiempo.
            Al ejecutar desde la página <strong>Ejecutar</strong>, puedes elegir qué flujo correr.
          </p>
        </div>
        <button
          onClick={() => { setCreating(true); setExpanded(null); setError(null); }}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          <Plus className="h-4 w-4" /> Nuevo Flujo
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
          <button className="ml-3 underline" onClick={() => setError(null)}>Cerrar</button>
        </div>
      )}

      {/* Info: how flows work */}
      <div className="rounded-lg border border-primary/20 bg-primary/5 px-4 py-3 text-sm text-primary/80 space-y-1">
        <p className="font-semibold flex items-center gap-1.5"><Users className="h-4 w-4" /> ¿Cómo funcionan los flujos?</p>
        <ul className="list-disc list-inside space-y-0.5 text-xs text-muted-foreground">
          <li>El <strong>Coordinator</strong> NO decide el flujo: el flujo está definido aquí y el coordinador solo aprueba el resultado final.</li>
          <li>Los pasos se ejecutan en orden. Pasos con el mismo <code className="bg-secondary px-1 rounded">grupo paralelo</code> corren en threads simultáneos.</li>
          <li>Cada paso vincula un <strong>agente</strong> con una <strong>tarea</strong> — el agente ejecuta el prompt de la tarea.</li>
          <li>El flujo seleccionado al ejecutar determina qué agentes participan y en qué orden.</li>
        </ul>
      </div>

      {/* Create form */}
      {creating && (
        <Card className="border-primary/40">
          <CardContent className="pt-5 space-y-4">
            <p className="text-sm font-semibold text-primary">Nuevo Flujo</p>
            <Field label="Nombre" value={newFlow.name}
              onChange={v => setNewFlow(p => ({ ...p, name: v }))} />
            <Field label="Descripción" value={newFlow.description}
              onChange={v => setNewFlow(p => ({ ...p, description: v }))} multiline rows={2} />
            <Field label="Objetivo del flujo" value={newFlow.goal}
              onChange={v => setNewFlow(p => ({ ...p, goal: v }))} multiline rows={2} />
            <StepEditor
              steps={newFlow.steps}
              agents={agents}
              tasks={tasks}
              tasksByAgent={tasksByAgent}
              agentName={agentName}
              taskName={taskName}
              onChange={steps => setNewFlow(p => ({ ...p, steps }))}
            />
            <div className="flex gap-2 pt-1">
              <button onClick={handleCreate} disabled={saving === 'new'}
                className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors">
                <Save className="h-3.5 w-3.5" />
                {saving === 'new' ? 'Creando…' : 'Crear Flujo'}
              </button>
              <button onClick={() => setCreating(false)}
                className="rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-secondary transition-colors">
                Cancelar
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Flows list */}
      <div className="space-y-4">
        {flows.map(flow => (
          <FlowCard
            key={flow.id}
            flow={flow}
            agents={agents}
            tasks={tasks}
            expanded={expanded === flow.id}
            saving={saving === flow.id}
            agentName={agentName}
            taskName={taskName}
            tasksByAgent={tasksByAgent}
            onToggle={() => setExpanded(expanded === flow.id ? null : flow.id)}
            onSave={handleSave}
            onDelete={() => handleDelete(flow.id)}
          />
        ))}
        {flows.length === 0 && !creating && (
          <p className="text-sm text-muted-foreground text-center py-12">
            No hay flujos configurados. Crea el primero.
          </p>
        )}
      </div>
    </div>
  );
}

// ─── FlowCard ─────────────────────────────────────────────────────────────────

function FlowCard({
  flow, agents, tasks, expanded, saving, agentName, taskName, tasksByAgent,
  onToggle, onSave, onDelete,
}: {
  flow: Flow; agents: AgentConfig[]; tasks: TaskConfig[];
  expanded: boolean; saving: boolean;
  agentName: (id: string) => string;
  taskName: (id: string) => string;
  tasksByAgent: (agentId: string) => TaskConfig[];
  onToggle: () => void; onSave: (f: Flow) => void; onDelete: () => void;
}) {
  const [local, setLocal] = useState<Flow>(flow);
  useEffect(() => setLocal(flow), [flow]);

  return (
    <Card>
      <button
        className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-secondary/30 transition-colors"
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <GitFork className="h-4 w-4 text-primary" />
          </div>
          <div>
            <p className="text-sm font-semibold">{local.name}</p>
            <p className="text-xs text-muted-foreground font-mono">
              {local.id} · {local.steps.length} paso{local.steps.length !== 1 ? 's' : ''}
            </p>
          </div>
        </div>
        {/* Mini flow preview */}
        {!expanded && local.steps.length > 0 && (
          <div className="hidden md:flex items-center gap-1 text-xs text-muted-foreground mr-4">
            {local.steps.map((s, i) => (
              <span key={i} className="flex items-center gap-1">
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
                  s.parallel_group ? 'bg-amber-500/10 text-amber-400' : 'bg-secondary'
                }`}>
                  {s.label || agentName(s.agent_id)}
                </span>
                {i < local.steps.length - 1 && <ArrowRight className="h-3 w-3 opacity-40" />}
              </span>
            ))}
          </div>
        )}
        {expanded ? <ChevronUp className="h-4 w-4 text-muted-foreground shrink-0" /> : <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />}
      </button>

      {expanded && (
        <CardContent className="pt-0 space-y-4 border-t border-border">
          <div className="pt-4 space-y-4">
            <Field label="Nombre" value={local.name} onChange={v => setLocal(p => ({ ...p, name: v }))} />
            <Field label="Descripción" value={local.description}
              onChange={v => setLocal(p => ({ ...p, description: v }))} multiline rows={2} />
            <Field label="Objetivo del flujo" value={local.goal}
              onChange={v => setLocal(p => ({ ...p, goal: v }))} multiline rows={3} />

            <StepEditor
              steps={local.steps}
              agents={agents}
              tasks={tasks}
              tasksByAgent={tasksByAgent}
              agentName={agentName}
              taskName={taskName}
              onChange={steps => setLocal(p => ({ ...p, steps }))}
            />
          </div>
          <div className="flex justify-between pt-1">
            <button onClick={() => onSave(local)} disabled={saving}
              className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors">
              <Save className="h-3.5 w-3.5" />
              {saving ? 'Guardando…' : 'Guardar cambios'}
            </button>
            <button onClick={onDelete}
              className="flex items-center gap-2 rounded-lg border border-destructive/40 px-3 py-2 text-sm text-destructive hover:bg-destructive/10 transition-colors">
              <Trash2 className="h-3.5 w-3.5" /> Eliminar flujo
            </button>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

// ─── StepEditor ───────────────────────────────────────────────────────────────

function StepEditor({
  steps, agents, tasks, tasksByAgent, agentName, taskName, onChange,
}: {
  steps: FlowStep[];
  agents: AgentConfig[];
  tasks: TaskConfig[];
  tasksByAgent: (agentId: string) => TaskConfig[];
  agentName: (id: string) => string;
  taskName: (id: string) => string;
  onChange: (steps: FlowStep[]) => void;
}) {
  function addStep() {
    onChange([...steps, { ...EMPTY_STEP }]);
  }

  function removeStep(i: number) {
    onChange(steps.filter((_, idx) => idx !== i));
  }

  function updateStep(i: number, field: keyof FlowStep, value: string | null) {
    const updated = steps.map((s, idx) =>
      idx === i ? { ...s, [field]: value } : s
    );
    onChange(updated);
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-muted-foreground">
          Pasos del flujo ({steps.length})
        </p>
        <button onClick={addStep}
          className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary transition-colors">
          <Plus className="h-3 w-3" /> Agregar paso
        </button>
      </div>

      {steps.length === 0 && (
        <p className="text-xs text-muted-foreground text-center py-4 border border-dashed border-border rounded-lg">
          Sin pasos. Agrega al menos uno para definir el flujo.
        </p>
      )}

      <div className="space-y-2">
        {steps.map((step, i) => (
          <div key={i}
            className="flex items-start gap-2 rounded-lg border border-border bg-secondary/20 p-3">
            {/* Step number */}
            <div className="flex flex-col items-center gap-1 mt-1">
              <GripVertical className="h-4 w-4 text-muted-foreground/40" />
              <span className="text-[10px] text-muted-foreground font-mono w-5 text-center">{i + 1}</span>
            </div>

            <div className="flex-1 grid grid-cols-2 gap-2">
              {/* Agent selector */}
              <div>
                <label className="block text-[10px] text-muted-foreground mb-1">Agente</label>
                <select
                  value={step.agent_id}
                  onChange={e => {
                    updateStep(i, 'agent_id', e.target.value);
                    updateStep(i, 'task_id', '');  // reset task when agent changes
                  }}
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="">— Agente —</option>
                  {agents.map(a => (
                    <option key={a.id} value={a.id}>{a.role}</option>
                  ))}
                </select>
              </div>

              {/* Task selector (filtered by selected agent) */}
              <div>
                <label className="block text-[10px] text-muted-foreground mb-1">Tarea</label>
                <select
                  value={step.task_id}
                  onChange={e => updateStep(i, 'task_id', e.target.value)}
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                  disabled={!step.agent_id}
                >
                  <option value="">— Tarea —</option>
                  {(step.agent_id ? tasksByAgent(step.agent_id) : tasks).map(t => (
                    <option key={t.id} value={t.id}>{t.title || t.id}</option>
                  ))}
                </select>
              </div>

              {/* Label */}
              <div>
                <label className="block text-[10px] text-muted-foreground mb-1">Etiqueta (opcional)</label>
                <input
                  value={step.label}
                  onChange={e => updateStep(i, 'label', e.target.value)}
                  placeholder={step.agent_id ? agentName(step.agent_id) : 'ej: Clasificar Foco'}
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>

              {/* Parallel group */}
              <div>
                <label className="block text-[10px] text-muted-foreground mb-1">
                  Grupo paralelo <span className="text-muted-foreground/50">(mismo grupo = simultáneo)</span>
                </label>
                <input
                  value={step.parallel_group ?? ''}
                  onChange={e => updateStep(i, 'parallel_group', e.target.value || null)}
                  placeholder="ej: analysis"
                  className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
            </div>

            <button onClick={() => removeStep(i)}
              className="mt-1 rounded-md p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors">
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Field helper ─────────────────────────────────────────────────────────────

function Field({
  label, value, onChange, multiline = false, rows = 2,
}: {
  label: string; value: string; onChange: (v: string) => void;
  multiline?: boolean; rows?: number;
}) {
  const cls = "w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary resize-none";
  return (
    <div>
      <label className="block text-xs text-muted-foreground mb-1">{label}</label>
      {multiline
        ? <textarea rows={rows} value={value} onChange={e => onChange(e.target.value)} className={cls} />
        : <input value={value} onChange={e => onChange(e.target.value)} className={cls} />
      }
    </div>
  );
}
