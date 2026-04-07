'use client';
import { useEffect, useState } from 'react';
import { BotMessageSquare, Plus, Trash2, Save, ChevronDown, ChevronUp, Wrench } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { listAgents, createAgent, updateAgent, deleteAgent, listTools } from '@/lib/api';
import type { AgentConfig, ToolConfig } from '@/lib/types';

const EMPTY_AGENT: AgentConfig = {
  id: '', role: '', goal: '', backstory: '', max_iter: 3,
  llm_model: 'gemini-2.5-flash', tools: [],
};

const LLM_OPTIONS = [
  'gemini-2.5-flash', 'gemini-2.5-pro',
  'openai/gpt-4o', 'openai/gpt-4o-mini',
  'lmstudio-model',
];

export default function AgentsPage() {
  const [agents, setAgents]       = useState<AgentConfig[]>([]);
  const [tools, setTools]         = useState<ToolConfig[]>([]);
  const [expanded, setExpanded]   = useState<string | null>(null);
  const [creating, setCreating]   = useState(false);
  const [newAgent, setNewAgent]   = useState<AgentConfig>({ ...EMPTY_AGENT });
  const [saving, setSaving]       = useState<string | null>(null);
  const [error, setError]         = useState<string | null>(null);

  useEffect(() => {
    listAgents().then(setAgents).catch(console.error);
    listTools().then(setTools).catch(console.error);
  }, []);

  async function handleSave(agent: AgentConfig) {
    setSaving(agent.id);
    try {
      const updated = await updateAgent(agent.id, agent);
      setAgents(prev => prev.map(a => a.id === updated.id ? updated : a));
    } catch (e) { setError(String(e)); }
    finally { setSaving(null); }
  }

  async function handleCreate() {
    if (!newAgent.id.trim() || !newAgent.role.trim()) {
      setError('El ID y el Rol son obligatorios');
      return;
    }
    setSaving('new');
    try {
      const created = await createAgent(newAgent);
      setAgents(prev => [...prev, created]);
      setNewAgent({ ...EMPTY_AGENT });
      setCreating(false);
      setExpanded(created.id);
    } catch (e) { setError(String(e)); }
    finally { setSaving(null); }
  }

  async function handleDelete(id: string) {
    if (!confirm(`¿Eliminar el agente "${id}"? Esta acción no se puede deshacer.`)) return;
    try {
      await deleteAgent(id);
      setAgents(prev => prev.filter(a => a.id !== id));
      if (expanded === id) setExpanded(null);
    } catch (e) { setError(String(e)); }
  }

  function toggleTool(agent: AgentConfig, toolId: string): AgentConfig {
    const has = agent.tools.includes(toolId);
    return { ...agent, tools: has ? agent.tools.filter(t => t !== toolId) : [...agent.tools, toolId] };
  }

  return (
    <div className="p-8 space-y-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <BotMessageSquare className="h-7 w-7 text-primary" /> Agentes
          </h1>
          <p className="text-muted-foreground mt-1">
            Cada agente tiene un rol, objetivo y backstory que guía su comportamiento.
            Los agentes se asignan a tareas dentro de los flujos.
          </p>
        </div>
        <button
          onClick={() => { setCreating(true); setExpanded(null); setError(null); }}
          className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          <Plus className="h-4 w-4" /> Nuevo Agente
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
            <p className="text-sm font-semibold text-primary">Nuevo Agente</p>
            <div className="grid grid-cols-2 gap-4">
              <Field label="ID (único, sin espacios)" value={newAgent.id}
                onChange={v => setNewAgent(p => ({ ...p, id: v.replace(/\s/g, '_') }))} />
              <Field label="Rol" value={newAgent.role}
                onChange={v => setNewAgent(p => ({ ...p, role: v }))} />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-muted-foreground mb-1">Modelo LLM</label>
                <select
                  value={newAgent.llm_model}
                  onChange={e => setNewAgent(p => ({ ...p, llm_model: e.target.value }))}
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  {LLM_OPTIONS.map(m => <option key={m}>{m}</option>)}
                </select>
              </div>
              <Field label="Max iteraciones" value={String(newAgent.max_iter)}
                onChange={v => setNewAgent(p => ({ ...p, max_iter: parseInt(v) || 1 }))} />
            </div>
            <Field label="Objetivo (goal)" value={newAgent.goal}
              onChange={v => setNewAgent(p => ({ ...p, goal: v }))} multiline />
            <Field label="Backstory" value={newAgent.backstory}
              onChange={v => setNewAgent(p => ({ ...p, backstory: v }))} multiline rows={3} />
            <div className="flex gap-2 pt-1">
              <button onClick={handleCreate} disabled={saving === 'new'}
                className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors">
                <Save className="h-3.5 w-3.5" />
                {saving === 'new' ? 'Creando…' : 'Crear Agente'}
              </button>
              <button onClick={() => setCreating(false)}
                className="rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-secondary transition-colors">
                Cancelar
              </button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Agent list */}
      <div className="space-y-3">
        {agents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            tools={tools}
            expanded={expanded === agent.id}
            saving={saving === agent.id}
            onToggle={() => setExpanded(expanded === agent.id ? null : agent.id)}
            onSave={handleSave}
            onDelete={() => handleDelete(agent.id)}
            onToggleTool={(toolId) => {
              const updated = toggleTool(agent, toolId);
              setAgents(prev => prev.map(a => a.id === agent.id ? updated : a));
            }}
          />
        ))}
        {agents.length === 0 && !creating && (
          <p className="text-sm text-muted-foreground text-center py-12">
            No hay agentes configurados. Crea el primero.
          </p>
        )}
      </div>
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function AgentCard({
  agent, tools, expanded, saving,
  onToggle, onSave, onDelete, onToggleTool,
}: {
  agent: AgentConfig;
  tools: ToolConfig[];
  expanded: boolean;
  saving: boolean;
  onToggle: () => void;
  onSave: (a: AgentConfig) => void;
  onDelete: () => void;
  onToggleTool: (toolId: string) => void;
}) {
  const [local, setLocal] = useState<AgentConfig>(agent);
  useEffect(() => setLocal(agent), [agent]);

  return (
    <Card>
      <button
        className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-secondary/30 transition-colors"
        onClick={onToggle}
      >
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary/10 text-primary text-xs font-bold">
            {(local.role || local.id)[0]?.toUpperCase()}
          </div>
          <div>
            <p className="text-sm font-semibold">{local.role || local.id}</p>
            <p className="text-xs text-muted-foreground font-mono">{local.id}
              {local.tools.length > 0 && (
                <span className="ml-2 text-primary/70">
                  · {local.tools.length} tool{local.tools.length !== 1 ? 's' : ''}
                </span>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground font-mono">{local.llm_model}</span>
          {expanded ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
        </div>
      </button>

      {expanded && (
        <CardContent className="pt-0 space-y-4 border-t border-border">
          <div className="grid grid-cols-2 gap-4 pt-4">
            <Field label="Rol" value={local.role} onChange={v => setLocal(p => ({ ...p, role: v }))} />
            <div>
              <label className="block text-xs text-muted-foreground mb-1">Modelo LLM</label>
              <select
                value={local.llm_model}
                onChange={e => setLocal(p => ({ ...p, llm_model: e.target.value }))}
                className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {LLM_OPTIONS.map(m => <option key={m}>{m}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Max iteraciones" value={String(local.max_iter)}
              onChange={v => setLocal(p => ({ ...p, max_iter: parseInt(v) || 1 }))} />
          </div>
          <Field label="Objetivo (goal)" value={local.goal}
            onChange={v => setLocal(p => ({ ...p, goal: v }))} multiline />
          <Field label="Backstory" value={local.backstory}
            onChange={v => setLocal(p => ({ ...p, backstory: v }))} multiline rows={5} />

          {/* Tools assignment */}
          <div>
            <p className="text-xs font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
              <Wrench className="h-3.5 w-3.5" /> Herramientas asignadas
            </p>
            <div className="grid grid-cols-2 gap-2">
              {tools.map(tool => (
                <label key={tool.id}
                  className="flex items-start gap-2 rounded-md border border-border px-3 py-2 cursor-pointer hover:bg-secondary/50 transition-colors">
                  <input
                    type="checkbox"
                    checked={local.tools.includes(tool.id)}
                    onChange={() => {
                      const has = local.tools.includes(tool.id);
                      setLocal(p => ({
                        ...p,
                        tools: has ? p.tools.filter(t => t !== tool.id) : [...p.tools, tool.id],
                      }));
                      onToggleTool(tool.id);
                    }}
                    className="mt-0.5 accent-primary"
                  />
                  <div>
                    <p className="text-xs font-medium">{tool.name}</p>
                    <p className="text-[10px] text-muted-foreground line-clamp-2">{tool.description}</p>
                  </div>
                </label>
              ))}
            </div>
          </div>

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
