'use client';
import { useEffect, useState } from 'react';
import { getNiaConfig, updateNiaConfig } from '@/lib/api';
import type { NiaConfig } from '@/lib/types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Radio,
  Save,
  Loader2,
  CheckCircle,
  MessageCircle,
  Mail,
  Volume2,
  Mic,
  Video,
  FileAudio,
  Terminal,
} from 'lucide-react';

type Tab = 'telegram' | 'email' | 'meeting';

export default function ChannelsPage() {
  const [cfg, setCfg] = useState<NiaConfig | null>(null);
  const [tab, setTab] = useState<Tab>('telegram');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getNiaConfig()
      .then(setCfg)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    if (!cfg) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await updateNiaConfig(cfg);
      setCfg(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const setTg = <K extends keyof NiaConfig['telegram']>(
    key: K,
    val: NiaConfig['telegram'][K],
  ) => setCfg((c) => c ? { ...c, telegram: { ...c.telegram, [key]: val } } : c);

  const setEm = <K extends keyof NiaConfig['email']>(
    key: K,
    val: NiaConfig['email'][K],
  ) => setCfg((c) => c ? { ...c, email: { ...c.email, [key]: val } } : c);

  if (loading)
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  if (!cfg) return <p className="text-muted-foreground">Error cargando configuración.</p>;

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Radio className="h-7 w-7 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">Canales</h1>
            <p className="text-sm text-muted-foreground">Adaptadores de entrada/salida de Nia</p>
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

      {/* Tabs */}
      <div className="flex gap-1 p-1 rounded-lg bg-muted w-fit">
        {(
          [
            { id: 'telegram', label: 'Telegram',  icon: MessageCircle },
            { id: 'email',    label: 'Email',      icon: Mail },
            { id: 'meeting',  label: 'Reuniones',  icon: Video },
          ] as const
        ).map(({ id, label, icon: Icon }) => {
          const isOn =
            id === 'telegram' ? cfg.telegram.enabled :
            id === 'email'    ? cfg.email.enabled :
            true; // meeting always available
          return (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-2 px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${
              tab === id
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            }`}
          >
            <Icon className="h-4 w-4" />
            {label}
            {id !== 'meeting' && (
              <Badge variant={isOn ? 'default' : 'secondary'} className="text-[10px] px-1.5 py-0">
                {isOn ? 'ON' : 'OFF'}
              </Badge>
            )}
          </button>
          );
        })}
      </div>

      {/* ── Telegram tab ────────────────────────────────────────────────── */}
      {tab === 'telegram' && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <MessageCircle className="h-4 w-4" />
              Canal Telegram
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <ToggleRow
              label="Habilitado"
              description="Activar el bot de Telegram"
              checked={cfg.telegram.enabled}
              onChange={(v) => setTg('enabled', v)}
            />

            <Field label="Modo">
              <select
                className="input-base"
                value={cfg.telegram.mode}
                onChange={(e) => setTg('mode', e.target.value as 'conversational' | 'triage_only')}
              >
                <option value="conversational">Conversacional (recomendado)</option>
                <option value="triage_only">Solo triage</option>
              </select>
            </Field>

            <Field label="Chat ID para notificaciones">
              <input
                className="input-base"
                placeholder="Ej: 123456789 (usa /miid en el bot)"
                value={cfg.telegram.notify_chat_id ?? ''}
                onChange={(e) =>
                  setTg('notify_chat_id', e.target.value || null)
                }
              />
              <p className="text-xs text-muted-foreground mt-1">
                Envía <code>/miid</code> al bot para obtener tu ID
              </p>
            </Field>

            <div className="grid grid-cols-2 gap-4">
              <ToggleRow
                label="Entrada de voz"
                description="Transcribir notas de voz (Whisper)"
                checked={cfg.telegram.voice_input}
                onChange={(v) => setTg('voice_input', v)}
                icon={<Mic className="h-4 w-4" />}
              />
              <ToggleRow
                label="Salida de voz"
                description="Responder con audio (gTTS)"
                checked={cfg.telegram.voice_output}
                onChange={(v) => setTg('voice_output', v)}
                icon={<Volume2 className="h-4 w-4" />}
              />
            </div>

            {/* Commands reference */}
            <div className="rounded-lg border border-border p-4 space-y-2">
              <p className="text-sm font-medium">Comandos disponibles</p>
              <div className="grid grid-cols-2 gap-1 text-xs text-muted-foreground">
                {[
                  ['/start', 'Bienvenida'],
                  ['/help', 'Ayuda'],
                  ['/flujos', 'Listar flujos'],
                  ['/iniciar', 'Ejecutar flujo'],
                  ['/nueva', 'Limpiar contexto'],
                  ['/topics', 'Ver cajones'],
                  ['/recall', 'Buscar por tema'],
                  ['/status', 'Estado del inbox'],
                  ['/miid', 'Tu chat ID'],
                ].map(([cmd, desc]) => (
                  <div key={cmd} className="flex gap-2">
                    <code className="text-primary">{cmd}</code>
                    <span>{desc}</span>
                  </div>
                ))}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Email tab ───────────────────────────────────────────────────── */}
      {tab === 'email' && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Mail className="h-4 w-4" />
              Canal Email
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">
            <ToggleRow
              label="Habilitado"
              description="Activar el watcher de IMAP"
              checked={cfg.email.enabled}
              onChange={(v) => setEm('enabled', v)}
            />

            <Field label="Intervalo de polling (segundos)">
              <input
                type="number"
                min={10}
                max={3600}
                className="input-base w-28"
                value={cfg.email.poll_interval_seconds}
                onChange={(e) =>
                  setEm('poll_interval_seconds', parseInt(e.target.value) || 60)
                }
              />
            </Field>

            {/* Pipeline visual */}
            <div>
              <p className="text-sm font-medium mb-3">Pipeline de procesamiento</p>
              <div className="space-y-2">
                {[
                  {
                    step: 'classify',
                    label: '1. Clasificar',
                    desc: 'spam / notification / important / analyzable',
                    color: 'text-yellow-500',
                  },
                  {
                    step: 'summarize',
                    label: '2. Resumir',
                    desc: 'Genera resumen ejecutivo con Nia',
                    color: 'text-blue-500',
                  },
                  {
                    step: 'notify_telegram',
                    label: '3. Notificar por Telegram',
                    desc: 'Envía resumen al chat configurado',
                    color: 'text-green-500',
                  },
                  {
                    step: 'ask_feedback',
                    label: '4. Pedir confirmación',
                    desc: 'Si es analizable → botones inline en Telegram',
                    color: 'text-purple-500',
                  },
                  {
                    step: 'execute',
                    label: '5. Ejecutar',
                    desc: 'Si el usuario confirmó → corre el flujo',
                    color: 'text-primary',
                  },
                ].map(({ step, label, desc, color }) => {
                  const active = cfg.email.pipeline.some((s) => s.step === step);
                  return (
                    <div
                      key={step}
                      className={`flex items-start gap-3 p-3 rounded-lg border transition-colors ${
                        active ? 'border-border bg-secondary/30' : 'border-dashed border-border/40 opacity-50'
                      }`}
                    >
                      <div className={`mt-0.5 h-2 w-2 rounded-full bg-current ${color} shrink-0`} />
                      <div className="flex-1 min-w-0">
                        <p className={`text-sm font-medium ${color}`}>{label}</p>
                        <p className="text-xs text-muted-foreground">{desc}</p>
                      </div>
                      <Badge variant={active ? 'default' : 'secondary'} className="text-[10px]">
                        {active ? 'activo' : 'inactivo'}
                      </Badge>
                    </div>
                  );
                })}
              </div>
              <p className="text-xs text-muted-foreground mt-3">
                El pipeline se configura en <code>config/nia.yaml</code> →{' '}
                <code>channels.email.pipeline</code>
              </p>
            </div>

            {/* IMAP credentials hint */}
            <div className="rounded-lg border border-border p-4 bg-muted/30">
              <p className="text-sm font-medium mb-2">Credenciales IMAP (.env)</p>
              <div className="space-y-1 text-xs font-mono text-muted-foreground">
                <p>IMAP_USER=tu@gmail.com</p>
                <p>IMAP_PASSWORD=contraseña</p>
                <p>IMAP_SERVER=imap.gmail.com</p>
                <p>IMAP_POLL_INTERVAL=60</p>
                <p>IMAP_NOTIFY_CHAT_ID=123456789</p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Meeting tab ─────────────────────────────────────────────────── */}
      {tab === 'meeting' && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Video className="h-4 w-4" />
                Canal Reuniones
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-5">
              <p className="text-sm text-muted-foreground">
                Nia puede transcribir y analizar reuniones de Teams, Zoom o cualquier grabación.
                Usa Whisper localmente — ningún audio sale de tu equipo.
              </p>

              {/* Flujo visual */}
              <div>
                <p className="text-sm font-medium mb-3">Flujo de procesamiento</p>
                <div className="flex items-center gap-2 flex-wrap">
                  {[
                    { icon: FileAudio, label: 'Archivo / Micrófono', color: 'text-yellow-500' },
                    { icon: null, label: '→', color: 'text-muted-foreground' },
                    { icon: Mic, label: 'ffmpeg → WAV 16kHz', color: 'text-blue-500' },
                    { icon: null, label: '→', color: 'text-muted-foreground' },
                    { icon: Volume2, label: 'Whisper', color: 'text-purple-500' },
                    { icon: null, label: '→', color: 'text-muted-foreground' },
                    { icon: Radio, label: 'Nia analiza', color: 'text-green-500' },
                  ].map(({ icon: Icon, label, color }, i) =>
                    Icon ? (
                      <div key={i} className={`flex items-center gap-1.5 text-xs font-medium ${color}`}>
                        <Icon className="h-3.5 w-3.5" />
                        {label}
                      </div>
                    ) : (
                      <span key={i} className="text-xs text-muted-foreground">{label}</span>
                    )
                  )}
                </div>
              </div>

              {/* Modelos Whisper */}
              <div className="rounded-lg border border-border p-4 space-y-3">
                <p className="text-sm font-medium">Modelos Whisper disponibles</p>
                <div className="space-y-2">
                  {[
                    { model: 'tiny',   speed: '★★★★★', accuracy: '★★☆☆☆', use: 'Pruebas rápidas' },
                    { model: 'base',   speed: '★★★★☆', accuracy: '★★★☆☆', use: 'Uso diario (recomendado)' },
                    { model: 'small',  speed: '★★★☆☆', accuracy: '★★★★☆', use: 'Mayor precisión' },
                    { model: 'medium', speed: '★★☆☆☆', accuracy: '★★★★★', use: 'Transcripciones críticas' },
                    { model: 'large',  speed: '★☆☆☆☆', accuracy: '★★★★★', use: 'Máxima calidad' },
                  ].map(({ model, speed, accuracy, use }) => (
                    <div key={model} className="grid grid-cols-4 gap-2 text-xs items-center">
                      <code className="text-primary font-mono">{model}</code>
                      <span className="text-muted-foreground" title="Velocidad">{speed}</span>
                      <span className="text-muted-foreground" title="Precisión">{accuracy}</span>
                      <span className="text-muted-foreground">{use}</span>
                    </div>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Modos de uso */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Terminal className="h-4 w-4" />
                Cómo usarlo
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">

              <div className="space-y-1">
                <p className="text-sm font-medium flex items-center gap-2">
                  <FileAudio className="h-4 w-4 text-blue-500" />
                  Archivo grabado (post-reunión)
                </p>
                <p className="text-xs text-muted-foreground mb-2">
                  Descarga la grabación de Teams/Zoom y pásasela a Nia.
                </p>
                <div className="rounded-md bg-muted p-3 space-y-1 font-mono text-xs">
                  <p><span className="text-muted-foreground"># Básico</span></p>
                  <p>make meeting FILE=reunion.mp4</p>
                  <p className="mt-2"><span className="text-muted-foreground"># Mayor precisión</span></p>
                  <p>make meeting FILE=reunion.mp4 MODEL=small</p>
                  <p className="mt-2"><span className="text-muted-foreground"># Con flujo estratégico</span></p>
                  <p>make meeting FILE=reunion.mp4 FLOW=strategy_crew</p>
                </div>
              </div>

              <div className="h-px bg-border" />

              <div className="space-y-1">
                <p className="text-sm font-medium flex items-center gap-2">
                  <Mic className="h-4 w-4 text-green-500" />
                  En tiempo real (durante la reunión)
                </p>
                <p className="text-xs text-muted-foreground mb-2">
                  Inicia antes de entrar a la llamada. Ctrl+C al terminar → Nia analiza automáticamente.
                </p>
                <div className="rounded-md bg-muted p-3 space-y-1 font-mono text-xs">
                  <p><span className="text-muted-foreground"># Micrófono físico (lo que se dice en la sala)</span></p>
                  <p>make live</p>
                  <p className="mt-2"><span className="text-muted-foreground"># Con nombre de reunión</span></p>
                  <p>make live TITLE=kickoff_q2</p>
                  <p className="mt-2"><span className="text-muted-foreground"># Audio del sistema (Teams/Zoom por parlantes)</span></p>
                  <p><span className="text-muted-foreground"># Requiere BlackHole instalado como dispositivo de salida</span></p>
                  <p>make live DEVICE=1</p>
                </div>
              </div>

              <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
                <p className="text-xs font-medium text-amber-600 dark:text-amber-400 mb-1">
                  🎧 Para capturar audio de Teams/Zoom
                </p>
                <p className="text-xs text-muted-foreground">
                  Instala <strong>BlackHole</strong> (gratis) desde{' '}
                  <code className="text-primary">existential.audio/blackhole</code>,
                  configúralo como salida de audio en macOS y usa <code>DEVICE=1</code>.
                  Así Nia escucha exactamente lo mismo que tú.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared components
// ---------------------------------------------------------------------------

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label className="text-sm font-medium text-foreground">{label}</label>
      {children}
    </div>
  );
}

function ToggleRow({
  label,
  description,
  checked,
  onChange,
  icon,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <div className="flex items-center gap-2">
        {icon && <span className="text-muted-foreground">{icon}</span>}
        <div>
          <p className="text-sm font-medium">{label}</p>
          {description && (
            <p className="text-xs text-muted-foreground">{description}</p>
          )}
        </div>
      </div>
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
    </div>
  );
}
