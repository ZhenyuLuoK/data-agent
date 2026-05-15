import { useEffect, useState } from 'react';
import { useDefaultsStore } from '@/state/defaultsStore';
import { getDefaults } from '@/api/client';
import type { DefaultsResponse } from '@/api/types';
import { AlertIcon } from '@/components/Icon';
import { toast } from '@/state/toastStore';
import { useI18n } from '@/i18n/I18nProvider';

export function SettingsPage() {
  const { t } = useI18n();
  const stored = useDefaultsStore((s) => s.defaults);
  const setStored = useDefaultsStore((s) => s.setDefaults);
  const remember = useDefaultsStore((s) => s.rememberApiKey);
  const setRemember = useDefaultsStore((s) => s.setRememberApiKey);
  const clear = useDefaultsStore((s) => s.clear);

  const [defaults, setDefaults] = useState<DefaultsResponse | null>(null);
  const [model, setModel] = useState(stored.model ?? '');
  const [apiBase, setApiBase] = useState(stored.api_base ?? '');
  const [apiKey, setApiKey] = useState(stored.api_key ?? '');
  const [maxSteps, setMaxSteps] = useState(
    stored.max_steps != null ? String(stored.max_steps) : '',
  );
  const [temperature, setTemperature] = useState(
    stored.temperature != null ? String(stored.temperature) : '',
  );
  const [voteRounds, setVoteRounds] = useState<1 | 2 | 3>(
    (stored.vote_rounds as 1 | 2 | 3) ?? 1,
  );
  const [showKey, setShowKey] = useState(false);

  useEffect(() => {
    getDefaults().then(setDefaults).catch(() => setDefaults(null));
  }, []);

  const save = () => {
    setStored({
      model,
      api_base: apiBase,
      api_key: apiKey,
      max_steps: maxSteps ? Number(maxSteps) : undefined,
      temperature: temperature ? Number(temperature) : undefined,
      vote_rounds: voteRounds,
    });
    toast.success(
      t('settings.saved'),
      remember ? t('settings.savedPersisted') : t('settings.savedMemoryOnly'),
    );
  };

  return (
    <div className="max-w-3xl mx-auto px-6 py-8">
      <h1 className="text-2xl font-semibold tracking-tight mb-1">{t('settings.title')}</h1>
      <p className="text-sm text-[color:var(--color-fg-muted)] mb-6">{t('settings.subtitle')}</p>

      <div
        className="surface p-4 mb-5 flex items-start gap-3"
        style={{ borderLeft: '3px solid var(--color-warning)' }}
      >
        <AlertIcon size={18} className="text-[color:var(--color-warning)] shrink-0 mt-0.5" />
        <div className="text-sm">
          <div className="font-medium mb-0.5">{t('settings.privacy.title')}</div>
          <div className="text-[color:var(--color-fg-muted)] leading-relaxed">
            {t('settings.privacy.desc.before')}
            <strong className="text-[color:var(--color-fg)]"> {t('settings.privacy.desc.warn')}</strong>
          </div>
        </div>
      </div>

      <div className="surface p-5 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="md:col-span-2">
            <label className="label">{t('runcfg.model')}</label>
            <input
              className="input font-mono"
              value={model}
              placeholder={defaults?.model ?? ''}
              onChange={(e) => setModel(e.target.value)}
            />
          </div>
          <div className="md:col-span-2">
            <label className="label">{t('runcfg.apiBase')}</label>
            <input
              className="input font-mono"
              value={apiBase}
              placeholder={defaults?.api_base ?? ''}
              onChange={(e) => setApiBase(e.target.value)}
            />
          </div>
          <div className="md:col-span-2">
            <label className="label">{t('runcfg.apiKey')}</label>
            <div className="relative">
              <input
                className="input font-mono pr-16"
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                placeholder={
                  defaults?.api_key_set ? t('runcfg.apiKeyHasDefault') : t('runcfg.apiKeyNoDefault')
                }
                onChange={(e) => setApiKey(e.target.value)}
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
              value={maxSteps}
              placeholder={String(defaults?.max_steps ?? '')}
              onChange={(e) => setMaxSteps(e.target.value)}
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
              value={temperature}
              placeholder={String(defaults?.temperature ?? '')}
              onChange={(e) => setTemperature(e.target.value)}
            />
          </div>
          <div>
            <label className="label">{t('runcfg.voteRounds')}</label>
            <div className="flex gap-1">
              {[1, 2, 3].map((n) => (
                <button
                  key={n}
                  className={`btn btn-sm flex-1 ${
                    voteRounds === n ? 'btn-primary' : ''
                  }`}
                  onClick={() => setVoteRounds(n as 1 | 2 | 3)}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="divider" />

        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            className="w-4 h-4 accent-[color:var(--color-accent)]"
            checked={remember}
            onChange={(e) => setRemember(e.target.checked)}
          />
          {t('settings.saveLabel')}
        </label>

        <div className="flex items-center gap-2 pt-2">
          <button className="btn btn-primary" onClick={save}>{t('common.save')}</button>
          <button
            className="btn btn-ghost"
            onClick={() => {
              clear();
              setModel(''); setApiBase(''); setApiKey('');
              setMaxSteps(''); setTemperature(''); setVoteRounds(1);
              toast.info(t('settings.cleared'));
            }}
          >
            {t('settings.clear')}
          </button>
        </div>
      </div>

      {defaults && (
        <div className="mt-6 surface p-4 text-xs font-mono text-[color:var(--color-fg-muted)]">
          <div className="text-[color:var(--color-fg-faint)] uppercase tracking-wider text-[10px] mb-2">
            {t('settings.serverDefaults')}
          </div>
          <div>model: {defaults.model}</div>
          <div>api_base: {defaults.api_base}</div>
          <div>api_key_set: {String(defaults.api_key_set)}</div>
          <div>max_steps: {defaults.max_steps}</div>
          <div>temperature: {defaults.temperature}</div>
          <div>vote_rounds: {defaults.vote_rounds}</div>
          <div>max_concurrent_runs: {defaults.max_concurrent_runs}</div>
        </div>
      )}
    </div>
  );
}
