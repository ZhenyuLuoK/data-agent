import { useMemo } from 'react';
import { useRunStreamStore } from '@/state/runStreamStore';
import { useI18n } from '@/i18n/I18nProvider';
import type { WSStep, DagNode } from '@/api/types';

interface TimelineEntry {
  step: WSStep;
  nodeGoal: string | null;
  nodeIndex: number | null;
  isPlan: boolean;
  isActive: boolean;
}

export function StepTimeline() {
  const { t } = useI18n();
  const steps = useRunStreamStore((s) => s.steps);
  const dag = useRunStreamStore((s) => s.dag);
  const status = useRunStreamStore((s) => s.status);

  const entries = useMemo<TimelineEntry[]>(() => {
    const nodeMap = new Map<string, DagNode>();
    if (dag) {
      dag.nodes.forEach((node) => nodeMap.set(node.id, node));
    }

    // Track which node is currently being executed (by order of start_node calls)
    let currentNodeIndex = 0;
    const seenNodes = new Set<string>();

    return steps.map((step, stepIndex) => {
      const isPlan = step.action === '__plan__';
      const inputAny = step.action_input as Record<string, unknown> | undefined;
      const nodeId = typeof inputAny?.node_id === 'string' ? inputAny.node_id : null;
      const node = nodeId ? nodeMap.get(nodeId) : null;

      if (nodeId && !seenNodes.has(nodeId)) {
        seenNodes.add(nodeId);
        currentNodeIndex++;
      }

      const isLast = stepIndex === steps.length - 1;
      const isActive = isLast && (status === 'running' || status === 'queued');

      return {
        step,
        nodeGoal: node?.goal ?? null,
        nodeIndex: nodeId ? currentNodeIndex : null,
        isPlan,
        isActive,
      };
    });
  }, [steps, dag, status]);

  if (entries.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center h-full gap-3 text-sm text-[color:var(--color-fg-muted)]"
        style={{ background: 'var(--color-bg-raised)' }}
      >
        <span className="status-dot status-running pulse-running" style={{ width: 12, height: 12 }} />
        {t('steps.empty')}
      </div>
    );
  }

  // Find the currently active node for the banner (last entry with a node)
  let activeEntry: TimelineEntry | undefined;
  for (let i = entries.length - 1; i >= 0; i--) {
    if (entries[i].nodeIndex !== null && !entries[i].isPlan) {
      activeEntry = entries[i];
      break;
    }
  }
  const activeBanner = activeEntry && (status === 'running' || status === 'queued')
    ? t('steps.executing', {
        index: String(activeEntry.nodeIndex ?? 0),
        desc: activeEntry.nodeGoal ?? activeEntry.step.action ?? '',
      })
    : null;

  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--color-bg-raised)' }}>
      {/* Active node banner */}
      {activeBanner && (
        <div
          className="px-4 py-2.5 text-sm font-medium flex items-center gap-2 border-b border-[color:var(--color-border)]"
          style={{
            background: 'color-mix(in oklch, var(--color-surface) 85%, var(--color-status-running) 15%)',
            color: 'var(--color-fg)',
          }}
        >
          <span className="status-dot status-running pulse-running" />
          {activeBanner}
        </div>
      )}

      {/* Timeline */}
      <div className="flex-1 overflow-auto px-4 py-3">
        <div className="relative">
          {/* Vertical line */}
          <div
            className="absolute left-[11px] top-3 bottom-3"
            style={{ width: 2, background: 'var(--color-border)' }}
          />

          {entries.map((entry, index) => (
            <TimelineItem key={index} entry={entry} index={index} />
          ))}
        </div>
      </div>
    </div>
  );
}

function TimelineItem({ entry, index }: { entry: TimelineEntry; index: number }) {
  const { t } = useI18n();
  const { step, nodeGoal, nodeIndex, isPlan, isActive } = entry;

  const dotColor = isPlan
    ? 'var(--color-info)'
    : step.action === 'mark_node_done' || step.action === 'mark_node_failed'
      ? step.action === 'mark_node_done' ? 'var(--color-status-done)' : 'var(--color-status-failed)'
      : isActive
        ? 'var(--color-status-running)'
        : 'var(--color-fg-faint)';

  const label = isPlan
    ? t('steps.plan')
    : t('steps.toolCall', { action: step.action ?? 'unknown' });

  const elapsedLabel = step.elapsed_ms != null
    ? t('steps.elapsed', { ms: String(step.elapsed_ms) })
    : null;

  // Compact display of thought (first 120 chars)
  const thoughtPreview = step.thought
    ? step.thought.length > 120 ? `${step.thought.slice(0, 120)}…` : step.thought
    : null;

  return (
    <div className="relative pl-8 pb-4 group" style={{ minHeight: 36 }}>
      {/* Dot */}
      <div
        className={`absolute left-[6px] top-[6px] w-[12px] h-[12px] rounded-full border-2 z-10 ${isActive ? 'pulse-running' : ''}`}
        style={{
          background: dotColor,
          borderColor: 'var(--color-bg-raised)',
        }}
      />

      {/* Content */}
      <div className="text-sm">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="font-medium">{label}</span>
          {nodeIndex !== null && nodeGoal && (
            <span className="text-xs text-[color:var(--color-fg-muted)] font-mono">
              #{nodeIndex}
            </span>
          )}
          {elapsedLabel && (
            <span className="text-xs text-[color:var(--color-fg-faint)] font-mono">
              {elapsedLabel}
            </span>
          )}
          <span className="text-xs text-[color:var(--color-fg-faint)] font-mono">
            step {index + 1}
          </span>
        </div>

        {nodeGoal && (
          <div className="text-xs text-[color:var(--color-fg-muted)] mt-0.5 leading-relaxed">
            {nodeGoal}
          </div>
        )}

        {thoughtPreview && (
          <div
            className="mt-1 text-xs leading-relaxed px-2.5 py-1.5 rounded"
            style={{
              background: 'var(--color-surface)',
              color: 'var(--color-fg-muted)',
              borderLeft: '2px solid var(--color-accent-soft)',
            }}
          >
            {thoughtPreview}
          </div>
        )}
      </div>
    </div>
  );
}
