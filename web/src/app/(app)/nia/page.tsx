'use client';
import { useEffect, useState } from 'react';
import { getNiaConfig, updateNiaConfig, listFlows } from '@/lib/api';
import type { NiaConfig, Flow } from '@/lib/types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Bot, Save, Loader2, CheckCircle } from 'lucide-react';

const DEFAULT_NIA: NiaConfig = {
  name: 'Nia',
  role: 'Analista Estratégica de Triaje',
  personality: 'Profesional, directa y estratégica. Responde en español.',
  default_flow: 'strategy_crew',
  telegram_feedback_enabled: true,
  memory_max_topics: 10,
  telegram: {
    enabled: true,
    mode: 'conversational',
    voice_input: true,
    voice_output: true,
    notify_chat_id: null,
    commands: {},
  },
  email: {
    enabled: false,
    poll_interval_seconds: 60,
    pipeline: [],
  },
};

export default function NiaPage() {
  const [cfg, setCfg] = useState<NiaConfig>(DEFAULT_NIA);
  const [flows, setFlows] = useState<Flow[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getNiaConfig(), listFlows()])
      .then(([nia, fl]) => {
        setCfg(nia);
        setFlows(fl);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const set = <K extends keyof NiaConfig>(key: K, val: NiaConfig[K]) =>
    setCfg((c) => ({ ...c, [key]: val }));

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await updateNiaConfig(cfg);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (loading)
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Bot className="h-7 w-7 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">Nia</h1>
            <p className="text-sm text-muted-foreground">Configuración del agente central</p>
          </div>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-60 transition-colors"
        >
          {saving ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : saved ? (
            <CheckCircle className="h-4 w-4" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          {saved ? 'Guardado' : 'Guardar'}
        </button>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-destructive/10 text-destructive text-sm">{error}</div>
      )}

      {/* Identity */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Identidad</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Field label="Nombre">
            <input
              className="input-base"
              value={cfg.name}
              onChange={(e) => set('name', e.target.value)}
            />
          </Field>
          <Field label="Rol">
            <input
              className="input-base"
              value={cfg.role}
              onChange={(e) => set('role', e.target.value)}
            />
          </Field>
          <Field label="Personalidad">
            <textarea
              className="input-base resize-none"
              rows={3}
              value={cfg.personality}
              onChange={(e) => set('personality', e.target.value)}
              placeholder="Describe la personalidad de Nia…"
            />
          </Field>
        </CardContent>
      </Card>

      {/* Behavior */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Comportamiento</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Field label="Flujo por defecto">
            <select
              className="input-base"
              value={cfg.default_flow}
              onChange={(e) => set('default_flow', e.target.value)}
            >
              {flows.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} ({f.id})
                </option>
              ))}
              {flows.length === 0 && (
                <option value="strategy_crew">strategy_crew</option>
              )}
            </select>
          </Field>

          <Field label="Máx. cajones de memoria">
            <input
              type="number"
              min={1}
              max={50}
              className="input-base w-24"
              value={cfg.memory_max_topics}
              onChange={(e) => set('memory_max_topics', parseInt(e.target.value) || 10)}
            />
          </Field>

          <div className="flex items-center justify-between py-1">
            <div>
              <p className="text-sm font-medium">Feedback por Telegram</p>
              <p className="text-xs text-muted-foreground">
                Nia pregunta por Telegram antes de ejecutar acciones de email
              </p>
            </div>
            <Toggle
              checked={cfg.telegram_feedback_enabled}
              onChange={(v) => set('telegram_feedback_enabled', v)}
            />
          </div>
        </CardContent>
      </Card>

      {/* Status badges */}
      <div className="flex flex-wrap gap-2">
        <Badge variant={cfg.telegram.enabled ? 'default' : 'secondary'}>
          Telegram {cfg.telegram.enabled ? 'activo' : 'inactivo'}
        </Badge>
        <Badge variant={cfg.email.enabled ? 'default' : 'secondary'}>
          Email {cfg.email.enabled ? 'activo' : 'inactivo'}
        </Badge>
        <Badge variant="outline" className="text-muted-foreground">
          Configura los canales en la página Canales →
        </Badge>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tiny shared components
// ---------------------------------------------------------------------------

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-sm font-medium text-foreground">{label}</label>
      {children}
    </div>
  );
}

function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none ${
        checked ? 'bg-primary' : 'bg-muted'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
          checked ? 'translate-x-6' : 'translate-x-1'
        }`}
      />
    </button>
  );
}
