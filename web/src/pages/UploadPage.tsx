import { useMemo, useRef, useState } from 'react';
import { createUpload } from '@/api/client';
import type { TaskBrief } from '@/api/types';
import { RunConfigModal } from '@/components/RunConfigModal';
import { UploadIcon, FileIcon, XIcon, PlayIcon, FolderIcon } from '@/components/Icon';
import { toast } from '@/state/toastStore';
import { useI18n } from '@/i18n/I18nProvider';
import type { Translator } from '@/i18n/locales';

const ALLOWED_EXTS = new Set([
  'csv', 'tsv', 'json', 'jsonl', 'xlsx', 'xls', 'parquet',
  'db', 'sqlite', 'sqlite3', 'txt', 'md',
]);
const MAX_FILE_BYTES = 200 * 1024 * 1024; // 200 MB
const MAX_TOTAL_BYTES = 1024 * 1024 * 1024; // 1 GB

interface FileEntry {
  file: File;
  relPath: string;
  error?: string;
}

const extOf = (name: string) => {
  const idx = name.lastIndexOf('.');
  return idx >= 0 ? name.slice(idx + 1).toLowerCase() : '';
};

const validateOne = (entry: FileEntry, t: Translator): string | undefined => {
  if (entry.relPath.includes('..')) return t('upload.fileError.path');
  if (entry.relPath.startsWith('/')) return t('upload.fileError.pathSlash');
  const ext = extOf(entry.file.name);
  if (!ALLOWED_EXTS.has(ext)) return t('upload.fileError.ext', { ext });
  if (entry.file.size > MAX_FILE_BYTES) return t('upload.fileError.size');
  return undefined;
};

export function UploadPage() {
  const { t } = useI18n();
  const [taskId, setTaskId] = useState('');
  const [difficulty, setDifficulty] = useState('custom');
  const [question, setQuestion] = useState('');
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [dragOver, setDragOver] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [createdTask, setCreatedTask] = useState<TaskBrief | null>(null);
  const [createdUploadId, setCreatedUploadId] = useState<string | null>(null);
  const [runOpen, setRunOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);

  const totalBytes = useMemo(
    () => entries.reduce((acc, e) => acc + e.file.size, 0),
    [entries],
  );
  const overTotal = totalBytes > MAX_TOTAL_BYTES;
  const hasErrors = entries.some((e) => e.error) || overTotal;

  const ingest = (files: FileList | File[]) => {
    const next: FileEntry[] = [];
    for (const f of Array.from(files)) {
      const rel = (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name;
      const safe = rel.replace(/^\/+/, '');
      const entry: FileEntry = { file: f, relPath: safe };
      entry.error = validateOne(entry, t);
      next.push(entry);
    }
    setEntries((prev) => [...prev, ...next]);
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    if (e.dataTransfer.files) ingest(e.dataTransfer.files);
  };

  const removeAt = (idx: number) =>
    setEntries((prev) => prev.filter((_, i) => i !== idx));

  const reset = () => {
    setTaskId(''); setDifficulty('custom'); setQuestion('');
    setEntries([]); setCreatedTask(null); setCreatedUploadId(null);
  };

  const submit = async () => {
    if (!question.trim()) {
      toast.warning(t('upload.errors.questionRequired'));
      return;
    }
    if (entries.length === 0) {
      toast.warning(t('upload.errors.fileRequired'));
      return;
    }
    if (hasErrors) {
      toast.danger(t('upload.errors.failed'), t('upload.errors.fixFiles'));
      return;
    }
    setSubmitting(true);
    try {
      const res = await createUpload({
        taskId: taskId || undefined,
        difficulty,
        question,
        files: entries.map((e) => e.file),
      });
      setCreatedTask(res.task);
      setCreatedUploadId(res.upload_id);
      toast.success(t('upload.success'), `task_id: ${res.task.task_id}`);
    } catch (err) {
      const e = err as { code?: string; message?: string };
      toast.danger(`${t('upload.errors.failed')} · ${e.code ?? 'error'}`, e.message ?? '');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-6 py-8">
      <h1 className="text-2xl font-semibold tracking-tight mb-1">{t('upload.title')}</h1>
      <p className="text-sm text-[color:var(--color-fg-muted)] mb-6">{t('upload.subtitle')}</p>

      <div className="surface p-5 space-y-5">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="md:col-span-2">
            <label className="label">{t('upload.taskId')}</label>
            <input
              className="input font-mono"
              placeholder={t('upload.taskIdPlaceholder')}
              value={taskId}
              onChange={(e) => setTaskId(e.target.value)}
              pattern="[A-Za-z0-9_]{1,64}"
            />
          </div>
          <div>
            <label className="label">{t('upload.difficulty')}</label>
            <select
              className="select"
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value)}
            >
              {['easy', 'medium', 'hard', 'custom'].map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="label">{t('upload.question')}</label>
          <textarea
            className="textarea"
            rows={5}
            placeholder={t('upload.questionPlaceholder')}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />
        </div>

        <div>
          <label className="label">{t('upload.contextFiles')}</label>
          <div
            className={`relative rounded-xl border-2 border-dashed p-8 transition-colors text-center ${
              dragOver
                ? 'border-[color:var(--color-accent)] bg-[color:var(--color-bg-elevated)]'
                : 'border-[color:var(--color-border)]'
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
          >
            <UploadIcon size={28} className="mx-auto text-[color:var(--color-fg-muted)] mb-2" />
            <div className="text-sm font-medium mb-1">{t('upload.dropzoneTitle')}</div>
            <div className="text-xs text-[color:var(--color-fg-muted)] mb-4">
              {t('upload.dropzoneHint')}
            </div>
            <div className="flex items-center justify-center gap-2">
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => fileInputRef.current?.click()}
              >
                <FileIcon size={12} /> {t('upload.pickFiles')}
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => folderInputRef.current?.click()}
              >
                <FolderIcon size={12} /> {t('upload.pickFolder')}
              </button>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              hidden
              multiple
              onChange={(e) => e.target.files && ingest(e.target.files)}
            />
            <input
              ref={folderInputRef}
              type="file"
              hidden
              multiple
              // @ts-expect-error non-standard but widely supported
              webkitdirectory=""
              directory=""
              onChange={(e) => e.target.files && ingest(e.target.files)}
            />
          </div>

          {entries.length > 0 && (
            <div className="surface mt-3 divide-y divide-[color:var(--color-border-subtle)]">
              {entries.map((e, idx) => (
                <div key={idx} className="px-4 py-2 flex items-center gap-3 text-sm">
                  <FileIcon size={14} className="text-[color:var(--color-fg-faint)]" />
                  <div className="flex-1 min-w-0">
                    <div className="font-mono text-xs truncate">{e.relPath}</div>
                    {e.error && (
                      <div className="text-xs mt-0.5" style={{ color: 'var(--color-danger)' }}>
                        {e.error}
                      </div>
                    )}
                  </div>
                  <span className="text-xs text-[color:var(--color-fg-faint)]">
                    {(e.file.size / 1024).toFixed(1)} KB
                  </span>
                  <button className="btn btn-ghost btn-sm" onClick={() => removeAt(idx)}>
                    <XIcon size={12} />
                  </button>
                </div>
              ))}
              <div className="px-4 py-2 text-xs flex items-center justify-between">
                <span className="text-[color:var(--color-fg-muted)]">
                  {t('upload.filesSummary', {
                    count: entries.length,
                    mb: (totalBytes / 1024 / 1024).toFixed(2),
                  })}
                </span>
                {overTotal && (
                  <span style={{ color: 'var(--color-danger)' }}>{t('upload.tooLargeTotal')}</span>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            className="btn btn-primary btn-lg"
            disabled={submitting || createdTask !== null}
            onClick={submit}
          >
            {submitting
              ? t('upload.uploading')
              : createdTask
                ? t('upload.uploaded')
                : t('upload.action')}
          </button>
          {createdTask && (
            <button
              className="btn btn-lg"
              onClick={() => setRunOpen(true)}
            >
              <PlayIcon /> {t('upload.runNow')}
            </button>
          )}
          {createdTask && (
            <button className="btn btn-ghost btn-lg" onClick={reset}>
              {t('upload.reset')}
            </button>
          )}
        </div>
      </div>

      <RunConfigModal
        open={runOpen}
        onClose={() => setRunOpen(false)}
        task={createdTask}
        uploadId={createdUploadId}
      />
    </div>
  );
}
