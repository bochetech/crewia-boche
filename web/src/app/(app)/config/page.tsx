'use client';
import { useEffect, useState } from 'react';
import { Settings, Save, Plus, Trash2, ChevronDown, ChevronUp } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { getConfig, updateConfig } from '@/lib/api';
import type { AgentConfig, CrewConfig, TaskConfig } from '@/lib/types';

export default function ConfigPage() {
  const [config, setConfig]     = useState<CrewConfig | null>(null);
  const [saving, setSaving]     = useState(false);
  const [saved, setSaved]       = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    getConfig().then(setConfig).catch(console.error);
  }, []);

  async function handleSave() {
    if (!config) return;
    setSaving(true);
    try {
      await updateConfig(config);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) { console.error(e); }
    finally { setSaving(false); }
  }

  function updateAgent(idx: number, field: keyof AgentConfig, value: string | number | string[]) {
    if (!config) return;
    const agents = [...config.agents];
    agents[idx] = { ...agents[idx], [field]: value };
    setConfig({ ...config, agents });
  }

  function updateTask(idx: number, field: keyof TaskConfig, value: string) {
    if (!config) return;
    const tasks = [...config.tasks];
    tasks[idx] = { ...tasks[idx], [field]: value };
    setConfig({ ...config, tasks });
  }

  if (!config) return (
    <div className="p-8 text-sm text-muted-foreground">Cargando configuración…</div>
  );

  return (
    <div className="p-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Configuración</h1>
          <p className="text-muted-foreground mt-1">
            Edita agentes y tareas — los cambios se guardan en <code className="text-xs bg-secondary px-1 py-0.5 rounded">config/agents.yaml</code> y <code className="text-xs bg-secondary px-1 py-0.5 rounded">config/tasks.yaml</code>
          </p>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
        >
          <Save className="h-4 w-4" />
          {saved ? '✓ Guardado' : saving ? 'Guardando…' : 'Guardar'}
        </button>
      </div>

      {/* Agents */}
      <section>
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <Settings className="h-5 w-5 text-primary" /> Agentes ({config.agents.length})
        </h2>
        <div className="space-y-3">
          {config.agents.map((agent, idx) => (
            <Card key={agent.id}>
              <button
                className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-secondary/30"
                onClick={() => setExpanded(expanded === agent.id ? null : agent.id)}
              >
                <div>
                  <p className="text-sm font-semibold">{agent.role || agent.id}</p>
                  <p className="text-xs text-muted-foreground font-mono">{agent.id}</p>
                </div>
                {expanded === agent.id ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
              </button>

              {expanded === agent.id && (
                <CardContent className="pt-0 space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <Field
                      label="Role"
                      value={agent.role}
                      onChange={(v) => updateAgent(idx, 'role', v)}
                    />
                    <Field
                      label="Max iterations"
                      value={String(agent.max_iter)}
                      onChange={(v) => updateAgent(idx, 'max_iter', parseInt(v) || 1)}
                    />
                  </div>
                  <Field
                    label="Goal"
                    value={agent.goal}
                    onChange={(v) => updateAgent(idx, 'goal', v)}
                    multiline
                  />
                  <Field
                    label="Backstory"
                    value={agent.backstory}
                    onChange={(v) => updateAgent(idx, 'backstory', v)}
                    multiline
                    rows={4}
                  />
                </CardContent>
              )}
            </Card>
          ))}
        </div>
      </section>

      {/* Tasks */}
      <section>
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <Settings className="h-5 w-5 text-primary" /> Tareas ({config.tasks.length})
        </h2>
        <div className="space-y-3">
          {config.tasks.map((task, idx) => (
            <Card key={task.id}>
              <button
                className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-secondary/30"
                onClick={() => setExpanded(expanded === `task-${task.id}` ? null : `task-${task.id}`)}
              >
                <div>
                  <p className="text-sm font-semibold">{task.id}</p>
                  <p className="text-xs text-muted-foreground">Agente: {task.agent_id}</p>
                </div>
                {expanded === `task-${task.id}` ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
              </button>

              {expanded === `task-${task.id}` && (
                <CardContent className="pt-0 space-y-4">
                  <Field
                    label="Descripción"
                    value={task.description}
                    onChange={(v) => updateTask(idx, 'description', v)}
                    multiline
                    rows={5}
                  />
                  <Field
                    label="Resultado esperado"
                    value={task.expected_result}
                    onChange={(v) => updateTask(idx, 'expected_result', v)}
                    multiline
                    rows={3}
                  />
                </CardContent>
              )}
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}

function Field({
  label, value, onChange, multiline = false, rows = 2,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  multiline?: boolean;
  rows?: number;
}) {
  const cls = 'w-full rounded-lg border border-border bg-secondary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary';
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</label>
      {multiline ? (
        <textarea
          className={`${cls} resize-y`}
          rows={rows}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          className={cls}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
    </div>
  );
}
