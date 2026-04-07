import type {
  AgentConfig,
  CrewConfig,
  ExecutionRecord,
  Flow,
  Initiative,
  LMStudioStatus,
  NiaConfig,
  TaskConfig,
  ToolConfig,
} from './types';

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`API ${res.status}: ${detail}`);
  }
  return res.json() as Promise<T>;
}

// --- Config (combined) ---
export const getConfig = () => apiFetch<CrewConfig>('/api/config');
export const updateConfig = (cfg: CrewConfig) =>
  apiFetch<{ ok: boolean; message: string }>('/api/config', {
    method: 'PUT',
    body: JSON.stringify(cfg),
  });
export const getLMStudioStatus = () => apiFetch<LMStudioStatus>('/api/config/lmstudio');

// --- Agents ---
export const listAgents = () => apiFetch<AgentConfig[]>('/api/agents');
export const createAgent = (a: AgentConfig) =>
  apiFetch<AgentConfig>('/api/agents', { method: 'POST', body: JSON.stringify(a) });
export const updateAgent = (id: string, a: AgentConfig) =>
  apiFetch<AgentConfig>(`/api/agents/${id}`, { method: 'PUT', body: JSON.stringify(a) });
export const deleteAgent = (id: string) =>
  apiFetch<{ ok: boolean }>(`/api/agents/${id}`, { method: 'DELETE' });

// --- Tasks ---
export const listTasks = () => apiFetch<TaskConfig[]>('/api/tasks');
export const createTask = (t: TaskConfig) =>
  apiFetch<TaskConfig>('/api/tasks', { method: 'POST', body: JSON.stringify(t) });
export const updateTask = (id: string, t: TaskConfig) =>
  apiFetch<TaskConfig>(`/api/tasks/${id}`, { method: 'PUT', body: JSON.stringify(t) });
export const deleteTask = (id: string) =>
  apiFetch<{ ok: boolean }>(`/api/tasks/${id}`, { method: 'DELETE' });

// --- Tools (read-only) ---
export const listTools = () => apiFetch<ToolConfig[]>('/api/tools');

// --- Flows ---
export const listFlows = () => apiFetch<Flow[]>('/api/flows');
export const createFlow = (f: Flow) =>
  apiFetch<Flow>('/api/flows', { method: 'POST', body: JSON.stringify(f) });
export const updateFlow = (id: string, f: Flow) =>
  apiFetch<Flow>(`/api/flows/${id}`, { method: 'PUT', body: JSON.stringify(f) });
export const deleteFlow = (id: string) =>
  apiFetch<{ ok: boolean }>(`/api/flows/${id}`, { method: 'DELETE' });

// --- Executions ---
export const listExecutions = (limit = 50) =>
  apiFetch<ExecutionRecord[]>(`/api/executions?limit=${limit}`);
export const getExecution = (id: string) =>
  apiFetch<ExecutionRecord>(`/api/executions/${id}`);
export const runCrew = (inputText: string, flowId?: string) =>
  apiFetch<{ execution_id: string; message: string }>('/api/crew/run', {
    method: 'POST',
    body: JSON.stringify({ input_text: inputText, flow_id: flowId }),
  });

// --- Initiatives ---
export const listInitiatives = () =>
  apiFetch<{ initiatives: Initiative[]; total: number }>('/api/initiatives');

// --- WebSocket ---
export function createExecutionSocket(
  executionId: string,
  onEvent: (event: string) => void,
  onDone: () => void,
): WebSocket {
  const wsBase = API_BASE.replace(/^http/, 'ws');
  const ws = new WebSocket(`${wsBase}/ws/execution/${executionId}`);
  ws.onmessage = (e) => {
    if (e.data === '__DONE__') {
      onDone();
      ws.close();
    } else {
      onEvent(e.data);
    }
  };
  ws.onerror = () => onDone();
  return ws;
}

// --- Nia config ---
export const getNiaConfig = () => apiFetch<NiaConfig>('/api/nia/config');
export const updateNiaConfig = (cfg: NiaConfig) =>
  apiFetch<NiaConfig>('/api/nia/config', {
    method: 'PUT',
    body: JSON.stringify(cfg),
  });
