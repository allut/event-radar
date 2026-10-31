import { useEffect, useRef, useState } from 'react';
import { adminStream, StreamDisconnectedError, type NdjsonLine } from '../api/client';
import { ADMIN_GENERIC_ERROR } from '../constants/admin';
import { apiErrorMessage } from '../utils/apiErrors';

export type RunState = 'idle' | 'starting' | 'streaming' | 'done' | 'disconnected';

// Drives one trigger's run: streams NDJSON lines and tracks a UI state that
// distinguishes cold-start ("starting…", shown until the first line arrives
// regardless of why — Render free-tier spin-up or ordinary first-stage
// latency look the same to the client) from an in-flight run, a clean
// finish, and a mid-stream disconnect (issue #159).
export function useTriggerRun(): { state: RunState; lines: NdjsonLine[]; run: (path: string) => void } {
  const [state, setState] = useState<RunState>('idle');
  const [lines, setLines] = useState<NdjsonLine[]>([]);
  const abortRef = useRef<AbortController | null>(null);

  function run(path: string) {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLines([]);
    setState('starting');

    adminStream(
      path,
      (line) => {
        setState('streaming');
        setLines((prev) => [...prev, line]);
      },
      controller.signal,
    )
      .then(() => setState('done'))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof StreamDisconnectedError) {
          setState('disconnected');
          return;
        }
        // The request never even started streaming (network error, or a
        // non-2xx before any body arrived) — surface it the same generic
        // way a streamed error line would have.
        const message = apiErrorMessage(err, ADMIN_GENERIC_ERROR);
        setLines((prev) => (prev.length ? prev : [{ stage: path, status: 'error', result: null, error: message }]));
        setState('done');
      });
  }

  useEffect(() => () => abortRef.current?.abort(), []);
  return { state, lines, run };
}
