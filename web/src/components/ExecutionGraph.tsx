'use client';
import React, { useCallback, useEffect, useMemo } from 'react';
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  type NodeProps,
  Handle,
  Position,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/badge';
import type { AgentStepEvent, ExecutionRecord } from '@/lib/types';

// ---------------------------------------------------------------------------
// Agent metadata
// ---------------------------------------------------------------------------
const AGENT_META: Record<string, { label: string; color: string; description: string }> = {
  strategist: {
    label: 'Triage Strategist',
    color: 'hsl(238 82% 63%)',
    description: 'Clasifica la iniciativa en Focos F1-F4 o la rechaza como JUNK',
  },
  ba: {
    label: 'Business Analyst',
    color: 'hsl(199 89% 48%)',
    description: 'Deduplica y documenta la iniciativa en el HTML SSOT',
  },
  researcher: {
    label: 'Researcher',
    color: 'hsl(142 76% 36%)',
    description: 'Valida viabilidad técnica e investiga benchmarks del mercado',
  },
  coordinator: {
    label: 'Coordinator',
    color: 'hsl(45 93% 47%)',
    description: 'Aprueba el resultado final antes de escribir al SSOT',
  },
};

// ---------------------------------------------------------------------------
// Custom Agent Node
// ---------------------------------------------------------------------------
function AgentNode({ data }: NodeProps) {
  const meta = AGENT_META[data.agentId] ?? { label: data.agentId, color: '#888', description: '' };
  const statusColors: Record<string, string> = {
    idle:      'bg-muted-foreground/30',
    running:   'bg-blue-500/20 border-blue-500/50 animate-pulse_glow',
    completed: 'bg-emerald-500/20 border-emerald-500/50',
    error:     'bg-destructive/20 border-destructive/50',
  };

  return (
    <div
      className={cn(
        'relative rounded-xl border-2 bg-card p-4 shadow-lg min-w-[180px] cursor-pointer transition-all hover:scale-105',
        statusColors[data.status ?? 'idle'],
      )}
      onClick={data.onSelect}
      style={{ borderColor: meta.color }}
    >
      <Handle type="target" position={Position.Left} className="opacity-0" />
      <div className="flex items-start gap-3">
        {/* Status dot */}
        <span
          className={cn(
            'mt-1 h-2.5 w-2.5 rounded-full shrink-0',
            data.status === 'running'   ? 'bg-blue-400 animate-ping' :
            data.status === 'completed' ? 'bg-emerald-400' :
            data.status === 'error'     ? 'bg-red-400' : 'bg-muted-foreground/40',
          )}
        />
        <div>
          <p className="text-sm font-semibold leading-tight" style={{ color: meta.color }}>
            {meta.label}
          </p>
          {data.foco && (
            <Badge variant="secondary" className="mt-1 text-[10px]">{data.foco}</Badge>
          )}
          {data.toolCalls > 0 && (
            <p className="mt-1 text-[10px] text-muted-foreground">{data.toolCalls} tool calls</p>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Right} className="opacity-0" />
    </div>
  );
}

const nodeTypes = { agentNode: AgentNode };

// ---------------------------------------------------------------------------
// Build nodes + edges from execution record
// ---------------------------------------------------------------------------
function buildGraph(
  execution: ExecutionRecord | null,
  onSelectAgent: (id: string) => void,
): { nodes: Node[]; edges: Edge[] } {
  const AGENT_IDS = ['strategist', 'ba', 'researcher', 'coordinator'];
  const X_POSITIONS: Record<string, number> = {
    strategist: 0,
    ba: 300,
    researcher: 300,
    coordinator: 600,
  };
  const Y_POSITIONS: Record<string, number> = {
    strategist: 100,
    ba: 0,
    researcher: 200,
    coordinator: 100,
  };

  // Compute per-agent status from steps
  const agentStatus: Record<string, string> = {};
  const agentToolCalls: Record<string, number> = {};
  let focoDetected: string | null = null;

  if (execution) {
    focoDetected = execution.foco;
    for (const step of execution.steps) {
      const a = step.agent;
      if (step.event === 'started')    agentStatus[a] = 'running';
      if (step.event === 'completed')  agentStatus[a] = 'completed';
      if (step.event === 'error')      agentStatus[a] = 'error';
      if (step.event === 'tool_call')  agentToolCalls[a] = (agentToolCalls[a] ?? 0) + 1;
    }
    if (execution.status === 'approved' || execution.status === 'rejected' || execution.status === 'error') {
      // Mark remaining idle agents
      AGENT_IDS.forEach((id) => {
        if (!agentStatus[id]) agentStatus[id] = 'idle';
      });
    }
  }

  const nodes: Node[] = AGENT_IDS.map((id) => ({
    id,
    type: 'agentNode',
    position: { x: X_POSITIONS[id], y: Y_POSITIONS[id] },
    data: {
      agentId: id,
      status: agentStatus[id] ?? 'idle',
      foco: id === 'strategist' ? focoDetected : null,
      toolCalls: agentToolCalls[id] ?? 0,
      onSelect: () => onSelectAgent(id),
    },
  }));

  const edges: Edge[] = [
    { id: 'e-str-ba',   source: 'strategist', target: 'ba',         animated: agentStatus['ba'] === 'running' },
    { id: 'e-str-res',  source: 'strategist', target: 'researcher',  animated: agentStatus['researcher'] === 'running' },
    { id: 'e-ba-coo',   source: 'ba',         target: 'coordinator', animated: agentStatus['coordinator'] === 'running' },
    { id: 'e-res-coo',  source: 'researcher', target: 'coordinator', animated: agentStatus['coordinator'] === 'running' },
  ];

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
interface ExecutionGraphProps {
  execution: ExecutionRecord | null;
  onSelectAgent: (agentId: string) => void;
}

export function ExecutionGraph({ execution, onSelectAgent }: ExecutionGraphProps) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => buildGraph(execution, onSelectAgent),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Re-build graph when execution steps change
  useEffect(() => {
    const { nodes: n, edges: e } = buildGraph(execution, onSelectAgent);
    setNodes(n);
    setEdges(e);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [execution?.steps?.length, execution?.status]);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges],
  );

  return (
    <div className="h-full w-full rounded-lg overflow-hidden border border-border">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} size={1} color="hsl(222 47% 14%)" />
        <Controls showInteractive={false} />
        <MiniMap nodeColor={(n) => AGENT_META[n.id]?.color ?? '#888'} maskColor="hsl(222 47% 6% / 0.7)" />
      </ReactFlow>
    </div>
  );
}
