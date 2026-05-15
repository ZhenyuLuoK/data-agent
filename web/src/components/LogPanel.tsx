import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { VariableSizeList, type ListChildComponentProps } from 'react-window';
import type { LogLine } from '@/api/types';
import { useRunStreamStore } from '@/state/runStreamStore';
import { fetchAgentLog } from '@/api/client';
import { toast } from '@/state/toastStore';
import { DownloadIcon, PauseIcon, PlayIcon, SearchIcon } from '@/components/Icon';
import { useI18n } from '@/i18n/I18nProvider';

const LEVELS = ['ALL', 'DEBUG', 'INFO', 'WARN', 'ERROR'] as const;
type Level = (typeof LEVELS)[number];

const LEVEL_COLORS: Record<string, string> = {
  DEBUG: 'var(--color-fg-faint)',
  INFO: 'var(--color-info)',
  WARN: 'var(--color-warning)',
  ERROR: 'var(--color-danger)',
};

const ROW_HEIGHT = 20;
const CHAR_WIDTH = 7.6; // monospace 12px ~ 7.6px char

const LEVEL_RE = /\b(DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL)\b/;

function detectLevel(text: string): string | undefined {
  const m = text.match(LEVEL_RE);
  if (!m) return undefined;
  const raw = m[1];
  return raw === 'WARNING' ? 'WARN' : raw === 'CRITICAL' ? 'ERROR' : raw;
}

interface RowMeta {
  line: LogLine;
  level?: string;
  height: number;
}

interface RowsContext {
  rows: RowMeta[];
}

const Row = ({ index, style, data }: ListChildComponentProps<RowsContext>) => {
  const { rows } = data;
  const meta = rows[index];
  const colour = meta.level ? LEVEL_COLORS[meta.level] : 'var(--color-fg-muted)';

  return (
    <div
      style={{
        ...style,
        display: 'flex',
        gap: 8,
        paddingLeft: 12,
        paddingRight: 12,
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
        lineHeight: '20px',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
        overflow: 'hidden',
        color: 'var(--color-fg)',
        borderLeft: meta.level === 'ERROR' ? '2px solid var(--color-danger)' :
          meta.level === 'WARN' ? '2px solid var(--color-warning)' : '2px solid transparent',
      }}
    >
      <span style={{ color: 'var(--color-fg-faint)', flexShrink: 0 }}>
        {String(index + 1).padStart(5, ' ')}
      </span>
      {meta.level && (
        <span style={{ color: colour, flexShrink: 0, fontWeight: 600 }}>
          {meta.level.padEnd(5)}
        </span>
      )}
      <span style={{ flex: 1, minWidth: 0 }}>
        {meta.line.text}
      </span>
    </div>
  );
};

export function LogPanel({ runId }: { runId: string }) {
  const { t } = useI18n();
  const logLines = useRunStreamStore((s) => s.logLines);
  const truncated = useRunStreamStore((s) => s.truncatedSnapshot);
  const appendFullLog = useRunStreamStore((s) => s.appendFullLog);
  const connection = useRunStreamStore((s) => s.connection);

  const [autoScroll, setAutoScroll] = useState(true);
  const [paused, setPaused] = useState(false);
  const [level, setLevel] = useState<Level>('ALL');
  const [keyword, setKeyword] = useState('');
  const autoLoadedRef = useRef(false);

  // Auto-load full log when snapshot is truncated
  useEffect(() => {
    if (!truncated || autoLoadedRef.current) return;
    autoLoadedRef.current = true;
    fetchAgentLog(runId)
      .then((text) => {
        appendFullLog(text);
      })
      .catch(() => {
        // Silent fail — user can still click the manual button
      });
  }, [truncated, runId, appendFullLog]);

  const listRef = useRef<VariableSizeList | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });

  // Resize observer
  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const cr = entry.contentRect;
        setContainerSize({ width: cr.width, height: cr.height });
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  // Snapshot of lines (paused: freeze the array reference at pause-time)
  const renderedLines = useRef<LogLine[]>(logLines);
  if (!paused) renderedLines.current = logLines;

  const rows = useMemo<RowMeta[]>(() => {
    const kw = keyword.trim().toLowerCase();
    const filtered = renderedLines.current.filter((l) => {
      if (level !== 'ALL') {
        const lv = detectLevel(l.text);
        if (lv !== level) return false;
      }
      if (kw && !l.text.toLowerCase().includes(kw)) return false;
      return true;
    });
    const charsPerLine = Math.max(40, Math.floor((containerSize.width - 80) / CHAR_WIDTH));
    return filtered.map((line) => {
      const lv = detectLevel(line.text);
      const wrappedLines = Math.max(1, Math.ceil(line.text.length / charsPerLine));
      return { line, level: lv, height: wrappedLines * ROW_HEIGHT };
    });
  }, [logLines, paused, level, keyword, containerSize.width]);

  // VariableSizeList needs to know that row sizes might have changed
  useEffect(() => {
    listRef.current?.resetAfterIndex(0, true);
  }, [rows]);

  // Auto-scroll on new content
  useEffect(() => {
    if (!autoScroll || paused) return;
    if (!listRef.current) return;
    listRef.current.scrollToItem(rows.length - 1, 'end');
  }, [rows.length, autoScroll, paused]);

  const onScroll = useCallback(
    ({ scrollOffset }: { scrollOffset: number }) => {
      const totalHeight = rows.reduce((acc, r) => acc + r.height, 0);
      const atBottom = scrollOffset + containerSize.height >= totalHeight - 40;
      if (atBottom !== autoScroll) setAutoScroll(atBottom);
    },
    [rows, containerSize.height, autoScroll],
  );

  const loadFullLog = async () => {
    try {
      const text = await fetchAgentLog(runId);
      appendFullLog(text);
      toast.success(t('log.loadFullSuccess'));
    } catch (err) {
      toast.danger(t('log.loadFullFailed'), (err as Error).message);
    }
  };

  return (
    <div className="flex flex-col h-full surface" style={{ borderRadius: 0 }}>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[color:var(--color-border)] flex-wrap">
        <button
          className={`btn btn-sm ${autoScroll ? 'btn-primary' : ''}`}
          onClick={() => {
            const next = !autoScroll;
            setAutoScroll(next);
            if (next) listRef.current?.scrollToItem(rows.length - 1, 'end');
          }}
          title={t('log.follow')}
        >
          {autoScroll ? t('log.following') : t('log.follow')}
        </button>
        <button
          className={`btn btn-sm ${paused ? 'btn-primary' : ''}`}
          onClick={() => setPaused((v) => !v)}
        >
          {paused
            ? <><PlayIcon size={12} /> {t('log.resume')}</>
            : <><PauseIcon size={12} /> {t('log.pause')}</>}
        </button>

        <div className="flex items-center surface px-1 py-0.5 gap-0.5">
          {LEVELS.map((lv) => (
            <button
              key={lv}
              className={`btn btn-sm btn-ghost ${level === lv ? 'btn-primary' : ''}`}
              onClick={() => setLevel(lv)}
            >
              {lv}
            </button>
          ))}
        </div>

        <div className="relative flex-1 min-w-[160px]">
          <SearchIcon
            size={12}
            style={{
              position: 'absolute',
              left: 8,
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'var(--color-fg-faint)',
            }}
          />
          <input
            className="input pl-7 font-mono"
            placeholder={t('log.filterPlaceholder')}
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            style={{ height: 26, fontSize: 12 }}
          />
        </div>

        <span className="chip" title={t('log.connection')}>
          <span
            className={`status-dot ${
              connection === 'open'
                ? 'status-done'
                : connection === 'reconnecting' || connection === 'connecting'
                  ? 'status-running pulse-running'
                  : 'status-failed'
            }`}
          />
          {connection}
        </span>

        <span className="chip">{rows.length} / {renderedLines.current.length}</span>

        <a
          className="btn btn-sm"
          href={`/api/runs/${encodeURIComponent(runId)}/files/agent.log`}
          target="_blank"
          rel="noreferrer"
          title={t('log.downloadRaw')}
        >
          <DownloadIcon size={12} />
        </a>
      </div>

      {truncated && (
        <div
          className="px-3 py-2 text-xs flex items-center justify-between"
          style={{ background: 'oklch(40% 0.12 80 / 0.18)', color: 'var(--color-warning)' }}
        >
          <span>{t('log.truncated')}</span>
          <button className="btn btn-sm" onClick={loadFullLog}>{t('log.loadFull')}</button>
        </div>
      )}

      <div
        ref={containerRef}
        className="flex-1 min-h-0"
        style={{ background: 'var(--color-bg-raised)' }}
      >
        {containerSize.height > 0 && (
          <VariableSizeList
            ref={listRef}
            height={containerSize.height}
            width={containerSize.width}
            itemCount={rows.length}
            itemSize={(idx) => rows[idx]?.height ?? ROW_HEIGHT}
            itemData={{ rows }}
            onScroll={onScroll}
            overscanCount={20}
          >
            {Row}
          </VariableSizeList>
        )}
      </div>
    </div>
  );
}
