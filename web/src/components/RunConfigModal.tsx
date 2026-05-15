import { useEffect, useMemo, useState } from 'react';
import { Modal } from './Modal';
import { useDefaultsStore } from '@/state/defaultsStore';
import { getDefaults, createRun } from '@/api/client';
import { toast } from '@/state/toastStore';
import type { AgentOverrides, DefaultsResponse, TaskBrief } from '@/api/types';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '@/i18n/I18nProvider';

interface RunConfigModalProps {
  open: boolean;
  onClose: () => void;
  task: TaskBrief | null;
  uploadId?: string | null;
}

interface FormState {
  model: string;
  api_base: string;
  api_key: string;
  max_steps: string;
  temperature: string;
  task_timeout_seconds: string;
  vote_rounds: 1 | 2 | 3;
  saveAsDefault: boolean;
}

const numOrUndef = (s: string) => {
  if (s.trim() === '') return undefined;
  const n = Number(s);
  return Number.isFinite(n) ? n : undefined;
};

export function RunConfigModal({ open, onClose, task, uploadId }: RunConfigModalProps) {
  const navigate = useNavigate();
  const { t } = useI18n();
  const stored = useDefaultsStore((s) => s.defaults);
  const setStored = useDefaultsStore((s) => s.setDefaults);
  const rememberApiKey = useDefaultsStore((s) => s.rememberApiKey);
  const setRememberApiKey = useDefaultsStore((s) => s.setRememberApiKey);

  const [serverDefaults, setServerDefaults] = useState<DefaultsResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showKey, setShowKey] = useState(false);
  const [form, setForm] = useState<FormState>({
    model: '',
    api_base: '',
    api_key: '',
    max_steps: '',
    temperature: '',
    task_timeout_seconds: '',
    vote_rounds: 1,
    saveAsDefault: false,
  });

  useEffect(() => {
    if (!open) return;
    getDefaults()
      .then((d) => {
        setServerDefaults(d);
        setForm({
          model: stored.model ?? '',
          api_base: stored.api_base ?? '',
          api_key: stored.api_key ?? '',
          max_steps: stored.max_steps != null ? String(stored.max_steps) : '',
          temperature:
            stored.temperature != null ? String(stored.temperature) : '',
          task_timeout_seconds:
            stored.task_timeout_seconds != null
              ? String(stored.task_timeout_seconds)
              : '',
          vote_rounds: (stored.vote_rounds as 1 | 2 | 3) ?? (d.vote_rounds as 1 | 2 | 3),
          saveAsDefault: rememberApiKey,
        });
      })
      .catch((err: Error) => toast.danger(t('runcfg.loadDefaultsFailed'), err.message));
  }, [open, stored, rememberApiKey, t]);

  const apiKeyPlaceholder = useMemo(() => {
    if (!serverDefaults) return '';
    return serverDefaults.api_key_set
      ? t('runcfg.apiKeyHasDefault')
      : t('runcfg.apiKeyNoDefault');
  }, [serverDefaults, t]);

  const buildOverrides = (): AgentOverrides => ({
    model: form.model || undefined,
    api_base: form.api_base || undefined,
    api_key: form.api_key || undefined,
    max_steps: numOrUndef(form.max_steps),
    temperature: numOrUndef(form.temperature),
    task_timeout_seconds: numOrUndef(form.task_timeout_seconds),
    vote_rounds: form.vote_rounds,
  });

  const submit = async () => {
    if (!task) return;
    if (
      serverDefaults &&
      !serverDefaults.api_key_set &&
      !form.api_key.trim()
    ) {
      toast.warning(t('runcfg.warnApiKey'), t('runcfg.warnApiKeyDesc'));
      return;
    }
    setSubmitting(true);
    try {
      if (form.saveAsDefault) {
        setRememberApiKey(true);
        setStored({
          model: form.model,
          api_base: form.api_base,
          api_key: form.api_key,
          max_steps: numOrUndef(form.max_steps),
          temperature: numOrUndef(form.temperature),
          task_timeout_seconds: numOrUndef(form.task_timeout_seconds),
          vote_rounds: form.vote_rounds,
        });
      } else {
        // Save non-secret fields only
        setStored({
          model: form.model,
          api_base: form.api_base,
          max_steps: numOrUndef(form.max_steps),
          temperature: numOrUndef(form.temperature),
          task_timeout_seconds: numOrUndef(form.task_timeout_seconds),
          vote_rounds: form.vote_rounds,
        });
      }

      const summary = await createRun({
        source: task.source,
        task_id: task.task_id,
        upload_id: uploadId ?? null,
        agent_overrides: buildOverrides(),
      });
      toast.success(t('runcfg.runCreated'), `run_id: ${summary.run_id}`);
      onClose();
      navigate(`/runs/${summary.run_id}`);
    } catch (err) {
      const e = err as { code?: string; message?: string };
      toast.danger(`${t('runcfg.submitFailed')} · ${e.code ?? 'unknown'}`, e.message ?? '');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={task ? `${t('runcfg.title')} · ${task.task_id}` : t('runcfg.title')}
      width={620}
      footer={
        <>
          <button className="btn" onClick={onClose} disabled={submitting}>
            {t('common.cancel')}
          </button>
          <button
            className="btn btn-primary"
            onClick={submit}
            disabled={!task || submitting}
          >
            {submitting ? t('runcfg.submitting') : t('runcfg.submit')}
          </button>
        </>
      }
    >
      {task && (
        <div className="mb-4 surface p-3 text-sm">
          <div className="text-[color:var(--color-fg-muted)] text-xs uppercase tracking-wider mb-1">
            {t('runcfg.task')}
          </div>
          <div className="font-mono text-xs mb-2">{task.task_id} · {task.difficulty}</div>
          <div className="text-[color:var(--color-fg-muted)] line-clamp-3">
            {task.question}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="md:col-span-2">
          <label className="label">{t('runcfg.model')}</label>
          <input
            className="input font-mono"
            value={form.model}
            placeholder={serverDefaults?.model ?? ''}
            onChange={(e) => setForm({ ...form, model: e.target.value })}
          />
        </div>

        <div className="md:col-span-2">
          <label className="label">{t('runcfg.apiBase')}</label>
          <input
            className="input font-mono"
            value={form.api_base}
            placeholder={serverDefaults?.api_base ?? ''}
            onChange={(e) => setForm({ ...form, api_base: e.target.value })}
          />
        </div>

        <div className="md:col-span-2">
          <label className="label">{t('runcfg.apiKey')}</label>
          <div className="relative">
            <input
              className="input font-mono pr-16"
              type={showKey ? 'text' : 'password'}
              value={form.api_key}
              placeholder={apiKeyPlaceholder}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })}
              autoComplete="off"
            />
            <button
              type="button"
              className="absolute right-1 top-1 btn btn-ghost btn-sm"
              onClick={() => setShowKey((v) => !v)}
            >
              {showKey ? t('runcfg.hide') : t('runcfg.show')}
            </button>
          </div>
        </div>

        <div>
          <label className="label">{t('runcfg.maxSteps')}</label>
          <input
            className="input font-mono"
            type="number"
            min={1}
            max={1000}
            value={form.max_steps}
            placeholder={String(serverDefaults?.max_steps ?? '')}
            onChange={(e) => setForm({ ...form, max_steps: e.target.value })}
          />
        </div>

        <div>
          <label className="label">{t('runcfg.temperature')}</label>
          <input
            className="input font-mono"
            type="number"
            step="0.1"
            min={0}
            max={2}
            value={form.temperature}
            placeholder={String(serverDefaults?.temperature ?? '')}
            onChange={(e) => setForm({ ...form, temperature: e.target.value })}
          />
        </div>

        <div>
          <label className="label">{t('runcfg.timeout')}</label>
          <input
            className="input font-mono"
            type="number"
            min={0}
            value={form.task_timeout_seconds}
            placeholder={String(serverDefaults?.task_timeout_seconds ?? '')}
            onChange={(e) =>
              setForm({ ...form, task_timeout_seconds: e.target.value })
            }
          />
        </div>

        <div>
          <label className="label">{t('runcfg.voteRounds')}</label>
          <div className="flex gap-1">
            {[1, 2, 3].map((n) => (
              <button
                key={n}
                type="button"
                className={`btn btn-sm flex-1 ${
                  form.vote_rounds === n ? 'btn-primary' : ''
                }`}
                onClick={() =>
                  setForm({ ...form, vote_rounds: n as 1 | 2 | 3 })
                }
              >
                {n}
              </button>
            ))}
          </div>
        </div>

        <div className="md:col-span-2 mt-2 flex items-center gap-2">
          <input
            id="save-default"
            type="checkbox"
            checked={form.saveAsDefault}
            onChange={(e) =>
              setForm({ ...form, saveAsDefault: e.target.checked })
            }
            className="w-4 h-4 accent-[color:var(--color-accent)]"
          />
          <label htmlFor="save-default" className="text-sm cursor-pointer">
            {t('runcfg.saveAsDefault')}
            <span className="text-[color:var(--color-fg-faint)] ml-2 text-xs">
              {t('runcfg.saveAsDefaultHint')}
            </span>
          </label>
        </div>
      </div>
    </Modal>
  );
}
