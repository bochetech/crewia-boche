'use client';
import { useEffect, useState } from 'react';
import { Wrench, ExternalLink, Code2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { listTools } from '@/lib/api';
import type { ToolConfig } from '@/lib/types';

export default function ToolsPage() {
  const [tools, setTools] = useState<ToolConfig[]>([]);

  useEffect(() => {
    listTools().then(setTools).catch(console.error);
  }, []);

  return (
    <div className="p-8 space-y-6 max-w-4xl">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
          <Wrench className="h-7 w-7 text-primary" /> Herramientas
        </h1>
        <p className="text-muted-foreground mt-1">
          Las herramientas son capacidades de código que los agentes pueden usar durante su ejecución.
          Se definen en Python y se asignan a agentes en la página de <strong>Agentes</strong>.
          Agregar una herramienta nueva requiere implementarla en el código fuente.
        </p>
      </div>

      {/* Info banner */}
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-400 flex items-start gap-2">
        <Code2 className="h-4 w-4 mt-0.5 shrink-0" />
        <div>
          <strong>Solo lectura:</strong> Las herramientas son clases Python registradas en el código.
          Para agregar una nueva, crea una clase que herede de <code className="bg-secondary px-1 rounded">BaseTool</code> en <code className="bg-secondary px-1 rounded">src/tools.py</code> o <code className="bg-secondary px-1 rounded">src/strategy_tools/</code>,
          y luego reinicia el backend para que aparezca aquí.
        </div>
      </div>

      {/* Tools grid */}
      <div className="grid grid-cols-1 gap-4">
        {tools.map(tool => (
          <Card key={tool.id}>
            <CardContent className="pt-5 space-y-3">
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10">
                    <Wrench className="h-4 w-4 text-primary" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold">{tool.name}</p>
                    <p className="text-xs text-muted-foreground font-mono">{tool.id}</p>
                  </div>
                </div>
                <span className="text-[10px] font-mono text-muted-foreground/60 border border-border rounded px-2 py-1">
                  read-only
                </span>
              </div>

              <p className="text-sm text-muted-foreground">{tool.description}</p>

              <div className="flex flex-wrap gap-3 text-xs">
                {tool.source && (
                  <div className="flex items-center gap-1.5 text-muted-foreground">
                    <Code2 className="h-3.5 w-3.5" />
                    <span className="font-mono">{tool.source}</span>
                  </div>
                )}
              </div>

              {tool.parameters.length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1.5">Parámetros:</p>
                  <div className="flex flex-wrap gap-1.5">
                    {tool.parameters.map(p => (
                      <span key={p}
                        className="rounded-md bg-secondary px-2 py-0.5 text-xs font-mono text-secondary-foreground">
                        {p}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
        {tools.length === 0 && (
          <p className="text-sm text-muted-foreground text-center py-12">
            Cargando herramientas…
          </p>
        )}
      </div>
    </div>
  );
}
