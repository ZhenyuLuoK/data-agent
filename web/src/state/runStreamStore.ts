import { create } from 'zustand';
import type {
  DagSnapshot,
  LogLine,
  RunStatus,
  RunSummary,
  WSDagUpdate,
  WSError,
  WSFinal,
  WSLogChunk,
  WSSnapshot,
  WSStep,
} from '@/api/types';

const TERMINAL_STATUSES: RunStatus[] = [
  'succeeded',
  'failed',
  'cancelled',
  'timeout',
];

export const isTerminal = (status: RunStatus | undefined | null) =>
  !!status && TERMINAL_STATUSES.includes(status);

export type ConnectionState =
  | 'idle'
  | 'connecting'
  | 'open'
  | 'reconnecting'
  | 'closed'
  | 'error';

interface PendingChunkBuffer {
  total: number;
  chunks: WSLogChunk[];
  ts: string;
}

interface RunStreamStore {
  runId: string | null;
  run: RunSummary | null;
  status: RunStatus;
  logLines: LogLine[];
  pendingChunks: Map<number, PendingChunkBuffer>;
  dag: DagSnapshot | null;
  steps: WSStep[];
  /** Map node_id → most-recent step (for DAG node detail panel). */
  stepByNodeId: Map<string, WSStep>;
  highlightNodeIds: Set<string>;
  lastSeq: number;
  connection: ConnectionState;
  errors: WSError[];
  truncatedSnapshot: boolean;

  reset: (runId: string) => void;
  applySnapshot: (event: WSSnapshot) => void;
  applyLogChunk: (event: WSLogChunk) => void;
  applyStep: (event: WSStep) => void;
  applyDagUpdate: (event: WSDagUpdate) => void;
  applyFinal: (event: WSFinal) => void;
  applyError: (event: WSError) => void;
  setConnection: (state: ConnectionState) => void;
  clearHighlights: () => void;
  appendFullLog: (text: string) => void;
}

const SNAPSHOT_TRUNCATION_SENTINEL_PREFIX = '[snapshot truncated';

function getStepNodeId(step: WSStep): string | null {
  const inputAny = step.action_input as Record<string, unknown> | undefined;
  return typeof inputAny?.node_id === 'string' ? inputAny.node_id : null;
}

function buildStepByNodeId(steps: WSStep[]): Map<string, WSStep> {
  const stepByNodeId = new Map<string, WSStep>();
  for (const step of steps) {
    const nodeId = getStepNodeId(step);
    if (nodeId) stepByNodeId.set(nodeId, step);
  }
  return stepByNodeId;
}

function getStepSignature(step: WSStep): string {
  const nodeId = getStepNodeId(step) ?? '';
  return [step.step_index ?? '', step.action ?? '', nodeId].join('|');
}

export const useRunStreamStore = create<RunStreamStore>((set, get) => ({
  runId: null,
  run: null,
  status: 'queued',
  logLines: [],
  pendingChunks: new Map(),
  dag: null,
  steps: [],
  stepByNodeId: new Map(),
  highlightNodeIds: new Set(),
  lastSeq: 0,
  connection: 'idle',
  errors: [],
  truncatedSnapshot: false,

  reset: (runId) =>
    set({
      runId,
      run: null,
      status: 'queued',
      logLines: [],
      pendingChunks: new Map(),
      dag: null,
      steps: [],
      stepByNodeId: new Map(),
      highlightNodeIds: new Set(),
      lastSeq: 0,
      connection: 'connecting',
      errors: [],
      truncatedSnapshot: false,
    }),

  applySnapshot: (event) => {
    const lines: LogLine[] = event.log_tail.map((text, idx) => ({
      line_id: -event.log_tail.length + idx, // negative ids: synthetic snapshot tail
      ts: '',
      text,
    }));
    const truncated =
      event.log_tail.length > 0 &&
      event.log_tail[0].startsWith(SNAPSHOT_TRUNCATION_SENTINEL_PREFIX);

    const snapshotSteps = event.steps ?? [];
    set({
      run: event.run,
      status: event.run.status,
      dag: event.dag,
      steps: snapshotSteps,
      stepByNodeId: buildStepByNodeId(snapshotSteps),
      logLines: lines,
      pendingChunks: new Map(),
      // snapshot has seq=0 by contract; subsequent events start from server's last seq
      lastSeq: 0,
      truncatedSnapshot: truncated,
    });
  },

  applyLogChunk: (event) => {
    const state = get();
    if (event.seq <= state.lastSeq) return; // duplicate (e.g. due to reconnect race)

    let merged: LogLine | null = null;

    if (event.chunk_total === 1) {
      merged = { line_id: event.line_id, ts: event.ts, text: event.line };
    } else {
      const buf = state.pendingChunks.get(event.line_id) ?? {
        total: event.chunk_total,
        chunks: new Array<WSLogChunk>(event.chunk_total),
        ts: event.ts,
      };
      buf.chunks[event.chunk_index] = event;
      const filled = buf.chunks.filter(Boolean).length;
      if (filled === buf.total) {
        // Re-decode after concat: U+FFFD inserted by per-chunk utf-8 decoding can
        // remain at slice boundaries; that's an acceptable trade-off vs. doing
        // a second pass at the byte level (which we don't have here).
        const text = buf.chunks.map((c) => c.line).join('');
        merged = { line_id: event.line_id, ts: event.ts, text };
        state.pendingChunks.delete(event.line_id);
      } else {
        state.pendingChunks.set(event.line_id, buf);
      }
    }

    if (merged) {
      const alreadySeen = state.logLines.some((line) => line.text === merged.text);
      set({
        logLines: alreadySeen ? state.logLines : [...state.logLines, merged],
        lastSeq: event.seq,
      });
    } else {
      set({ lastSeq: event.seq });
    }
  },

  applyStep: (event) => {
    const state = get();
    if (event.seq <= state.lastSeq) return;
    const eventSignature = getStepSignature(event);
    const alreadySeen = state.steps.some(
      (step) => getStepSignature(step) === eventSignature,
    );
    if (alreadySeen) {
      set({ lastSeq: event.seq });
      return;
    }

    const nodeId = getStepNodeId(event);
    const nextStepByNode = new Map(state.stepByNodeId);
    if (nodeId) nextStepByNode.set(nodeId, event);
    set({
      steps: [...state.steps, event],
      stepByNodeId: nextStepByNode,
      lastSeq: event.seq,
    });
  },

  applyDagUpdate: (event) => {
    const state = get();
    if (event.seq <= state.lastSeq) return;
    set({
      dag: {
        nodes: event.nodes,
        edges: event.edges,
        final_node_id: event.final_node_id,
      },
      highlightNodeIds: new Set(event.updated_node_ids),
      lastSeq: event.seq,
    });
    window.setTimeout(() => get().clearHighlights(), 1100);
  },

  applyFinal: (event) => {
    const state = get();
    if (event.seq <= state.lastSeq) return;
    set({
      run: event.run,
      status: event.run.status,
      lastSeq: event.seq,
    });
  },

  applyError: (event) => {
    const state = get();
    if (event.seq <= state.lastSeq) return;
    set({
      errors: [...state.errors, event],
      lastSeq: event.seq,
    });
  },

  setConnection: (connection) => set({ connection }),

  clearHighlights: () => set({ highlightNodeIds: new Set() }),

  appendFullLog: (text) => {
    const lines = text.split(/\r?\n/).map((t, idx) => ({
      line_id: -1_000_000 - idx,
      ts: '',
      text: t,
    }));
    set({ logLines: lines, truncatedSnapshot: false });
  },
}));
