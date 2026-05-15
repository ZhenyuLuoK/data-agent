// DTOs hand-mirrored from src/data_agent_baseline/web/schemas.py.
// Keep field names byte-identical with the backend; if anything drifts,
// regenerate from /openapi.json with openapi-typescript.

export type RunStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'timeout';

export type DagNodeStatus = 'pending' | 'in_progress' | 'done' | 'failed';

export type TaskSource = 'builtin' | 'upload';

export interface ContextFile {
  path: string;
  kind: string;
  size: number | null;
}

export interface TaskBrief {
  task_id: string;
  difficulty: string;
  question: string;
  source: TaskSource;
  context_files: ContextFile[];
}

export interface AgentOverrides {
  model?: string | null;
  api_base?: string | null;
  api_key?: string | null;
  max_steps?: number | null;
  temperature?: number | null;
  task_timeout_seconds?: number | null;
  vote_rounds?: number | null;
}

export interface DefaultsResponse {
  model: string;
  api_base: string;
  api_key_set: boolean;
  max_steps: number;
  temperature: number;
  task_timeout_seconds: number;
  vote_rounds: number;
  max_concurrent_runs: number;
}

export interface CreateRunRequest {
  source: TaskSource;
  task_id: string;
  upload_id?: string | null;
  agent_overrides?: AgentOverrides;
}

export interface RunSummary {
  run_id: string;
  task_id: string;
  source: TaskSource;
  status: RunStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  prediction_csv_url: string | null;
  trace_url: string | null;
  dag_svg_url: string | null;
  log_url: string | null;
  failure_reason: string | null;
}

export interface DagNode {
  id: string;
  goal: string;
  depends_on: string[];
  suggested_tools: string[];
  expected_output: string | null;
  status: DagNodeStatus;
  started_at: string | null;
  finished_at: string | null;
  output_summary: string | null;
}

// Backend DagEdge uses pydantic alias — wire payload literally has from / to.
export interface DagEdge {
  from: string;
  to: string;
}

export interface DagSnapshot {
  nodes: DagNode[];
  edges: DagEdge[];
  final_node_id: string | null;
}

export interface UploadResponse {
  upload_id: string;
  task: TaskBrief;
}

// ---------- WS events ----------

export interface WSSnapshot {
  type: 'snapshot';
  seq: 0;
  run: RunSummary;
  dag: DagSnapshot;
  log_tail: string[];
  steps: WSStep[];
}

export interface WSLogChunk {
  type: 'log';
  seq: number;
  ts: string;
  line_id: number;
  chunk_index: number;
  chunk_total: number;
  line: string;
}

export interface WSStep {
  type: 'step';
  seq: number;
  step_index: number | null;
  thought: string | null;
  action: string | null;
  action_input: unknown;
  observation: unknown;
  raw_response: string | null;
  elapsed_ms: number | null;
}

export interface WSDagUpdate {
  type: 'dag_update';
  seq: number;
  nodes: DagNode[];
  edges: DagEdge[];
  final_node_id: string | null;
  updated_node_ids: string[];
}

export interface WSFinal {
  type: 'final';
  seq: number;
  run: RunSummary;
}

export interface WSError {
  type: 'error';
  seq: number;
  code: string;
  message: string;
}

export type WSEvent =
  | WSSnapshot
  | WSLogChunk
  | WSStep
  | WSDagUpdate
  | WSFinal
  | WSError;

// Backend error envelope: {"detail": {"code": "...", "message": "..."}}
export interface ApiErrorBody {
  detail?:
    | { code?: string; message?: string }
    | string;
}

// Re-assembled (post chunk-merge) log line
export interface LogLine {
  line_id: number;
  ts: string;
  text: string;
}
