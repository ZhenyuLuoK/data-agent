import { useEffect, useMemo, useState } from 'react';
import { listTasks, getTask, taskContextUrl } from '@/api/client';
import type { TaskBrief } from '@/api/types';
import { Drawer } from '@/components/Modal';
import { RunConfigModal } from '@/components/RunConfigModal';
import { EmptyState, ErrorState, LoadingState } from '@/components/EmptyState';
import { SearchIcon, PlayIcon, FileIcon, ExternalLinkIcon } from '@/components/Icon';
import { toast } from '@/state/toastStore';
import { useI18n } from '@/i18n/I18nProvider';

const DIFFICULTIES = ['all', 'easy', 'medium', 'hard'];

export function TasksPage() {
  const { t } = useI18n();
  const [tasks, setTasks] = useState<TaskBrief[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [keyword, setKeyword] = useState('');
  const [difficulty, setDifficulty] = useState('all');
  const [selected, setSelected] = useState<TaskBrief | null>(null);
  const [detail, setDetail] = useState<TaskBrief | null>(null);
  const [runOpen, setRunOpen] = useState(false);

  const fetchTasks = () => {
    setTasks(null);
    setError(null);
    listTasks()
      .then(setTasks)
      .catch((e: Error) => setError(e.message));
  };

  useEffect(fetchTasks, []);

  const filtered = useMemo(() => {
    if (!tasks) return [];
    const kw = keyword.trim().toLowerCase();
    return tasks.filter((task) => {
      if (difficulty !== 'all' && task.difficulty !== difficulty) return false;
      if (!kw) return true;
      return (
        task.task_id.toLowerCase().includes(kw) ||
        task.question.toLowerCase().includes(kw)
      );
    });
  }, [tasks, keyword, difficulty]);

  const openDetail = async (task: TaskBrief) => {
    setSelected(task);
    setDetail(task); // optimistic
    try {
      const full = await getTask(task.task_id);
      setDetail(full);
    } catch (err) {
      toast.danger(t('tasks.detailLoadFailed'), (err as Error).message);
    }
  };

  return (
    <div className="max-w-7xl mx-auto px-6 py-8">
      <div className="flex items-end justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight mb-1">{t('tasks.title')}</h1>
          <p className="text-sm text-[color:var(--color-fg-muted)]">{t('tasks.subtitle')}</p>
        </div>
      </div>

      <div className="surface p-3 mb-4 flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[240px]">
          <SearchIcon
            size={14}
            style={{
              position: 'absolute',
              left: 10,
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'var(--color-fg-faint)',
            }}
          />
          <input
            className="input pl-8"
            placeholder={t('tasks.searchPlaceholder')}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
        </div>
        <div className="flex items-center gap-1 surface px-1 py-1">
          {DIFFICULTIES.map((d) => (
            <button
              key={d}
              className={`btn btn-sm ${difficulty === d ? 'btn-primary' : 'btn-ghost'}`}
              onClick={() => setDifficulty(d)}
            >
              {d === 'all' ? t('common.all') : d}
            </button>
          ))}
        </div>
        <span className="chip">{t('tasks.count', { count: filtered.length })}</span>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={fetchTasks} />
      ) : tasks === null ? (
        <LoadingState />
      ) : filtered.length === 0 ? (
        <EmptyState title={t('tasks.empty.title')} description={t('tasks.empty.desc')} />
      ) : (
        <div className="surface overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-[color:var(--color-fg-muted)]">
                <th className="px-4 py-3 font-medium">{t('tasks.col.id')}</th>
                <th className="px-4 py-3 font-medium">{t('tasks.col.difficulty')}</th>
                <th className="px-4 py-3 font-medium">{t('tasks.col.question')}</th>
                <th className="px-4 py-3 font-medium">{t('tasks.col.context')}</th>
                <th className="px-4 py-3 font-medium text-right">{t('common.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((task, idx) => (
                <tr
                  key={task.task_id}
                  className="border-t border-[color:var(--color-border-subtle)] hover:bg-[color:var(--color-surface-hover)] cursor-pointer transition-colors"
                  style={{ background: idx % 2 === 0 ? 'transparent' : 'var(--color-bg-raised)' }}
                  onClick={() => openDetail(task)}
                >
                  <td className="px-4 py-3 font-mono text-xs">{task.task_id}</td>
                  <td className="px-4 py-3">
                    <span className="chip">{task.difficulty}</span>
                  </td>
                  <td className="px-4 py-3 max-w-[420px] truncate text-[color:var(--color-fg-muted)]">
                    {task.question}
                  </td>
                  <td className="px-4 py-3 text-[color:var(--color-fg-muted)]">
                    {t('tasks.contextFiles', { count: task.context_files.length })}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      className="btn btn-primary btn-sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        setSelected(task);
                        setRunOpen(true);
                      }}
                    >
                      <PlayIcon size={12} /> {t('tasks.run')}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Drawer
        open={!!selected && !runOpen}
        onClose={() => setSelected(null)}
        title={selected?.task_id ?? t('runcfg.task')}
        width={560}
      >
        {detail && (
          <div className="space-y-5">
            <div className="flex items-center gap-2">
              <span className="chip">{detail.difficulty}</span>
              <span className="chip">{detail.source}</span>
              <span className="chip">
                {t('tasks.contextFiles', { count: detail.context_files.length })}
              </span>
            </div>

            <section>
              <div className="label">{t('tasks.drawer.question')}</div>
              <div className="surface p-4 text-sm leading-relaxed whitespace-pre-wrap">
                {detail.question}
              </div>
            </section>

            <section>
              <div className="label">{t('tasks.drawer.contextFiles')}</div>
              <ul className="surface divide-y divide-[color:var(--color-border-subtle)]">
                {detail.context_files.length === 0 && (
                  <li className="px-4 py-3 text-sm text-[color:var(--color-fg-muted)]">
                    {t('tasks.drawer.noContext')}
                  </li>
                )}
                {detail.context_files.map((f) => (
                  <li
                    key={f.path}
                    className="px-4 py-2 flex items-center gap-2 text-sm"
                  >
                    <FileIcon size={14} className="text-[color:var(--color-fg-faint)]" />
                    <span className="font-mono text-xs flex-1 truncate" title={f.path}>
                      {f.path}
                    </span>
                    <span className="text-xs text-[color:var(--color-fg-faint)]">
                      {f.kind} · {f.size != null ? `${(f.size / 1024).toFixed(1)} KB` : '—'}
                    </span>
                    <a
                      className="btn btn-ghost btn-sm"
                      href={taskContextUrl(detail.task_id, f.path)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLinkIcon size={12} />
                    </a>
                  </li>
                ))}
              </ul>
            </section>

            <button
              className="btn btn-primary btn-lg w-full"
              onClick={() => setRunOpen(true)}
            >
              <PlayIcon /> {t('tasks.runWithCurrent')}
            </button>
          </div>
        )}
      </Drawer>

      <RunConfigModal
        open={runOpen}
        onClose={() => setRunOpen(false)}
        task={selected}
      />
    </div>
  );
}
