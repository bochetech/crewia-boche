// Shared TypeScript types matching the FastAPI Pydantic models

export type ExecutionStatus = 'pending' | 'running' | 'approved' | 'rejected' | 'error';

export interface AgentStepEvent {
  execution_id: string;
  agent: string;
  event: 'started' | 'tool_call' | 'tool_result' | 'completed' | 'error' | 'finished';
  payload: Record<string, unknown>;
  timestamp: string;
}

export interface ExecutionRecord {
  id: string;
  input_text: string;
  flow_id: string | null;
  status: ExecutionStatus;
  foco: string | null;
  initiative_id: string | null;
  action: string | null;
  result: Record<string, unknown> | null;
  steps: AgentStepEvent[];
  started_at: string;
  finished_at: string | null;
  error: string | null;
}

export interface AgentConfig {
  id: string;
  role: string;
  goal: string;
  backstory: string;
  max_iter: number;
  llm_model: string;
  tools: string[];   // list of tool ids assigned to this agent
}

export interface TaskConfig {
  id: string;
  title: string;
  description: string;
  expected_result: string;
  agent_id: string;  // id of the agent that owns this task
}

export interface ToolConfig {
  id: string;
  name: string;
  description: string;
  source: string;
  parameters: string[];
}

export interface FlowStep {
  agent_id: string;
  task_id: string;
  label: string;
  parallel_group: string | null;
}

export interface Flow {
  id: string;
  name: string;
  description: string;
  goal: string;
  steps: FlowStep[];
  created_at?: string;
}

export interface CrewConfig {
  agents: AgentConfig[];
  tasks: TaskConfig[];
  tools: ToolConfig[];
  flows: Flow[];
}

export interface Initiative {
  id: string;
  title: string;
  status: string;
  foco: string;
  objective?: string;
  impact?: string;
  owner?: string;
  deadline?: string;
}

export interface LMStudioStatus {
  status: 'connected' | 'disconnected';
  models?: string[];
  base_url: string;
  error?: string;
}
