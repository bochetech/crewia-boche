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
import type { ExecutionRecord, Flow } from '@/lib/types';

// ---------------------------------------------------------------------------
// Default colors for agents by index (when no meta is known)
// ---------------------------------------------------------------------------
const PALETTE = [
  'hsl(238 82% 63%)',  // indigo
  'hsl(199 89% 48%)',  // cyan
  'hsl(142 76% 36%)',  // green
  'hsl(45 93% 47%)',   // amber
  'hsl(345 80% 55%)',  // rose
  'hsl(270 70% 55%)',  // purple
];

function agentColor(agentId: string, index: number): string {
  // Deterministic: hash agent ID to palette
  return PALETTE[index % PALETTE.length];
}

// ---------------------------------------------------------------------------
// Custom Agent Node
// ---------------------------------------------------------------------------
function AgentNode({ data }: NodeProps) {
  const statusColors: Record<string, string> = {
    idle:      'border-border bg-card',
    running:   'bg-blue-500/20 border-blue-500/50 animate-pulse',
    completed: 'bg-emerald-500/20 border-emerald-500/50',
    error:     'bg-destructive/20 border-destructive/50',
  };

  return (
    <div
      className={cn(
        'relative rounded-xl border-2 bg-card p-4 shadow-lg min-w-[160px] cursor-pointer transition-all hover:scale-105',
        statusColors[data.status ?? 'idle'],
      )}
      onClick={data.onSelect}
      style={{ borderColor: data.color }}
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
          <p className="text-sm font-semibold leading-tight" style={{ color: data.color }}>
            {data.label}
          </p>
          <p className="text-[10px] text-muted-foreground mt-0.5">{data.taskLabel}</p>
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
// Build nodes + edges from a Flow definition + ExecutionRecord
// ---------------------------------------------------------------------------
function buildGraph(
  flow: Flow | null,
  execution: ExecutionRecord | null,
  onSelectAgent: (id: string) => void,
): { nodes: Node[]; edges: Edge[] } {
  // Default fallback: the legacy 4-agent strategy flow
  const defaultSteps = [
    { agent_id: 'strategist', task_id: 'strategy_classify', label: 'Clasificar Foco', parallel_group: null },
    { agent_id: 'ba',         task_id: 'strategy_document', label: 'Documentar HTML', parallel_group: 'analysis' },
    { agent_id: 'researcher', task_id: 'strategy_research', label: 'Validar Técnico',  parallel_group: 'analysis' },
    { agent_id: 'coordinator',task_id: 'strategy_coordinate',label: 'Aprobar',        parallel_group: null },
  ];
  const steps = (flow?.steps?.length ?? 0) > 0 ? flow!.steps : defaultSteps;

  // Compute per-agent status from execution steps
  const agentStatus: Record<string, string> = {};
  const agentToolCalls: Record<string, number> = {};
  let focoDetected: string | null = execution?.foco ?? null;

  if (execution) {
    for (const ev of execution.steps) {
      const a = ev.agent;
      if (ev.event === 'started')   agentStatus[a] = 'running';
      if (ev.event === 'completed') agentStatus[a] = 'completed';
      if (ev.event === 'error')     agentStatus[a] = 'error';
      if (ev.event === 'tool_call') agentToolCalls[a] = (agentToolCalls[a] ?? 0) + 1;
    }
  }

  // ── Layout algorithm ────────────────────────────────────────────────────
  // Group steps into columns: sequential steps each get their own column,
  // steps in the same parallel_group share a column.
  type Column = { group: string | null; stepIndices: number[] };
  const columns: Column[] = [];
  const groupToCol: Record<string, number> = {};

  steps.forEach((step, i) => {
    if (step.parallel_group) {
      if (groupToCol[step.parallel_group] !== undefined) {
        columns[groupToCol[step.parallel_group]].stepIndices.push(i);
      } else {
        groupToCol[step.parallel_group] = columns.length;
        columns.push({ group: step.parallel_group, stepIndices: [i] });
      }
    } else {
      columns.push({ group: null, stepIndices: [i] });
    }
  });

  const COL_WIDTH = 260;
  const ROW_HEIGHT = 130;

  const nodes: Node[] = steps.map((step, i) => {
    const colIdx = columns.findIndex(c => c.stepIndices.includes(i));
    const col = columns[colIdx];
    const rowInCol = col.stepIndices.indexOf(i);
    const totalInCol = col.stepIndices.length;
    const x = colIdx * COL_WIDTH;
    const y = (rowInCol - (totalInCol - 1) / 2) * ROW_HEIGHT;

    const nodeId = `${step.agent_id}_${i}`;
    const color = agentColor(step.agent_id, i);

    return {
      id: nodeId,
      type: 'agentNode',
      position: { x, y: y + 150 },
      data: {
        agentId: step.agent_id,
        label: step.label || step.agent_id,
        taskLabel: step.task_id,
        color,
        status: agentStatus[step.agent_id] ?? 'idle',
        foco: step.agent_id === 'triage_strategist' || step.agent_id === 'strategist' ? focoDetected : null,
        toolCalls: agentToolCalls[step.agent_id] ?? 0,
        onSelect: () => onSelectAgent(step.agent_id),
      },
    };
  });

  // ── Edges: connect sequential columns and parallel convergence ──────────
  const edges: Edge[] = [];
  for (let ci = 1; ci < columns.length; ci++) {
    const prevCol = columns[ci - 1];
    const currCol = columns[ci];
    for (const prevIdx of prevCol.stepIndices) {
      for (const currIdx of currCol.stepIndices) {
        const srcAgent = steps[prevIdx].agent_id;
        const tgtAgent = steps[currIdx].agent_id;
        const edgeId = `e-${prevIdx}-${currIdx}`;
        edges.push({
          id: edgeId,
          source: `${srcAgent}_${prevIdx}`,
          target: `${tgtAgent}_${currIdx}`,
          animated: agentStatus[tgtAgent] === 'running',
          style: { stroke: 'hsl(222 47% 30%)', strokeWidth: 1.5 },
        });
      }
    }
  }

  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
interface ExecutionGraphProps {
  execution: ExecutionRecord | null;
  flow?: Flow | null;
  onSelectAgent: (agentId: string) => void;
}

export function ExecutionGraph({ execution, flow = null, onSelectAgent }: ExecutionGraphProps) {
  const { nodes: initialNodes, edges: initialEdges } = useMemo(
    () => buildGraph(flow, execution, onSelectAgent),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Re-build when execution steps change or flow changes
  useEffect(() => {
    const { nodes: n, edges: e } = buildGraph(flow, execution, onSelectAgent);
    setNodes(n);
    setEdges(e);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [execution?.steps?.length, execution?.status, flow?.id]);

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
        <MiniMap
          nodeColor={(n) => (n.data as { color?: string }).color ?? '#888'}
          maskColor="hsl(222 47% 6% / 0.7)"
        />
      </ReactFlow>
    </div>
  );
}
