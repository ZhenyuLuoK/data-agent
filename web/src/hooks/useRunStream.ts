import { useEffect, useRef } from 'react';
import { useRunStreamStore, isTerminal } from '@/state/runStreamStore';
import { toast } from '@/state/toastStore';
import { makeTranslator, detectInitialLocale } from '@/i18n/locales';
import type { WSEvent } from '@/api/types';

const MAX_RECONNECTS = 5;
const BASE_BACKOFF_MS = 800;

/**
 * Subscribes to /api/runs/{runId}/stream.
 *
 * - Replays from `lastSeq + 1` on reconnect (snapshot has seq=0 and is excluded).
 * - If the next observed seq has a gap > 1, ring-buffer overflow happened on the
 *   server; we close and re-open from scratch to trigger a fresh snapshot.
 * - Stops reconnecting after the run reaches a terminal state OR close code 1000.
 */
export function useRunStream(runId: string | null) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectsRef = useRef(0);
  const stoppedRef = useRef(false);

  useEffect(() => {
    if (!runId) return;
    stoppedRef.current = false;
    reconnectsRef.current = 0;
    useRunStreamStore.getState().reset(runId);

    let cancelled = false;
    // Hook is used outside React context for toasts; resolve locale from storage
    const t = makeTranslator(detectInitialLocale());

    const connect = () => {
      if (cancelled || stoppedRef.current) return;
      const store = useRunStreamStore.getState();
      const wsScheme = location.protocol === 'https:' ? 'wss' : 'ws';
      const fromSeq = store.lastSeq;
      // Per backend contract: pass lastSeq + 1 to avoid replaying the last event.
      // snapshot has seq=0 so on first connect we send no `from_seq`.
      const fromSeqParam = fromSeq > 0 ? `?from_seq=${fromSeq + 1}` : '';
      const url = `${wsScheme}://${location.host}/api/runs/${encodeURIComponent(
        runId,
      )}/stream${fromSeqParam}`;

      store.setConnection(reconnectsRef.current === 0 ? 'connecting' : 'reconnecting');

      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectsRef.current = 0;
        useRunStreamStore.getState().setConnection('open');
      };

      ws.onmessage = (msgEvent) => {
        let event: WSEvent;
        try {
          event = JSON.parse(msgEvent.data) as WSEvent;
        } catch (err) {
          console.error('Bad WS payload', err);
          return;
        }
        const s = useRunStreamStore.getState();

        // Ring-buffer gap detection: if we expected seq=lastSeq+1 but got more,
        // we missed events — server's ring buffer dropped them. Force a re-snapshot.
        if (
          event.type !== 'snapshot' &&
          s.lastSeq > 0 &&
          event.seq > s.lastSeq + 1
        ) {
          toast.warning(t('wsBufferDrop.title'), t('wsBufferDrop.desc'));
          stoppedRef.current = false; // force reconnect path
          s.reset(runId);
          ws.close(4000, 'gap-detected');
          return;
        }

        switch (event.type) {
          case 'snapshot':
            s.applySnapshot(event);
            break;
          case 'log':
            s.applyLogChunk(event);
            break;
          case 'step':
            s.applyStep(event);
            break;
          case 'dag_update':
            s.applyDagUpdate(event);
            break;
          case 'final':
            s.applyFinal(event);
            stoppedRef.current = true; // server will follow with close(1000)
            break;
          case 'error':
            s.applyError(event);
            toast.danger(`${t('wsError.title')} · ${event.code}`, event.message);
            break;
        }
      };

      ws.onerror = () => {
        useRunStreamStore.getState().setConnection('error');
      };

      ws.onclose = (closeEvent) => {
        wsRef.current = null;
        const s = useRunStreamStore.getState();
        s.setConnection('closed');

        if (cancelled) return;
        if (closeEvent.code === 1000 || isTerminal(s.status)) {
          stoppedRef.current = true;
          return;
        }
        if (closeEvent.code === 4404) {
          toast.danger(t('wsRunNotFound'), t('wsRunNotFoundDesc', { runId }));
          stoppedRef.current = true;
          return;
        }
        if (stoppedRef.current === false && reconnectsRef.current < MAX_RECONNECTS) {
          const attempt = ++reconnectsRef.current;
          const delay = BASE_BACKOFF_MS * 2 ** (attempt - 1);
          window.setTimeout(connect, delay);
        } else if (reconnectsRef.current >= MAX_RECONNECTS) {
          toast.danger(t('wsMaxReconnect'), t('wsMaxReconnectDesc'));
        }
      };
    };

    connect();

    return () => {
      cancelled = true;
      stoppedRef.current = true;
      const ws = wsRef.current;
      if (ws && ws.readyState <= WebSocket.OPEN) {
        ws.close(1000, 'client-unmount');
      }
      wsRef.current = null;
    };
  }, [runId]);
}
