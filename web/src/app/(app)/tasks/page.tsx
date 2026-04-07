'use client';
import { useEffect, useState } from 'react';
import { ClipboardList, Plus, Trash2, Save, ChevronDown, ChevronUp } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { listTasks, createTask, updateTask, deleteTask, listAgents } from '@/lib/api';
import type { AgentConfig, TaskConfig } from '@/lib/types';

const EMPTY_TASK: TaskConfig = {
  id: '', title: '', description: '', expected_result: '', agent_id: '',
};

export default function TasksPage() {
  const [tasks, setTasks]       = useState<TaskConfig[]>([]);
  const [agents, setAgents]     = useState<AgentConfig[]>([]);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newTask, setNewTask]   = useState<TaskConfig>({ ...EMPTY_TASK });
  const [saving, setSaving]     = useState<string | null>(null);
  const [error, setError]       = useState<string | null>(null);

  useEffect(() => {
    listTasks().then(setTasks).catch(console.error);
    listAgents().then(setAgents).catch(console.error);
  }, []);

  const agentName = (id: string) =>
    agents.find(a => a.id === id)?.role || id || '—';

  async function handleSave(task: TaskConfig) {
    setSaving(task.id);
    try {
      const updated = await updateTask(task.id, task);
      setTasks(prev => prev.map(t => t.id === updated.id ? updated : t));
    } catch (e) { setError(String(e)); }
    finally { setSaving(null); }
  }

  async function handleCreate() {
    if (!newTask.id.trim() || !newTask.agent_id) {
      setError('El ID y el Agente son obligatorios');
      return;
    }
    setSaving('new');
    try {
      const created = await createTask(newTask);
      setTasks(prev => [...prev, created]);
      setNewTask({ ...EMPTY_TASK });
      setCreating(false);
      setExpanded(created.id);
    } catch (e) { setError(String(e)); }
    finally { setSaving(null); }
  }

  async function handleDelete(id: string) {
    if (!confirm(`¿Eliminar la tarea "${id}"?`)) return;
    try {
      await deleteTask(id);
      setTasks(prev => prev.filter(t => t.id !== id));
      if (expanded === id) setExpanded(null);
    } catch (e) { setError(String(e)); }
  }

  // Group tasks by agent
  const tasksByAgent: Record<string, TaskConfig[]> = {};
  tasks.forEach(t => {
    if (!tasksByAgent[t.agent_id]) tasksByAgent[t.agent_id] = [];
    tasksByAgent[t.agent_id].push(t);
  });

  return (
    <div className="p-8 space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <ClipboardList className="h-7 w-7 text-primary" /> Tareas
          </h1>
          <p className="text-muted-foreground mt-1">
            Cada tarea está asignada a un agente y define qué debe hacer y qué resultado se espera.
            Las tareas se encadenan en los Flujos.
          </p>
        </div>
        <button
          onClick={() => { setCreating(true); setExpanded(null); setError(null); }}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          <Plus className="h-4 w-4" /> Nueva Tarea
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
          <button className="ml-3 underline" onClick={() => setError(null)}>Cerrar</button>
        </div>
      )}

      {/* Create form */}
      {creating && (
        <Card className="border-primary/40">
          <CardContent className="pt-5 space-y-4">
            <p className="text-sm font-semibold text-primary">Nueva Tarea</p>
            <div className="grid grid-cols-2 gap-4">
              <Field label="ID (único, sin espacios)" value={newTask.id}
                onChange={v => setNewTask(p => ({ ...p, id: v.replace(/\s/g, '_') }))} />
              <Field label="Título" value={newTask.title}
                onChange={v => setNewTask(p => ({ ...p, title: v }))} />
            </div>
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Agente responsable</label>
              <select
                value={newTask.agent_id}
                onChange={e => setNewTask(p => ({ ...p, agent_id: e.target.value }))}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="">— Seleccionar agente —</option>
                {agents.map(a => (
                  <option key={a.id} value={a.id}>{a.role} ({a.id})</option>
                ))}
              </select>
            </div>
            <Field label="Descripción / Prompt" value={newTask.description}
              onChange={v => setNewTask(p => ({ ...p, description: v }))} multiline rows={4} />
            <Field label="Resultado esperado" value={newTask.expected_result}
              onChange={v => setNewTask(p => ({ ...p, expected_result: v }))} multiline rows={2} />
            <div className="flex gap-2 pt-1">
              <button onClick={handleCreate} disabled={saving === 'new'}
                className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors">
                <Save className="h-3.5 w-3.5" />
                {saving === 'new' ? 'Creando…' : 'Crear Tarea'}
              </button>
              <button onClick={() => setCreating(false)}
                className="rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-secondary transition-colors">
                Cancelar
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tasks grouped by agent */}
      {Object.keys(tasksByAgent).length > 0 ? (
        Object.entries(tasksByAgent).map(([agentId, agentTasks]) => (
          <section key={agentId}>
            <div className="flex items-center gap-2 mb-3">
              <div className="h-6 w-6 rounded-full bg-primary/10 text-primary text-[10px] font-bold flex items-center justify-center">
                {(agentName(agentId) || agentId)[0]?.toUpperCase()}
              </div>
              <h2 className="text-sm font-semibold">{agentName(agentId)}</h2>
              <span className="text-xs text-muted-foreground font-mono">({agentId})</span>
              <span className="ml-auto text-xs text-muted-foreground">
                {agentTasks.length} tarea{agentTasks.length !== 1 ? 's' : ''}
              </span>
            </div>
            <div className="space-y-2 ml-2 pl-4 border-l border-border/60">
              {agentTasks.map(task => (
                <TaskCard
                  key={task.id}
                  task={task}
                  agents={agents}
                  expanded={expanded === task.id}
                  saving={saving === task.id}
                  onToggle={() => setExpanded(expanded === task.id ? null : task.id)}
                  onSave={handleSave}
                  onDelete={() => handleDelete(task.id)}
                />
              ))}
            </div>
          </section>
        ))
      ) : !creating && (
        <p className="text-sm text-muted-foreground text-center py-12">
          No hay tareas configuradas. Crea la primera.
        </p>
      )}
    </div>
  );
}

function TaskCard({
  task, agents, expanded, saving, onToggle, onSave, onDelete,
}: {
  task: TaskConfig; agents: AgentConfig[]; expanded: boolean; saving: boolean;
  onToggle: () => void; onSave: (t: TaskConfig) => void; onDelete: () => void;
}) {
  const [local, setLocal] = useState<TaskConfig>(task);
  useEffect(() => setLocal(task), [task]);

  return (
    <Card>
      <button
        className="w-full flex items-center justify-between px-5 py-3.5 text-left hover:bg-secondary/30 transition-colors"
        onClick={onToggle}
      >
        <div>
          <p className="text-sm font-medium">{local.title || local.id}</p>
          <p className="text-xs text-muted-foreground font-mono">{local.id}</p>
        </div>
        {expanded ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
      </button>

      {expanded && (
        <CardContent className="pt-0 space-y-4 border-t border-border">
          <div className="grid grid-cols-2 gap-4 pt-4">
            <Field label="Título" value={local.title}
              onChange={v => setLocal(p => ({ ...p, title: v }))} />
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Agente responsable</label>
              <select
                value={local.agent_id}
                onChange={e => setLocal(p => ({ ...p, agent_id: e.target.value }))}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {agents.map(a => (
                  <option key={a.id} value={a.id}>{a.role} ({a.id})</option>
                ))}
              </select>
            </div>
          </div>
          <Field label="Descripción / Prompt" value={local.description}
            onChange={v => setLocal(p => ({ ...p, description: v }))} multiline rows={6} />
          <Field label="Resultado esperado" value={local.expected_result}
            onChange={v => setLocal(p => ({ ...p, expected_result: v }))} multiline rows={3} />
          <div className="flex justify-between pt-1">
            <button onClick={() => onSave(local)} disabled={saving}
              className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors">
              <Save className="h-3.5 w-3.5" />
              {saving ? 'Guardando…' : 'Guardar cambios'}
            </button>
            <button onClick={onDelete}
              className="flex items-center gap-2 rounded-lg border border-destructive/40 px-3 py-2 text-sm text-destructive hover:bg-destructive/10 transition-colors">
              <Trash2 className="h-3.5 w-3.5" /> Eliminar
            </button>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

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
