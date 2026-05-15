import type {
  CreateRunRequest,
  DefaultsResponse,
  RunSummary,
  TaskBrief,
  UploadResponse,
  RunStatus,
  ApiErrorBody,
} from './types';

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(status: number, code: string | undefined, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let code: string | undefined;
  let message = res.statusText || `HTTP ${res.status}`;
  try {
    const body = (await res.json()) as ApiErrorBody;
    if (body?.detail && typeof body.detail === 'object') {
      code = body.detail.code;
      if (body.detail.message) message = body.detail.message;
    } else if (typeof body?.detail === 'string') {
      message = body.detail;
    }
  } catch {
    // body wasn't JSON — fall back to statusText
  }
  return new ApiError(res.status, code, message);
}

async function request<T>(
  path: string,
  init?: RequestInit & { json?: unknown },
): Promise<T> {
  const headers = new Headers(init?.headers);
  let body = init?.body;
  if (init?.json !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(init.json);
  }
  const res = await fetch(path, { ...init, headers, body });
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  const contentType = res.headers.get('Content-Type') ?? '';
  if (!contentType.includes('application/json')) {
    return (await res.text()) as unknown as T;
  }
  return (await res.json()) as T;
}

// ---------- Health ----------

export const getHealth = () =>
  request<{ ok: boolean; version?: string }>('/api/health');

// ---------- Config ----------

export const getDefaults = () => request<DefaultsResponse>('/api/config/defaults');

// ---------- Tasks ----------

export const listTasks = (params?: { keyword?: string; difficulty?: string }) => {
  const qs = new URLSearchParams();
  if (params?.keyword) qs.set('keyword', params.keyword);
  if (params?.difficulty && params.difficulty !== 'all')
    qs.set('difficulty', params.difficulty);
  const suffix = qs.toString() ? `?${qs}` : '';
  return request<TaskBrief[]>(`/api/tasks${suffix}`);
};

export const getTask = (taskId: string) =>
  request<TaskBrief>(`/api/tasks/${encodeURIComponent(taskId)}`);

export const taskContextUrl = (taskId: string, path: string) =>
  `/api/tasks/${encodeURIComponent(taskId)}/context/${path
    .split('/')
    .map(encodeURIComponent)
    .join('/')}`;

// ---------- Uploads ----------

export interface CreateUploadOptions {
  taskId?: string;
  difficulty?: string;
  question: string;
  files: File[];
}

export const createUpload = async ({
  taskId,
  difficulty,
  question,
  files,
}: CreateUploadOptions) => {
  const fd = new FormData();
  if (taskId) fd.append('task_id', taskId);
  if (difficulty) fd.append('difficulty', difficulty);
  fd.append('question', question);
  for (const file of files) {
    // Preserve folder structure if the file came from a directory drop
    const relPath = (file as File & { webkitRelativePath?: string })
      .webkitRelativePath;
    const safeRel = relPath ? relPath.replace(/^\/+/, '') : file.name;
    fd.append('files', file, safeRel);
  }
  const res = await fetch('/api/uploads', { method: 'POST', body: fd });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as UploadResponse;
};

export const deleteUpload = (uploadId: string) =>
  request<void>(`/api/uploads/${encodeURIComponent(uploadId)}`, {
    method: 'DELETE',
  });

// ---------- Runs ----------

export const createRun = (payload: CreateRunRequest) =>
  request<RunSummary>('/api/runs', { method: 'POST', json: payload });

export const listRuns = (params?: { limit?: number; status?: RunStatus }) => {
  const qs = new URLSearchParams();
  if (params?.limit) qs.set('limit', String(params.limit));
  if (params?.status) qs.set('status', params.status);
  const suffix = qs.toString() ? `?${qs}` : '';
  return request<RunSummary[]>(`/api/runs${suffix}`);
};

export const getRun = (runId: string) =>
  request<RunSummary>(`/api/runs/${encodeURIComponent(runId)}`);

export const cancelRun = (runId: string) =>
  request<RunSummary>(`/api/runs/${encodeURIComponent(runId)}/cancel`, {
    method: 'POST',
  });

export const runFileUrl = (runId: string, name: string) =>
  `/api/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(name)}`;

export const fetchAgentLog = async (runId: string) => {
  const res = await fetch(runFileUrl(runId, 'agent.log'));
  if (!res.ok) throw await parseError(res);
  return res.text();
};
