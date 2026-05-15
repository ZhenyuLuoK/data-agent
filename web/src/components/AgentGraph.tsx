import { useMemo } from 'react';
import { useRunStreamStore } from '@/state/runStreamStore';
import { useI18n } from '@/i18n/I18nProvider';

/**
 * LangGraph topology: fixed node layout showing the agent's internal
 * graph (planner → scheduler → executor → tools → reflector, etc.)
 * with dynamic glowing halo animations on the currently active node
 * and animated gradient arrows between connected nodes.
 * Nodes use pure text labels (no emoji) with pulsing light halos.
 */

/* ---- Static graph definition (mirrors _build_graph in langgraph_agent.py) ---- */

interface GraphNode {
  id: string;
  labelKey: string;
  /** Halo colour (oklch) for when the node is active. */
  haloColor: string;
  /** Position in the SVG canvas (hand-tuned for the fixed topology). */
  cx: number;
  cy: number;
}

interface GraphEdge {
  from: string;
  to: string;
  /** If true, this is a conditional edge (dashed). */
  conditional?: boolean;
}

const NODES: GraphNode[] = [
  { id: 'planner',      labelKey: 'agentGraph.planner',     haloColor: 'oklch(72% 0.18 270)', cx: 300, cy: 40  },
  { id: 'scheduler',    labelKey: 'agentGraph.scheduler',   haloColor: 'oklch(68% 0.16 290)', cx: 300, cy: 130 },
  { id: 'executor',     labelKey: 'agentGraph.executor',    haloColor: 'oklch(72% 0.14 240)', cx: 180, cy: 230 },
  { id: 'reasoning',    labelKey: 'agentGraph.reasoning',   haloColor: 'oklch(74% 0.16 200)', cx: 180, cy: 320 },
  { id: 'tools',        labelKey: 'agentGraph.tools',       haloColor: 'oklch(70% 0.14 150)', cx: 180, cy: 410 },
  { id: 'nudge',        labelKey: 'agentGraph.nudge',       haloColor: 'oklch(74% 0.12 80)',  cx: 60,  cy: 270 },
  { id: 'node_failure', labelKey: 'agentGraph.nodeFailure', haloColor: 'oklch(62% 0.20 25)',  cx: 420, cy: 270 },
  { id: 'reflector',    labelKey: 'agentGraph.reflector',   haloColor: 'oklch(68% 0.18 320)', cx: 420, cy: 370 },
  { id: 'replanner',    labelKey: 'agentGraph.replanner',   haloColor: 'oklch(70% 0.16 60)',  cx: 500, cy: 130 },
  { id: 'finalize',     labelKey: 'agentGraph.finalize',    haloColor: 'oklch(72% 0.14 150)', cx: 300, cy: 500 },
];

const EDGES: GraphEdge[] = [
  { from: 'planner',      to: 'scheduler',    conditional: true },
  { from: 'scheduler',    to: 'executor',     conditional: true },
  { from: 'scheduler',    to: 'reflector',    conditional: true },
  { from: 'scheduler',    to: 'replanner',    conditional: true },
  { from: 'scheduler',    to: 'finalize',     conditional: true },
  { from: 'executor',     to: 'reasoning',    conditional: true },
  { from: 'executor',     to: 'nudge',        conditional: true },
  { from: 'executor',     to: 'node_failure', conditional: true },
  { from: 'executor',     to: 'finalize',     conditional: true },
  { from: 'reasoning',    to: 'tools' },
  { from: 'nudge',        to: 'executor' },
  { from: 'tools',        to: 'executor',     conditional: true },
  { from: 'tools',        to: 'scheduler',    conditional: true },
  { from: 'tools',        to: 'reflector',    conditional: true },
  { from: 'tools',        to: 'node_failure', conditional: true },
  { from: 'node_failure', to: 'scheduler',    conditional: true },
  { from: 'node_failure', to: 'finalize',     conditional: true },
  { from: 'replanner',    to: 'scheduler',    conditional: true },
  { from: 'reflector',    to: 'scheduler',    conditional: true },
  { from: 'reflector',    to: 'finalize',     conditional: true },
];

/* ---- Infer active node from steps stream ---- */

/** Map a single step to its corresponding graph node id. */
function mapStepToGraphNode(
  step: { action?: string | null; action_input?: unknown },
): string | null {
  const action = step.action;
  if (!action) return null;
  const input = step.action_input as Record<string, unknown> | undefined;
  const graphNode = typeof input?.graph_node === 'string' ? input.graph_node : null;
  if (action === '__graph_node__' && graphNode) return graphNode;
  if (action === '__plan__') return 'planner';
  if (action === '__replan__') return 'replanner';
  if (action === '__dag_node_start__' || action === 'start_node') return 'scheduler';
  if (action === '__dag_node_done__' || action === 'mark_node_done') return 'scheduler';
  if (action === '__reflect__') return 'reflector';
  if (action === '__node_attempt_failed__' || action === 'mark_node_failed') return 'node_failure';
  if (action === '__assistant_text__') return 'executor';
  // Any non-synthetic action (concrete tool call) → "tools" node
  if (!action.startsWith('__')) return 'tools';
  return null;
}

/** Check whether a step represents a "tools is active" signal. */
function isToolsSignal(step: { action?: string | null; action_input?: unknown }): boolean {
  const action = step.action;
  if (!action) return false;
  // Concrete tool call (read_doc, execute_python, etc.)
  if (!action.startsWith('__')) return true;
  // Explicit __graph_node__ tools marker
  const input = step.action_input as Record<string, unknown> | undefined;
  return action === '__graph_node__' && input?.graph_node === 'tools';
}

/**
 * Infer the currently active graph node from the steps stream.
 *
 * Strategy: walk backwards from the most recent step. The first
 * recognizable action determines the active node.
 *
 * Special handling for "executor" markers: when the last recognized node
 * is __graph_node__="executor", we look at the step(s) immediately before
 * it. If any of them represent a "tools is active" signal (either a
 * concrete tool call OR a __graph_node__="tools" marker), we override
 * to "tools" — the executor marker is written at the START of the next
 * executor turn and races with tool IO. Without this heuristic, fast
 * tools would cause "tools" to never visually activate because the
 * TraceWatcher 0.25s poll picks up the already-overwritten state.
 */
function inferActiveGraphNode(
  steps: { action?: string | null; action_input?: unknown }[],
): string | null {
  if (steps.length === 0) return null;

  for (let i = steps.length - 1; i >= 0; i--) {
    const result = mapStepToGraphNode(steps[i]);
    if (result === null) continue;

    if (result === 'executor') {
      const step = steps[i];
      const action = step.action;
      const input = step.action_input as Record<string, unknown> | undefined;
      const isExecutorMarker =
        action === '__graph_node__' &&
        typeof input?.graph_node === 'string' &&
        input.graph_node === 'executor';
      if (isExecutorMarker && i > 0) {
        // Look at the previous step(s) — up to 3 back to handle
        // interleaved graph_node markers (tools/reasoning/tool-action).
        const lookback = Math.max(0, i - 3);
        for (let j = i - 1; j >= lookback; j--) {
          if (isToolsSignal(steps[j])) return 'tools';
        }
      }
    }
    return result;
  }
  return null;
}

/* ---- Component ---- */

const SVG_WIDTH = 580;
const SVG_HEIGHT = 560;
const NODE_RADIUS = 28;

export function AgentGraph() {
  const { t } = useI18n();
  const steps = useRunStreamStore((s) => s.steps);
  const status = useRunStreamStore((s) => s.status);

  const isRunning = status === 'running' || status === 'queued';
  const activeNodeId = useMemo(
    () => inferActiveGraphNode(steps),
    [steps],
  );

  // Track visited nodes for trail effect
  const visitedNodeIds = useMemo(() => {
    const visited = new Set<string>();
    for (const step of steps) {
      const mapped = inferActiveGraphNode([step]);
      if (mapped) visited.add(mapped);
    }
    return visited;
  }, [steps]);

  const nodeIndex = useMemo(
    () => new Map(NODES.map((n) => [n.id, n])),
    [],
  );

  if (!isRunning && steps.length === 0) {
    return (
      <div
        className="flex flex-col items-center justify-center h-full gap-3 text-sm text-[color:var(--color-fg-muted)]"
        style={{ background: 'var(--color-bg-raised)' }}
      >
        <span className="status-dot status-running pulse-running" style={{ width: 12, height: 12 }} />
        {t('agentGraph.empty')}
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-auto" style={{ background: 'var(--color-bg-raised)' }}>
      <svg
        viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
        className="w-full h-full"
        style={{ minHeight: 400 }}
      >
        <defs>
          {/* Per-node glow filters — each uses the node's haloColor */}
          {NODES.map((node) => (
            <filter key={`glow-${node.id}`} id={`glow-${node.id}`} x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur in="SourceGraphic" stdDeviation="8" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          ))}
          {/* Arrow markers */}
          <marker id="agent-graph-arrow" viewBox="0 0 10 10" refX="8" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse"
            fill="var(--color-border-strong)">
            <path d="M 0 0 L 10 5 L 0 10 z" />
          </marker>
          <marker id="agent-graph-arrow-active" viewBox="0 0 10 10" refX="8" refY="5"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse"
            fill="var(--color-status-running)">
            <path d="M 0 0 L 10 5 L 0 10 z" />
          </marker>
        </defs>

        {/* Edges */}
        {EDGES.map((edge, index) => {
          const fromNode = nodeIndex.get(edge.from);
          const toNode = nodeIndex.get(edge.to);
          if (!fromNode || !toNode) return null;

          const isActiveEdge = activeNodeId === edge.to && visitedNodeIds.has(edge.from);

          const dx = toNode.cx - fromNode.cx;
          const dy = toNode.cy - fromNode.cy;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist === 0) return null;
          const ux = dx / dist;
          const uy = dy / dist;

          const startX = fromNode.cx + ux * (NODE_RADIUS + 4);
          const startY = fromNode.cy + uy * (NODE_RADIUS + 4);
          const endX = toNode.cx - ux * (NODE_RADIUS + 4);
          const endY = toNode.cy - uy * (NODE_RADIUS + 4);

          return (
            <line
              key={index}
              x1={startX} y1={startY}
              x2={endX} y2={endY}
              stroke={isActiveEdge ? 'var(--color-status-running)' : 'var(--color-border)'}
              strokeWidth={isActiveEdge ? 2 : 1}
              strokeDasharray={edge.conditional ? '4 3' : undefined}
              markerEnd={isActiveEdge ? 'url(#agent-graph-arrow-active)' : 'url(#agent-graph-arrow)'}
              opacity={isActiveEdge ? 1 : 0.35}
              style={isActiveEdge ? { transition: 'all 0.5s ease' } : undefined}
            />
          );
        })}

        {/* Animated pulse traveller on active edge */}
        {activeNodeId && (() => {
          const activeEdge = EDGES.find(
            (e) => e.to === activeNodeId && visitedNodeIds.has(e.from),
          );
          if (!activeEdge) return null;
          const fromNode = nodeIndex.get(activeEdge.from);
          const toNode = nodeIndex.get(activeEdge.to);
          if (!fromNode || !toNode) return null;

          const dx = toNode.cx - fromNode.cx;
          const dy = toNode.cy - fromNode.cy;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist === 0) return null;
          const ux = dx / dist;
          const uy = dy / dist;
          const startX = fromNode.cx + ux * (NODE_RADIUS + 4);
          const startY = fromNode.cy + uy * (NODE_RADIUS + 4);
          const endX = toNode.cx - ux * (NODE_RADIUS + 4);
          const endY = toNode.cy - uy * (NODE_RADIUS + 4);

          return (
            <circle r="3.5" fill="var(--color-status-running)" opacity="0.85">
              <animateMotion
                dur="1.2s"
                repeatCount="indefinite"
                path={`M${startX},${startY} L${endX},${endY}`}
              />
            </circle>
          );
        })()}

        {/* Nodes — circles with dynamic glowing halos + text labels */}
        {NODES.map((node) => {
          const isActive = node.id === activeNodeId;
          const isVisited = visitedNodeIds.has(node.id);
          const label = t(node.labelKey as any);

          return (
            <g key={node.id} filter={isActive ? `url(#glow-${node.id})` : undefined}>
              {/* Expanding pulse ring — radiating outward when active */}
              {isActive && (
                <>
                  <circle
                    cx={node.cx} cy={node.cy} r={NODE_RADIUS}
                    fill="none" stroke={node.haloColor} strokeWidth="2" opacity="0"
                  >
                    <animate attributeName="r" from={NODE_RADIUS} to={NODE_RADIUS + 22} dur="1.8s" repeatCount="indefinite" />
                    <animate attributeName="opacity" from="0.7" to="0" dur="1.8s" repeatCount="indefinite" />
                  </circle>
                  {/* Second ring staggered for continuous wave effect */}
                  <circle
                    cx={node.cx} cy={node.cy} r={NODE_RADIUS}
                    fill="none" stroke={node.haloColor} strokeWidth="1.5" opacity="0"
                  >
                    <animate attributeName="r" from={NODE_RADIUS} to={NODE_RADIUS + 22} dur="1.8s" begin="0.9s" repeatCount="indefinite" />
                    <animate attributeName="opacity" from="0.5" to="0" dur="1.8s" begin="0.9s" repeatCount="indefinite" />
                  </circle>
                </>
              )}

              {/* Ambient glow behind circle (soft halo) */}
              {isActive && (
                <circle
                  cx={node.cx} cy={node.cy} r={NODE_RADIUS + 6}
                  fill={node.haloColor} opacity="0.15"
                >
                  <animate attributeName="opacity" values="0.10;0.25;0.10" dur="2s" repeatCount="indefinite" />
                </circle>
              )}

              {/* Main circle body */}
              <circle
                cx={node.cx} cy={node.cy} r={NODE_RADIUS}
                fill={
                  isActive
                    ? `color-mix(in oklch, var(--color-surface) 50%, ${node.haloColor} 50%)`
                    : isVisited
                      ? 'color-mix(in oklch, var(--color-surface) 70%, var(--color-status-done) 30%)'
                      : 'var(--color-surface)'
                }
                stroke={
                  isActive
                    ? node.haloColor
                    : isVisited
                      ? 'var(--color-status-done)'
                      : 'var(--color-border)'
                }
                strokeWidth={isActive ? 2.5 : 1.5}
                style={{ transition: 'all 0.4s ease' }}
              />

              {/* Text label — centred inside the circle */}
              <text
                x={node.cx} y={node.cy + 1}
                textAnchor="middle" dominantBaseline="central"
                fontSize="9.5"
                fontFamily="var(--font-sans)"
                fontWeight={isActive ? 700 : isVisited ? 500 : 400}
                fill={isActive ? '#fff' : isVisited ? 'var(--color-fg)' : 'var(--color-fg-muted)'}
                style={{ transition: 'fill 0.3s ease', pointerEvents: 'none' }}
              >
                {label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
