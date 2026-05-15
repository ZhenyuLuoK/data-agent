import { useCallback, useEffect, useRef, useState } from 'react';

interface SplitPaneProps {
  /** Persistence key for the split ratio (0..1, % of left pane). */
  storageKey?: string;
  /** Initial ratio if nothing is stored. Default 0.4 (= 40% left). */
  defaultRatio?: number;
  /** Minimum/maximum ratio bounds. */
  minRatio?: number;
  maxRatio?: number;
  /** Direction of the split: vertical = side-by-side (default), horizontal = stacked. */
  direction?: 'vertical' | 'horizontal';
  /** ARIA label for the divider, surfaced to screen readers. */
  dividerLabel?: string;
  left: React.ReactNode;
  right: React.ReactNode;
}

const clamp = (n: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, n));

const loadRatio = (key: string | undefined, fallback: number): number => {
  if (!key) return fallback;
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return fallback;
    const n = Number(raw);
    return Number.isFinite(n) ? n : fallback;
  } catch {
    return fallback;
  }
};

const persistRatio = (key: string | undefined, value: number) => {
  if (!key) return;
  try {
    localStorage.setItem(key, value.toFixed(4));
  } catch {
    // ignore
  }
};

export function SplitPane({
  storageKey,
  defaultRatio = 0.4,
  minRatio = 0.18,
  maxRatio = 0.82,
  direction = 'vertical',
  dividerLabel = 'Resize',
  left,
  right,
}: SplitPaneProps) {
  const [ratio, setRatio] = useState<number>(() =>
    clamp(loadRatio(storageKey, defaultRatio), minRatio, maxRatio),
  );
  const containerRef = useRef<HTMLDivElement | null>(null);
  const draggingRef = useRef(false);

  // Persist whenever ratio changes (debounced via rAF — cheap enough to do directly).
  useEffect(() => {
    persistRatio(storageKey, ratio);
  }, [storageKey, ratio]);

  // Keep ratio inside bounds if container shrinks past the configured range.
  useEffect(() => {
    setRatio((prev) => clamp(prev, minRatio, maxRatio));
  }, [minRatio, maxRatio]);

  const updateFromClient = useCallback(
    (clientX: number, clientY: number) => {
      const el = containerRef.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const next =
        direction === 'vertical'
          ? (clientX - rect.left) / rect.width
          : (clientY - rect.top) / rect.height;
      setRatio(clamp(next, minRatio, maxRatio));
    },
    [direction, minRatio, maxRatio],
  );

  // Pointer events unify mouse + touch + pen and respect setPointerCapture.
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    (e.target as HTMLDivElement).setPointerCapture(e.pointerId);
    draggingRef.current = true;
    document.body.style.cursor = direction === 'vertical' ? 'col-resize' : 'row-resize';
    document.body.style.userSelect = 'none';
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return;
    updateFromClient(e.clientX, e.clientY);
  };

  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    try {
      (e.target as HTMLDivElement).releasePointerCapture(e.pointerId);
    } catch {
      // ignore — capture may already be lost
    }
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
  };

  const onDoubleClick = () => setRatio(defaultRatio);

  // Keyboard support: arrow keys nudge by 2%, with Shift = 8%.
  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 0.08 : 0.02;
    let next = ratio;
    if (direction === 'vertical') {
      if (e.key === 'ArrowLeft') next -= step;
      else if (e.key === 'ArrowRight') next += step;
      else if (e.key === 'Home') next = minRatio;
      else if (e.key === 'End') next = maxRatio;
      else if (e.key === 'Enter' || e.key === ' ') next = defaultRatio;
      else return;
    } else {
      if (e.key === 'ArrowUp') next -= step;
      else if (e.key === 'ArrowDown') next += step;
      else if (e.key === 'Home') next = minRatio;
      else if (e.key === 'End') next = maxRatio;
      else if (e.key === 'Enter' || e.key === ' ') next = defaultRatio;
      else return;
    }
    e.preventDefault();
    setRatio(clamp(next, minRatio, maxRatio));
  };

  const isVertical = direction === 'vertical';
  const leftStyle: React.CSSProperties = isVertical
    ? { width: `${ratio * 100}%`, minWidth: 0 }
    : { height: `${ratio * 100}%`, minHeight: 0 };
  const rightStyle: React.CSSProperties = isVertical
    ? { width: `${(1 - ratio) * 100}%`, minWidth: 0 }
    : { height: `${(1 - ratio) * 100}%`, minHeight: 0 };

  return (
    <div
      ref={containerRef}
      className="flex"
      style={{
        flexDirection: isVertical ? 'row' : 'column',
        width: '100%',
        height: '100%',
      }}
    >
      <div style={leftStyle} className="min-w-0 min-h-0">
        {left}
      </div>
      <div
        role="separator"
        aria-orientation={isVertical ? 'vertical' : 'horizontal'}
        aria-label={dividerLabel}
        aria-valuenow={Math.round(ratio * 100)}
        aria-valuemin={Math.round(minRatio * 100)}
        aria-valuemax={Math.round(maxRatio * 100)}
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onDoubleClick={onDoubleClick}
        onKeyDown={onKeyDown}
        className="group relative shrink-0 transition-colors"
        style={{
          width: isVertical ? 6 : '100%',
          height: isVertical ? '100%' : 6,
          cursor: isVertical ? 'col-resize' : 'row-resize',
          background: 'var(--color-border)',
          touchAction: 'none',
        }}
        title="拖拽调整 · 双击复位"
      >
        {/* Larger hit area & hover affordance */}
        <span
          className="absolute inset-0 transition-colors"
          style={{
            background: 'transparent',
          }}
        />
        <span
          className="absolute pointer-events-none transition-colors group-hover:bg-[color:var(--color-accent)] group-focus-visible:bg-[color:var(--color-accent)]"
          style={
            isVertical
              ? { left: 0, right: 0, top: '50%', transform: 'translateY(-50%)', height: 32, width: '100%', borderRadius: 999 }
              : { top: 0, bottom: 0, left: '50%', transform: 'translateX(-50%)', width: 32, height: '100%', borderRadius: 999 }
          }
        />
        {/* Grip dots for visual hint */}
        <span
          className="absolute pointer-events-none flex gap-[3px] opacity-60 group-hover:opacity-100"
          style={
            isVertical
              ? {
                  left: '50%',
                  top: '50%',
                  transform: 'translate(-50%, -50%)',
                  flexDirection: 'column',
                }
              : {
                  left: '50%',
                  top: '50%',
                  transform: 'translate(-50%, -50%)',
                  flexDirection: 'row',
                }
          }
        >
          <span style={{ width: 3, height: 3, borderRadius: 999, background: 'var(--color-fg-muted)' }} />
          <span style={{ width: 3, height: 3, borderRadius: 999, background: 'var(--color-fg-muted)' }} />
          <span style={{ width: 3, height: 3, borderRadius: 999, background: 'var(--color-fg-muted)' }} />
        </span>
      </div>
      <div style={rightStyle} className="min-w-0 min-h-0">
        {right}
      </div>
    </div>
  );
}
