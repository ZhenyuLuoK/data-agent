import { useEffect, useState } from 'react';
import Papa from 'papaparse';
import type { RunSummary } from '@/api/types';
import { DownloadIcon, ExternalLinkIcon } from './Icon';
import { runFileUrl } from '@/api/client';
import { useI18n } from '@/i18n/I18nProvider';

type Tab = 'prediction' | 'trace' | 'dag' | 'log';

export function ArtifactsPanel({ run }: { run: RunSummary | null }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<Tab>('prediction');

  if (!run) {
    return (
      <div className="surface p-4 text-sm text-[color:var(--color-fg-muted)]" style={{ borderRadius: 0 }}>
        {t('artifact.metaLoading')}
      </div>
    );
  }

  const tabs: { id: Tab; label: string }[] = [
    { id: 'prediction', label: t('artifact.prediction') },
    { id: 'trace', label: t('artifact.trace') },
    { id: 'dag', label: t('artifact.dagSvg') },
    { id: 'log', label: t('artifact.rawLog') },
  ];

  const urls = {
    prediction: run.prediction_csv_url,
    trace: run.trace_url,
    dag: run.dag_svg_url,
    log: run.log_url ?? runFileUrl(run.run_id, 'agent.log'),
  };

  return (
    <div className="surface flex flex-col" style={{ borderRadius: 0, borderLeft: 'none', borderRight: 'none', borderBottom: 'none' }}>
      <div className="flex items-center gap-1 px-3 py-2 border-b border-[color:var(--color-border)] flex-wrap">
        {tabs.map((tabItem) => {
          const url = urls[tabItem.id];
          const enabled = !!url;
          return (
            <button
              key={tabItem.id}
              className={`btn btn-sm ${tab === tabItem.id ? 'btn-primary' : 'btn-ghost'}`}
              disabled={!enabled && tabItem.id !== 'log'}
              onClick={() => setTab(tabItem.id)}
            >
              {tabItem.label}
              {!enabled && tabItem.id !== 'log' && (
                <span className="text-[color:var(--color-fg-faint)] ml-1 text-[10px]">{t('common.notGenerated')}</span>
              )}
            </button>
          );
        })}
        <div className="flex-1" />
        {urls[tab] && (
          <>
            <a className="btn btn-sm" href={urls[tab]!} target="_blank" rel="noreferrer">
              <ExternalLinkIcon size={12} /> {t('common.open')}
            </a>
            <a className="btn btn-sm" href={urls[tab]!} download>
              <DownloadIcon size={12} /> {t('common.download')}
            </a>
          </>
        )}
      </div>

      <div className="max-h-[40vh] overflow-auto" style={{ background: 'var(--color-bg-raised)' }}>
        {tab === 'prediction' && (
          urls.prediction
            ? <PredictionPreview url={urls.prediction} />
            : <Hint label={t('artifact.predictionMissing')} />
        )}
        {tab === 'trace' && (
          urls.trace
            ? <TracePreview url={urls.trace} />
            : <Hint label={t('artifact.traceMissing')} />
        )}
        {tab === 'dag' && (
          urls.dag ? (
            <object data={urls.dag} type="image/svg+xml" className="w-full" style={{ minHeight: 320 }}>
              <Hint label={t('artifact.svgUnsupported')} />
            </object>
          ) : (
            <Hint label={t('artifact.dagMissing')} />
          )
        )}
        {tab === 'log' && (
          <iframe src={urls.log} className="w-full bg-white" style={{ minHeight: 320 }} title="agent.log" />
        )}
      </div>
    </div>
  );
}

function Hint({ label }: { label: string }) {
  return (
    <div className="p-8 text-center text-sm text-[color:var(--color-fg-muted)]">{label}</div>
  );
}

function PredictionPreview({ url }: { url: string }) {
  const { t } = useI18n();
  const [rows, setRows] = useState<string[][] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRows(null); setError(null);
    fetch(url)
      .then((r) => r.text())
      .then((text) => {
        const result = Papa.parse<string[]>(text, { delimiter: ',', skipEmptyLines: true });
        if (result.errors.length) setError(result.errors[0].message);
        setRows(result.data.slice(0, 200));
      })
      .catch((e: Error) => setError(e.message));
  }, [url]);

  if (error) return <Hint label={t('artifact.parseFailed', { message: error })} />;
  if (!rows) return <Hint label={t('common.loading')} />;
  if (rows.length === 0) return <Hint label={t('artifact.empty')} />;

  const [header, ...body] = rows;
  return (
    <div className="overflow-auto">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr>
            {header.map((h, i) => (
              <th
                key={i}
                className="px-3 py-2 text-left border-b border-[color:var(--color-border)] text-[color:var(--color-fg-muted)] uppercase tracking-wider"
                style={{ position: 'sticky', top: 0, background: 'var(--color-bg-elevated)' }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((r, i) => (
            <tr key={i} className="border-b border-[color:var(--color-border-subtle)]">
              {r.map((c, j) => (
                <td key={j} className="px-3 py-1.5">{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {body.length >= 200 && (
        <div className="p-2 text-center text-xs text-[color:var(--color-fg-faint)]">
          {t('artifact.first200')}
        </div>
      )}
    </div>
  );
}

function TracePreview({ url }: { url: string }) {
  const { t } = useI18n();
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setText(null); setError(null);
    fetch(url)
      .then((r) => r.text())
      .then((raw) => {
        try {
          setText(JSON.stringify(JSON.parse(raw), null, 2));
        } catch {
          setText(raw); // not strict JSON — show as-is
        }
      })
      .catch((e: Error) => setError(e.message));
  }, [url]);

  if (error) return <Hint label={t('artifact.parseFailed', { message: error })} />;
  if (text == null) return <Hint label={t('common.loading')} />;
  return (
    <pre className="p-4 text-xs font-mono whitespace-pre-wrap" style={{ color: 'var(--color-fg)' }}>
      {text}
    </pre>
  );
}
