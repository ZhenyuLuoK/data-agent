import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listRuns } from '@/api/client';
import type { RunStatus, RunSummary } from '@/api/types';
import { RunStatusBadge } from '@/components/StatusBadge';
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState';
import { RefreshIcon, TerminalIcon } from '@/components/Icon';
import { useI18n } from '@/i18n/I18nProvider';

const STATUS_FILTERS: (RunStatus | 'all')[] = [
  'all',
  'queued',
  'running',
  'succeeded',
  'failed',
  'cancelled',
  'timeout',
];

const fmtDuration = (ms: number | null) => {
  if (ms == null) return '—';
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rs = Math.round(s % 60);
  return `${m}m ${rs}s`;
};

const fmtTime = (iso: string | null) => {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
};

export function RunsPage() {
  const { t } = useI18n();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<RunStatus | 'all'>('all');

  const load = () => {
    setRuns(null);
    setError(null);
    listRuns({ limit: 100, status: filter === 'all' ? undefined : filter })
      .then(setRuns)
      .catch((e: Error) => setError(e.message));
  };

  useEffect(load, [filter]);

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      <div className="flex items-end justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight mb-1">{t('runs.title')}</h1>
          <p className="text-sm text-[color:var(--color-fg-muted)]">{t('runs.subtitle')}</p>
        </div>
        <button className="btn" onClick={load}>
          <RefreshIcon size={14} /> {t('common.refresh')}
        </button>
      </div>

      <div className="surface p-2 mb-4 flex items-center gap-1 flex-wrap">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            className={`btn btn-sm ${filter === s ? 'btn-primary' : 'btn-ghost'}`}
            onClick={() => setFilter(s)}
          >
            {s === 'all' ? t('common.all') : s}
          </button>
        ))}
      </div>

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : runs === null ? (
        <LoadingState />
      ) : runs.length === 0 ? (
        <EmptyState
          title={t('runs.empty.title')}
          description={t('runs.empty.desc')}
          icon={<TerminalIcon />}
          action={
            <Link to="/tasks" className="btn btn-primary">
              {t('runs.empty.cta')}
            </Link>
          }
        />
      ) : (
        <div className="surface overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-[color:var(--color-fg-muted)]">
                <th className="px-4 py-3 font-medium">{t('runs.col.runId')}</th>
                <th className="px-4 py-3 font-medium">{t('runs.col.task')}</th>
                <th className="px-4 py-3 font-medium">{t('runs.col.source')}</th>
                <th className="px-4 py-3 font-medium">{t('runs.col.status')}</th>
                <th className="px-4 py-3 font-medium">{t('runs.col.started')}</th>
                <th className="px-4 py-3 font-medium">{t('runs.col.duration')}</th>
                <th className="px-4 py-3 font-medium text-right">{t('common.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r, idx) => (
                <tr
                  key={r.run_id}
                  className="border-t border-[color:var(--color-border-subtle)] hover:bg-[color:var(--color-surface-hover)] transition-colors"
                  style={{
                    background: idx % 2 === 0 ? 'transparent' : 'var(--color-bg-raised)',
                  }}
                >
                  <td className="px-4 py-3 font-mono text-xs">
                    <Link to={`/runs/${r.run_id}`} className="text-[color:var(--color-accent)] hover:underline">
                      {r.run_id}
                    </Link>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-[color:var(--color-fg-muted)]">
                    {r.task_id}
                  </td>
                  <td className="px-4 py-3">
                    <span className="chip">{r.source}</span>
                  </td>
                  <td className="px-4 py-3">
                    <RunStatusBadge status={r.status} />
                  </td>
                  <td className="px-4 py-3 text-xs text-[color:var(--color-fg-muted)]">
                    {fmtTime(r.started_at)}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{fmtDuration(r.duration_ms)}</td>
                  <td className="px-4 py-3 text-right">
                    <Link to={`/runs/${r.run_id}`} className="btn btn-sm">
                      {t('runs.view')}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
