import { useEffect, useState } from 'react';
// Note: useNavigate is intentionally NOT imported — header link uses <Link>
import { useParams, Link } from 'react-router-dom';
import { useRunStream } from '@/hooks/useRunStream';
import { useRunStreamStore, isTerminal } from '@/state/runStreamStore';
import { LogPanel } from '@/components/LogPanel';
import { DagFlow } from '@/components/DagFlow';
import { StepTimeline } from '@/components/StepTimeline';
import { AgentGraph } from '@/components/AgentGraph';
import { ArtifactsPanel } from '@/components/ArtifactsPanel';
import { RunStatusBadge } from '@/components/StatusBadge';
import { RunConfigModal } from '@/components/RunConfigModal';
import { SplitPane } from '@/components/SplitPane';
import {
  XIcon,
  RefreshIcon,
  ExternalLinkIcon,
  ChevronDownIcon,
} from '@/components/Icon';
import { cancelRun, getRun, getTask } from '@/api/client';
import { toast } from '@/state/toastStore';
import { useI18n } from '@/i18n/I18nProvider';
import type { TaskBrief } from '@/api/types';

const fmtDuration = (ms: number) => {
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rs = Math.round(s % 60);
  return `${m}m ${rs}s`;
};

export function RunDetailPage() {
  const { runId } = useParams();
  const { t } = useI18n();
  useRunStream(runId ?? null);

  const run = useRunStreamStore((s) => s.run);
  const status = useRunStreamStore((s) => s.status);
  const [task, setTask] = useState<TaskBrief | null>(null);
  const [questionExpanded, setQuestionExpanded] = useState(false);
  const [now, setNow] = useState(Date.now());
  const [cancelling, setCancelling] = useState(false);
  const [rerunOpen, setRerunOpen] = useState(false);
  const [bottomOpen, setBottomOpen] = useState(true);

  // tick for elapsed timer
  useEffect(() => {
    if (isTerminal(status)) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [status]);

  // fetch task brief once we know task_id
  useEffect(() => {
    if (!run?.task_id || run.source !== 'builtin') return;
    if (task?.task_id === run.task_id) return;
    getTask(run.task_id).then(setTask).catch(() => undefined);
  }, [run?.task_id, run?.source, task?.task_id]);

  if (!runId) return null;

  const startedAt = run?.started_at ? Date.parse(run.started_at) : null;
  const finishedAt = run?.finished_at ? Date.parse(run.finished_at) : null;
  const elapsed =
    startedAt && (finishedAt ?? now) > startedAt
      ? (finishedAt ?? now) - startedAt
      : null;

  const onCancel = async () => {
    if (!window.confirm(t('run.confirmCancel'))) return;
    setCancelling(true);
    try {
      await cancelRun(runId);
      toast.info(t('run.cancelSent'));
    } catch (err) {
      toast.danger(t('run.cancelFailed'), (err as Error).message);
      setCancelling(false);
    }
  };

  // Auto-clear cancelling state once status becomes terminal
  useEffect(() => {
    if (cancelling && isTerminal(status)) setCancelling(false);
  }, [cancelling, status]);

  const refresh = async () => {
    try {
      const fresh = await getRun(runId);
      useRunStreamStore.setState({ run: fresh, status: fresh.status });
    } catch (err) {
      toast.danger(t('run.refreshFailed'), (err as Error).message);
    }
  };

  const question = task?.question ?? run?.task_id;

  return (
    <div className="h-[calc(100vh-56px)] flex flex-col">
      {/* ── Header ── */}
      <header className="flex items-start gap-4 px-5 py-3 border-b border-[color:var(--color-border)]">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <Link to="/runs" className="text-xs text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)]">
              {t('run.back')}
            </Link>
            <span className="font-mono text-xs text-[color:var(--color-fg-faint)]">{runId}</span>
            <RunStatusBadge status={status} />
            {run?.source && <span className="chip">{run.source}</span>}
            {run?.task_id && <span className="chip font-mono">{run.task_id}</span>}
            {elapsed != null && <span className="chip font-mono">{fmtDuration(elapsed)}</span>}
          </div>
          {question && (
            <button
              className="text-sm text-left w-full text-[color:var(--color-fg-muted)] hover:text-[color:var(--color-fg)] transition-colors"
              onClick={() => setQuestionExpanded((v) => !v)}
              title={t('run.expandHint')}
            >
              <ChevronDownIcon
                size={12}
                style={{
                  display: 'inline',
                  marginRight: 4,
                  transition: 'transform 200ms var(--ease-out-expo)',
                  transform: questionExpanded ? 'rotate(0)' : 'rotate(-90deg)',
                }}
              />
              {questionExpanded ? (
                <span className="whitespace-pre-wrap">{question}</span>
              ) : (
                <span className="line-clamp-1">{question}</span>
              )}
            </button>
          )}
          {run?.failure_reason && (
            <div
              className="mt-2 text-xs px-3 py-2 rounded"
              style={{ background: 'oklch(34% 0.10 25 / 0.4)', color: 'var(--color-status-failed)' }}
            >
              {run.failure_reason}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {!isTerminal(status) ? (
            <button className="btn btn-danger btn-sm" onClick={onCancel} disabled={cancelling}>
              {cancelling ? t('run.cancelling') : <><XIcon size={12} /> {t('run.cancel')}</>}
            </button>
          ) : (
            <button className="btn btn-sm" onClick={() => setRerunOpen(true)}>
              <RefreshIcon size={12} /> {t('run.rerun')}
            </button>
          )}
          <button className="btn btn-sm" onClick={refresh} title={t('run.refresh')}>
            <RefreshIcon size={12} />
          </button>
          {run?.dag_svg_url && (
            <a className="btn btn-sm" href={run.dag_svg_url} target="_blank" rel="noreferrer">
              <ExternalLinkIcon size={12} /> dag.svg
            </a>
          )}
        </div>
      </header>

      {/* ── Main body: three-column layout ──
           Left:   StepTimeline (execution timeline)
           Center: AgentGraph  (LangGraph topology with pulse animations)
           Right:  DagFlow     (task DAG visualization)
      */}
      <div className="flex-1 min-h-0">
        <SplitPane
          storageKey="dabench.web.runDetail.leftSplit"
          defaultRatio={0.22}
          minRatio={0.12}
          maxRatio={0.4}
          dividerLabel="Timeline ↔ Graph"
          left={<StepTimeline />}
          right={
            <SplitPane
              storageKey="dabench.web.runDetail.rightSplit"
              defaultRatio={0.5}
              minRatio={0.3}
              maxRatio={0.75}
              dividerLabel="Graph ↔ DAG"
              left={<AgentGraph />}
              right={<DagFlow />}
            />
          }
        />
      </div>

      {/* ── Bottom panel: Log + Artifacts (togglable) ── */}
      <div className="border-t border-[color:var(--color-border)]">
        {/* Toggle bar */}
        <div
          className="flex items-center gap-2 px-3 py-1.5 cursor-pointer select-none"
          style={{ background: 'var(--color-surface)' }}
          onClick={() => setBottomOpen((v) => !v)}
        >
          <ChevronDownIcon
            size={12}
            style={{
              transition: 'transform 200ms var(--ease-out-expo)',
              transform: bottomOpen ? 'rotate(0)' : 'rotate(-90deg)',
              color: 'var(--color-fg-muted)',
            }}
          />
          <span className="text-xs font-medium text-[color:var(--color-fg-muted)]">
            {t('steps.tab.log')} & {t('artifact.prediction')}
          </span>
        </div>

        {bottomOpen && (
          <SplitPane
            storageKey="dabench.web.runDetail.bottomSplit"
            defaultRatio={0.5}
            minRatio={0.2}
            maxRatio={0.8}
            dividerLabel="Log ↔ Artifacts"
            left={
              <div style={{ height: 280, overflow: 'hidden' }}>
                <LogPanel runId={runId} />
              </div>
            }
            right={
              <div style={{ height: 280, overflow: 'hidden' }}>
                <ArtifactsPanel run={run} />
              </div>
            }
          />
        )}
      </div>

      {/* Re-run modal */}
      <RunConfigModal
        open={rerunOpen}
        onClose={() => setRerunOpen(false)}
        task={
          task ??
          (run
            ? {
                task_id: run.task_id,
                difficulty: 'custom',
                question: '',
                source: run.source,
                context_files: [],
              }
            : null)
        }
      />
    </div>
  );
}
