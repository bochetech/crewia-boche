'use client';
import { useEffect, useState } from 'react';
import { Settings, Palette, Check } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

// ---------------------------------------------------------------------------
// Theme definitions
// ---------------------------------------------------------------------------

interface Theme {
  id: string;
  label: string;
  description: string;
  primaryHsl: string;   // for the preview swatch
  bgHsl: string;
  emoji: string;
}

const THEMES: Theme[] = [
  {
    id: 'dark',
    label: 'Dark',
    description: 'Azul oscuro — el clásico',
    primaryHsl: '238 82% 63%',
    bgHsl: '222 47% 6%',
    emoji: '🌙',
  },
  {
    id: 'ocean',
    label: 'Ocean',
    description: 'Cyan profundo',
    primaryHsl: '199 89% 48%',
    bgHsl: '207 50% 6%',
    emoji: '🌊',
  },
  {
    id: 'forest',
    label: 'Forest',
    description: 'Verde bosque',
    primaryHsl: '142 76% 36%',
    bgHsl: '150 30% 6%',
    emoji: '🌲',
  },
  {
    id: 'sunset',
    label: 'Sunset',
    description: 'Rosa vibrante',
    primaryHsl: '345 80% 55%',
    bgHsl: '345 30% 6%',
    emoji: '🌅',
  },
  {
    id: 'purple',
    label: 'Purple',
    description: 'Violeta profundo',
    primaryHsl: '270 80% 60%',
    bgHsl: '270 30% 6%',
    emoji: '🔮',
  },
  {
    id: 'light',
    label: 'Light',
    description: 'Fondo claro',
    primaryHsl: '238 82% 56%',
    bgHsl: '0 0% 98%',
    emoji: '☀️',
  },
];

const STORAGE_KEY = 'crewia-theme';

// ---------------------------------------------------------------------------
// Hook — applies theme to <html> and persists to localStorage
// ---------------------------------------------------------------------------

function useTheme() {
  const [theme, setThemeState] = useState<string>('dark');

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY) ?? 'dark';
    setThemeState(stored);
    document.documentElement.setAttribute('data-theme', stored);
  }, []);

  const setTheme = (id: string) => {
    setThemeState(id);
    document.documentElement.setAttribute('data-theme', id);
    localStorage.setItem(STORAGE_KEY, id);
  };

  return { theme, setTheme };
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SettingsPage() {
  const { theme, setTheme } = useTheme();

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Settings className="h-7 w-7 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Ajustes</h1>
          <p className="text-sm text-muted-foreground">Personaliza la apariencia del panel</p>
        </div>
      </div>

      {/* Theme selector */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Palette className="h-4 w-4" />
            Tema de color
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {THEMES.map((t) => {
              const active = theme === t.id;
              return (
                <button
                  key={t.id}
                  onClick={() => setTheme(t.id)}
                  className={`group relative flex flex-col gap-2 rounded-xl border-2 p-3 text-left transition-all hover:scale-[1.02] ${
                    active
                      ? 'border-primary bg-primary/5'
                      : 'border-border bg-secondary/20 hover:border-primary/40'
                  }`}
                >
                  {/* Swatch */}
                  <div
                    className="h-12 rounded-lg flex items-end justify-end p-1.5 overflow-hidden"
                    style={{ background: `hsl(${t.bgHsl})` }}
                  >
                    <div
                      className="h-4 w-4 rounded-full shadow-md"
                      style={{ background: `hsl(${t.primaryHsl})` }}
                    />
                  </div>
                  {/* Label */}
                  <div>
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm">{t.emoji}</span>
                      <span className="text-sm font-semibold">{t.label}</span>
                      {active && (
                        <Check className="h-3.5 w-3.5 text-primary ml-auto" />
                      )}
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-0.5">{t.description}</p>
                  </div>
                </button>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Info */}
      <p className="text-xs text-muted-foreground">
        El tema se guarda automáticamente en el navegador (localStorage).
      </p>
    </div>
  );
}
