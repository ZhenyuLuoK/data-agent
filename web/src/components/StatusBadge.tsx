import type { RunStatus, DagNodeStatus } from '@/api/types';

const RUN_TONE: Record<RunStatus, { dot: string; label: string; fg: string }> = {
  queued: { dot: 'status-pending', label: '排队中', fg: 'text-[color:var(--color-fg-muted)]' },
  running: { dot: 'status-running pulse-running', label: '运行中', fg: 'text-[color:var(--color-status-running)]' },
  succeeded: { dot: 'status-done', label: '已完成', fg: 'text-[color:var(--color-status-done)]' },
  failed: { dot: 'status-failed', label: '失败', fg: 'text-[color:var(--color-status-failed)]' },
  cancelled: { dot: 'status-pending', label: '已取消', fg: 'text-[color:var(--color-fg-muted)]' },
  timeout: { dot: 'status-failed', label: '超时', fg: 'text-[color:var(--color-status-failed)]' },
};

const NODE_TONE: Record<DagNodeStatus, { dot: string; label: string }> = {
  pending: { dot: 'status-pending', label: 'pending' },
  in_progress: { dot: 'status-running pulse-running', label: 'running' },
  done: { dot: 'status-done', label: 'done' },
  failed: { dot: 'status-failed', label: 'failed' },
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const tone = RUN_TONE[status];
  return (
    <span className={`chip ${tone.fg}`} aria-label={`run status: ${status}`}>
      <span className={`status-dot ${tone.dot}`} />
      {tone.label}
    </span>
  );
}

export function NodeStatusBadge({ status }: { status: DagNodeStatus }) {
  const tone = NODE_TONE[status];
  return (
    <span className="chip" aria-label={`node status: ${status}`}>
      <span className={`status-dot ${tone.dot}`} />
      {tone.label}
    </span>
  );
}
