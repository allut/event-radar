import { useEffect, useRef, useState } from 'react';
import { adminStream, ApiError, StreamDisconnectedError, type NdjsonLine } from '../../api/client';
import { ADMIN_PIPELINE_TRIGGERS, API, type AdminPipelineTrigger } from '../../constants';
import ConfirmRunModal from './ConfirmRunModal';
import PipelineRunBreakdown from './PipelineRunBreakdown';
import styles from './AdminPipeline.module.css';

type RunState = 'idle' | 'starting' | 'streaming' | 'done' | 'disconnected';

// Resolves a trigger + its current form state to the endpoint to stream from.
// Returns null when the trigger can't run yet (ingest_source with no slug).
function triggerPath(trigger: AdminPipelineTrigger, dryRun: boolean, slug: string): string | null {
  switch (trigger.id) {
    case 'ingest_all': return API.adminIngestAll;
    case 'ingest_source': return slug.trim() ? API.adminIngestSource(slug.trim()) : null;
    case 'dedup': return API.adminDedupRun;
    case 'classify': return API.adminClassify;
    case 'publish': return API.adminPublish;
    case 'geocode': return API.adminGeocode;
    case 'refetch': return API.adminRefetch;
    case 'sync_organizers': return API.adminSyncOrganizers;
    case 'cleanup': return API.adminCleanup(dryRun);
    case 'build_feeds': return API.adminBuildFeeds;
    case 'send_digests': return API.adminSendDigests(dryRun);
    case 'pipeline_run': return API.adminPipelineRun(dryRun);
  }
}

// Drives one trigger's run: streams NDJSON lines and tracks a UI state that
// distinguishes cold-start ("starting…", shown until the first line arrives
// regardless of why — Render free-tier spin-up or ordinary first-stage
// latency look the same to the client) from an in-flight run, a clean
// finish, and a mid-stream disconnect (issue #159).
function useTriggerRun() {
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
        const message = err instanceof ApiError ? err.message : 'Something went wrong.';
        setLines((prev) => (prev.length ? prev : [{ stage: path, status: 'error', result: null, error: message }]));
        setState('done');
      });
  }

  useEffect(() => () => abortRef.current?.abort(), []);
  return { state, lines, run };
}

// The generic pretty-printed result viewer (issue #159) — every trigger
// except pipeline_run renders through this. pipeline_run gets the bespoke
// stage-by-stage breakdown (PipelineRunBreakdown, issue #161) instead.
function ResultViewer({ line }: { line: NdjsonLine }) {
  if (line.status === 'error') {
    return (
      <div className={styles.lineError} role="alert">
        <span aria-hidden="true">✕</span> {line.stage} — {line.error}
      </div>
    );
  }
  return (
    <div className={styles.lineOk}>
      <div className={styles.lineOkHead}><span aria-hidden="true">✓</span> {line.stage}</div>
      <pre className={styles.pre}>{JSON.stringify(line.result, null, 2)}</pre>
    </div>
  );
}

function StatusLabel({ state }: { state: RunState }) {
  if (state === 'idle') return null;
  if (state === 'starting') return <span className={styles.badgeStarting}>starting…</span>;
  if (state === 'streaming') return <span className={styles.badgeStreaming}>running…</span>;
  if (state === 'disconnected') {
    return <span className={styles.badgeDisconnected}>connection lost — job may still be running</span>;
  }
  return <span className={styles.badgeDone}>done</span>;
}

function TriggerCard({ trigger }: { trigger: AdminPipelineTrigger }) {
  const [dryRun, setDryRun] = useState(true);
  const [slug, setSlug] = useState('');
  const [opened, setOpened] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { state, lines, run } = useTriggerRun();

  const path = triggerPath(trigger, dryRun, slug);
  const busy = state === 'starting' || state === 'streaming';
  const guarded = Boolean(trigger.dangerCopy);
  // `lines` still holds the last completed run's data until the next run()
  // call resets it — carrying a completed dry run's numbers into the
  // confirmation modal (issue #160) needs no extra state.
  const dryRunLines = state === 'done' && lines.length > 0 ? lines : null;

  function startRealRun() {
    const realPath = triggerPath(trigger, false, slug);
    if (!realPath) return;
    setConfirmOpen(false);
    setOpened(true);
    // Flip the toggle off so a completed real run doesn't re-satisfy
    // `guarded && dryRun && state === 'done'` and resurrect "Run for real"
    // mislabeling this real run's own numbers as a dry run's.
    setDryRun(false);
    run(realPath);
  }

  function handleRun() {
    if (!path) return;
    if (guarded && !dryRun) {
      setConfirmOpen(true);
      return;
    }
    setOpened(true);
    run(path);
  }

  return (
    <div className={styles.card} data-testid={`trigger-card-${trigger.id}`}>
      <div className={styles.cardHead}>
        <div className={styles.rowTitle}>{trigger.label}</div>
        {opened && <StatusLabel state={state} />}
      </div>
      <div className={styles.rowMeta}>{trigger.hint}</div>
      {trigger.needsSlug && (
        <input
          className={styles.slugInput}
          placeholder="source slug"
          value={slug}
          onChange={(e) => setSlug(e.target.value)}
          disabled={busy}
        />
      )}
      <div className={styles.cardFoot}>
        <span>
          {trigger.dryRunCapable && (
            <label className={styles.dryRunToggle}>
              <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} disabled={busy} />
              Dry run
            </label>
          )}
        </span>
        <button
          className={styles.runButton}
          disabled={!path || busy}
          onClick={handleRun}
          aria-label={`Run ${trigger.label}`}
        >
          Run
        </button>
      </div>
      {guarded && dryRun && state === 'done' && (
        <button
          type="button"
          className={styles.runForRealButton}
          onClick={() => setConfirmOpen(true)}
          aria-label={`Run ${trigger.label} for real`}
        >
          Run for real
        </button>
      )}
      {opened && lines.length > 0 && trigger.id === 'pipeline_run' && trigger.stages && (
        <div className={styles.drawer}>
          <PipelineRunBreakdown stages={trigger.stages} lines={lines} />
        </div>
      )}
      {opened && lines.length > 0 && trigger.id !== 'pipeline_run' && (
        <div className={styles.drawer}>
          {lines.map((l) => <ResultViewer key={l.stage} line={l} />)}
        </div>
      )}
      {confirmOpen && (
        <ConfirmRunModal
          trigger={trigger}
          dryRunLines={dryRunLines}
          onCancel={() => setConfirmOpen(false)}
          onConfirm={startRealRun}
        />
      )}
    </div>
  );
}

export default function AdminPipeline() {
  return (
    <div>
      <div className={styles.head}>
        <p className={styles.eyebrow}>Admin / Ops</p>
        <h1 className={styles.title}>Pipeline</h1>
      </div>

      <div className={styles.desktopGate}>Come back at a desk — the pipeline console needs more room than this screen.</div>

      <div className={styles.grid}>
        {ADMIN_PIPELINE_TRIGGERS.map((t) => <TriggerCard key={t.id} trigger={t} />)}
      </div>
    </div>
  );
}
