import { useEffect, useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
} from '@xyflow/react';
import type { DagNode, DagSnapshot } from '@/api/types';
import { useRunStreamStore } from '@/state/runStreamStore';
import { Drawer } from './Modal';
import { NodeStatusBadge } from './StatusBadge';
import { useI18n } from '@/i18n/I18nProvider';

const STATUS_BORDER: Record<DagNode['status'], string> = {
  pending: 'var(--color-status-pending)',
  in_progress: 'var(--color-status-running)',
  done: 'var(--color-status-done)',
  failed: 'var(--color-status-failed)',
};

const STATUS_BG: Record<DagNode['status'], string> = {
  pending: 'color-mix(in oklch, var(--color-surface) 80%, var(--color-status-pending) 20%)',
  in_progress: 'color-mix(in oklch, var(--color-surface) 70%, var(--color-status-running) 30%)',
  done: 'color-mix(in oklch, var(--color-surface) 70%, var(--color-status-done) 30%)',
  failed: 'color-mix(in oklch, var(--color-surface) 70%, var(--color-status-failed) 30%)',
};

interface DagNodeData extends Record<string, unknown> {
  node: DagNode;
  highlight: boolean;
  isFinal: boolean;
  finalLabel: string;
}

function DagNodeView({ data }: NodeProps<Node<DagNodeData>>) {
  const { node, highlight, isFinal, finalLabel } = data;
  const isRunning = node.status === 'in_progress';
  const classNames = [
    highlight ? 'highlight-flash' : '',
    isRunning ? 'dag-node-pulse' : '',
  ].filter(Boolean).join(' ');

  return (
    <div
      className={classNames || undefined}
      style={{
        width: 220,
        padding: '10px 12px',
        borderRadius: 10,
        background: STATUS_BG[node.status],
        border: `${isRunning ? '2px' : '1.5px'} solid ${STATUS_BORDER[node.status]}`,
        color: 'var(--color-fg)',
        fontFamily: 'var(--font-sans)',
        fontSize: 12,
        boxShadow: isRunning
          ? '0 0 16px -2px oklch(72% 0.16 240 / 0.5)'
          : isFinal
            ? 'var(--shadow-glow)'
            : 'var(--shadow-sm)',
        transition: 'box-shadow 0.4s ease, border 0.3s ease',
      }}
    >
      <Handle type="target" position={Position.Top} style={{ background: 'var(--color-border-strong)' }} />
      <div className="flex items-center gap-2 mb-1">
        <span
          className={`status-dot status-${
            node.status === 'in_progress' ? 'running' : node.status
          }${node.status === 'in_progress' ? ' pulse-running' : ''}`}
        />
        <span className="font-mono" style={{ fontSize: 10, color: 'var(--color-fg-muted)' }}>
          {node.id}
        </span>
        {isFinal && <span className="chip" style={{ height: 16, fontSize: 9, padding: '0 6px' }}>{finalLabel}</span>}
      </div>
      <div
        style={{
          fontWeight: 500,
          fontSize: 12,
          lineHeight: 1.4,
          display: '-webkit-box',
          WebkitLineClamp: 2,
          WebkitBoxOrient: 'vertical',
          overflow: 'hidden',
        }}
        title={node.goal}
      >
        {node.goal}
      </div>
      {node.suggested_tools.length > 0 && (
        <div className="flex gap-1 mt-2 flex-wrap">
          {node.suggested_tools.slice(0, 3).map((t) => (
            <span
              key={t}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9.5,
                padding: '1px 5px',
                borderRadius: 3,
                background: 'oklch(0% 0 0 / 0.2)',
                color: 'var(--color-fg-muted)',
              }}
            >
              {t}
            </span>
          ))}
          {node.suggested_tools.length > 3 && (
            <span style={{ fontSize: 9.5, color: 'var(--color-fg-faint)' }}>
              +{node.suggested_tools.length - 3}
            </span>
          )}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} style={{ background: 'var(--color-border-strong)' }} />
    </div>
  );
}

const NODE_TYPES = { dag: DagNodeView };

interface LayoutResult {
  positions: Map<string, { x: number; y: number }>;
  width: number;
  height: number;
}

/**
 * Simple Sugiyama-style layered layout: BFS depth from roots, 1 row per depth.
 * Avoids dragging in dagre/elkjs for first iteration.
 */
function layoutDag(snap: DagSnapshot): LayoutResult {
  const positions = new Map<string, { x: number; y: number }>();
  if (snap.nodes.length === 0) return { positions, width: 0, height: 0 };

  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  for (const n of snap.nodes) {
    incoming.set(n.id, []);
    outgoing.set(n.id, []);
  }
  for (const e of snap.edges) {
    if (!incoming.has(e.to) || !outgoing.has(e.from)) continue;
    incoming.get(e.to)!.push(e.from);
    outgoing.get(e.from)!.push(e.to);
  }

  // depth via Kahn's algorithm
  const depth = new Map<string, number>();
  const queue: string[] = [];
  for (const n of snap.nodes) {
    if ((incoming.get(n.id) ?? []).length === 0) {
      depth.set(n.id, 0);
      queue.push(n.id);
    }
  }
  while (queue.length) {
    const cur = queue.shift()!;
    const d = depth.get(cur)!;
    for (const next of outgoing.get(cur) ?? []) {
      const nd = Math.max(depth.get(next) ?? 0, d + 1);
      if (nd !== depth.get(next)) {
        depth.set(next, nd);
        queue.push(next);
      }
    }
  }
  // Fallback: cycles or disconnected nodes
  for (const n of snap.nodes) if (!depth.has(n.id)) depth.set(n.id, 0);

  // Group by depth
  const byDepth = new Map<number, string[]>();
  for (const [id, d] of depth) {
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d)!.push(id);
  }

  const COL_W = 280;
  const ROW_H = 140;
  const PAD = 40;
  let maxCols = 0;
  for (const [d, ids] of byDepth) {
    maxCols = Math.max(maxCols, ids.length);
    ids.forEach((id, idx) => {
      positions.set(id, {
        x: PAD + idx * COL_W,
        y: PAD + d * ROW_H,
      });
    });
  }

  return {
    positions,
    width: PAD * 2 + maxCols * COL_W,
    height: PAD * 2 + (byDepth.size || 1) * ROW_H,
  };
}

export function DagFlow() {
  const { t } = useI18n();
  const dag = useRunStreamStore((s) => s.dag);
  const highlight = useRunStreamStore((s) => s.highlightNodeIds);
  const stepByNode = useRunStreamStore((s) => s.stepByNodeId);
  const [openNode, setOpenNode] = useState<DagNode | null>(null);
  const finalLabel = t('dag.final');

  const { nodes, edges } = useMemo(() => {
    if (!dag) return { nodes: [] as Node<DagNodeData>[], edges: [] as Edge[] };
    const layout = layoutDag(dag);
    const ns: Node<DagNodeData>[] = dag.nodes.map((n) => {
      const pos = layout.positions.get(n.id) ?? { x: 0, y: 0 };
      return {
        id: n.id,
        type: 'dag',
        position: pos,
        data: {
          node: n,
          highlight: highlight.has(n.id),
          isFinal: dag.final_node_id === n.id,
          finalLabel,
        },
      };
    });
    const es: Edge[] = dag.edges.map((e, idx) => {
      const targetNode = dag.nodes.find((n) => n.id === e.to);
      const sourceNode = dag.nodes.find((n) => n.id === e.from);
      const isTargetRunning = targetNode?.status === 'in_progress';
      const isSourceDone = sourceNode?.status === 'done';
      const isActivePath = isTargetRunning && isSourceDone;
      return {
        id: `${e.from}->${e.to}-${idx}`,
        source: e.from,
        target: e.to,
        animated: isTargetRunning,
        style: {
          stroke: isActivePath
            ? 'var(--color-status-running)'
            : targetNode?.status === 'done'
              ? 'var(--color-status-done)'
              : 'var(--color-border-strong)',
          strokeWidth: isActivePath ? 2.2 : 1.4,
          transition: 'stroke 0.4s ease, stroke-width 0.3s ease',
        },
      };
    });
    return { nodes: ns, edges: es };
  }, [dag, highlight, finalLabel]);

  // Refresh openNode reference when DAG updates
  useEffect(() => {
    if (!openNode || !dag) return;
    const fresh = dag.nodes.find((n) => n.id === openNode.id);
    if (fresh && fresh !== openNode) setOpenNode(fresh);
  }, [dag, openNode]);

  if (!dag || dag.nodes.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center h-full gap-3 text-sm text-[color:var(--color-fg-muted)]"
        style={{ background: 'var(--color-bg-raised)' }}
      >
        <span className="status-dot status-running pulse-running" style={{ width: 12, height: 12 }} />
        {t('dag.empty')}
      </div>
    );
  }

  return (
    <div className="h-full w-full" style={{ background: 'var(--color-bg-raised)' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, node) => {
          const dagNode = (node.data as DagNodeData).node;
          setOpenNode(dagNode);
        }}
        defaultEdgeOptions={{ style: { stroke: 'var(--color-border-strong)' } }}
      >
        <Background gap={20} size={1} color="var(--color-border-subtle)" />
        <Controls
          style={{
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 8,
          }}
        />
      </ReactFlow>

      <Drawer
        open={!!openNode}
        onClose={() => setOpenNode(null)}
        title={openNode ? `${t('dag.node')} · ${openNode.id}` : t('dag.node')}
        width={520}
      >
        {openNode && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <NodeStatusBadge status={openNode.status} />
              {dag.final_node_id === openNode.id && (
                <span className="chip">{t('dag.final')}</span>
              )}
            </div>
            <section>
              <div className="label">{t('dag.goal')}</div>
              <div className="surface p-3 text-sm whitespace-pre-wrap leading-relaxed">
                {openNode.goal}
              </div>
            </section>
            {openNode.expected_output && (
              <section>
                <div className="label">{t('dag.expectedOutput')}</div>
                <div className="surface p-3 text-sm">{openNode.expected_output}</div>
              </section>
            )}
            {openNode.suggested_tools.length > 0 && (
              <section>
                <div className="label">{t('dag.suggestedTools')}</div>
                <div className="flex gap-1 flex-wrap">
                  {openNode.suggested_tools.map((tool) => (
                    <span key={tool} className="chip font-mono">{tool}</span>
                  ))}
                </div>
              </section>
            )}
            {openNode.depends_on.length > 0 && (
              <section>
                <div className="label">{t('dag.dependsOn')}</div>
                <div className="flex gap-1 flex-wrap">
                  {openNode.depends_on.map((d) => (
                    <span key={d} className="chip font-mono">{d}</span>
                  ))}
                </div>
              </section>
            )}
            {openNode.output_summary && (
              <section>
                <div className="label">{t('dag.outputSummary')}</div>
                <div className="surface p-3 text-sm whitespace-pre-wrap">
                  {openNode.output_summary}
                </div>
              </section>
            )}
            {(() => {
              const step = stepByNode.get(openNode.id);
              if (!step) return null;
              return (
                <section>
                  <div className="label">{t('dag.latestStep')}</div>
                  <div className="surface p-3 font-mono text-xs space-y-2 max-h-72 overflow-auto">
                    {step.thought && (
                      <div>
                        <div className="text-[color:var(--color-fg-faint)] mb-0.5">{t('dag.thought')}</div>
                        <div className="whitespace-pre-wrap">{step.thought}</div>
                      </div>
                    )}
                    {step.action && (
                      <div>
                        <div className="text-[color:var(--color-fg-faint)] mb-0.5">{t('dag.action')}</div>
                        <div>{step.action}</div>
                      </div>
                    )}
                    {step.action_input != null && (
                      <div>
                        <div className="text-[color:var(--color-fg-faint)] mb-0.5">{t('dag.actionInput')}</div>
                        <pre className="whitespace-pre-wrap break-all">{JSON.stringify(step.action_input, null, 2)}</pre>
                      </div>
                    )}
                    {step.observation != null && (
                      <div>
                        <div className="text-[color:var(--color-fg-faint)] mb-0.5">{t('dag.observation')}</div>
                        <pre className="whitespace-pre-wrap break-all">{JSON.stringify(step.observation, null, 2)}</pre>
                      </div>
                    )}
                  </div>
                </section>
              );
            })()}
          </div>
        )}
      </Drawer>
    </div>
  );
}
