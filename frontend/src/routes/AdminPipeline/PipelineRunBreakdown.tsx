import type { NdjsonLine } from '../../api/client';
import { ADMIN_PIPELINE_STAGE_LABELS } from '../../constants';
import styles from './PipelineRunBreakdown.module.css';

// Bespoke stage-by-stage breakdown for pipeline_run's result (issue #161).
// Renders one row per stage in `stages` order (trigger.stages —
// constants.ts) regardless of how many lines have arrived yet, so a run in
// progress (or one that stopped early on a failure) shows the full seven-
// stage shape instead of only what's streamed so far.

function formatValue(v: unknown): string {
  if (v === null) return 'null';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  return String(v);
}

function formatEntries(obj: Record<string, unknown>, skip?: string): string {
  return Object.entries(obj)
    .filter(([k]) => k !== skip)
    .map(([k, v]) => `${k}=${formatValue(v)}`)
    .join('  ');
}

// Stage results aren't a single fixed shape: most stages return a flat
// dict of counts, but `ingest` returns a list of per-source dicts (see
// ingest_all_enabled, app/ingestion/jobs.py). Both render as compact
// k=v text rather than requiring per-stage-specific components.
function formatDetail(result: unknown): string {
  if (Array.isArray(result)) {
    if (result.length === 0) return '(no sources)';
    return result
      .map((item) => {
        if (item && typeof item === 'object') {
          const obj = item as Record<string, unknown>;
          const label = typeof obj.slug === 'string' ? obj.slug : null;
          const rest = formatEntries(obj, label ? 'slug' : undefined);
          return label ? `${label}: ${rest}` : rest;
        }
        return formatValue(item);
      })
      .join('  ·  ');
  }
  if (result && typeof result === 'object') {
    return formatEntries(result as Record<string, unknown>);
  }
  return formatValue(result);
}

export default function PipelineRunBreakdown({
  stages,
  lines,
}: {
  stages: string[];
  lines: NdjsonLine[];
}) {
  const byStage = new Map(lines.map((l) => [l.stage, l]));
  const failedIndex = stages.findIndex((s) => byStage.get(s)?.status === 'error');
  // A line whose `stage` doesn't match any real stage name is a
  // connection-level failure synthesized by useTriggerRun's catch (see
  // AdminPipeline.tsx) — e.g. a 429 from the shared admin rate limiter, or
  // any non-2xx before the stream body even starts. It can't be placed in a
  // stage row, so it's surfaced on its own rather than silently dropped.
  const preStreamErrors = lines.filter((l) => !stages.includes(l.stage));

  return (
    <>
      {preStreamErrors.map((l) => (
        <div key={l.stage} className={styles.preStreamError} role="alert">
          <span aria-hidden="true">✕</span> {l.error}
        </div>
      ))}
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Stage</th>
            <th>Status</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {stages.map((stage, i) => {
            const line = byStage.get(stage);
            const skipped = failedIndex !== -1 && i > failedIndex && !line;
            return (
              <tr key={stage} data-status={line?.status ?? (skipped ? 'skipped' : 'pending')}>
                <td className={styles.stage}>{ADMIN_PIPELINE_STAGE_LABELS[stage] ?? stage}</td>
                <td>
                  {line?.status === 'ok' && <span className={styles.iconOk} aria-hidden="true">✓</span>}
                  {line?.status === 'error' && <span className={styles.iconError} aria-hidden="true">✕</span>}
                  {!line && <span className={styles.iconPending} aria-hidden="true">·</span>}
                </td>
                <td className={styles.detail}>
                  {line?.status === 'error' && <span className={styles.errorText}>{line.error}</span>}
                  {line?.status === 'ok' && formatDetail(line.result)}
                  {!line && skipped && <span className={styles.pendingText}>not run — earlier stage failed</span>}
                  {!line && !skipped && <span className={styles.pendingText}>—</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}
