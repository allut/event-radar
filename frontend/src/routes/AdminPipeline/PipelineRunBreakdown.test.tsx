import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import PipelineRunBreakdown from './PipelineRunBreakdown';
import type { NdjsonLine } from '../../api/client';

const STAGES = ['sync_organizers', 'ingest', 'dedup', 'classify', 'publish', 'build_feeds', 'send_digests'];

// Representative multi-stage result: three ok stages (a flat-dict shape and
// ingest's list-of-per-source shape), one failure, and the stages after it
// never ran — matches _run_pipeline_stages' stop-at-first-failure contract
// (backend/app/routers/admin.py).
const PARTIAL_RUN: NdjsonLine[] = [
  { stage: 'sync_organizers', status: 'ok', result: { checked: 42, added: 2, retired: 0 }, error: null },
  {
    stage: 'ingest', status: 'ok',
    result: [{ slug: 'fienta', raw_count: 18, new_count: 6 }, { slug: 'piletilevi', raw_count: 9, new_count: 1 }],
    error: null,
  },
  { stage: 'dedup', status: 'ok', result: { candidate_pairs: 120, groups: 15, passes: 1 }, error: null },
  { stage: 'classify', status: 'error', result: null, error: 'classify failed; see server logs' },
];

describe('PipelineRunBreakdown', () => {
  it('renders every configured stage, even ones that never ran', () => {
    render(<PipelineRunBreakdown stages={STAGES} lines={PARTIAL_RUN} />);
    for (const label of ['Sync organizers', 'Ingest', 'Dedup', 'Classify', 'Publish', 'Build feeds', 'Send digests']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('renders an ok dict-shaped stage as legible key=value text, not raw JSON', () => {
    render(<PipelineRunBreakdown stages={STAGES} lines={PARTIAL_RUN} />);
    const row = screen.getByText('Sync organizers').closest('tr')!;
    expect(within(row).getByText(/checked=42/)).toBeInTheDocument();
    expect(within(row).getByText(/added=2/)).toBeInTheDocument();
    expect(within(row).queryByText(/[{}]/)).not.toBeInTheDocument();
  });

  it('renders an ok list-shaped stage (ingest) per-source', () => {
    render(<PipelineRunBreakdown stages={STAGES} lines={PARTIAL_RUN} />);
    const row = screen.getByText('Ingest').closest('tr')!;
    expect(within(row).getByText(/fienta.*raw_count=18/)).toBeInTheDocument();
    expect(within(row).getByText(/piletilevi.*new_count=1/)).toBeInTheDocument();
  });

  it('surfaces a failed stage\'s generic error message', () => {
    render(<PipelineRunBreakdown stages={STAGES} lines={PARTIAL_RUN} />);
    const row = screen.getByText('Classify').closest('tr')!;
    expect(within(row).getByText('classify failed; see server logs')).toBeInTheDocument();
  });

  it('marks stages after the failure as not run, distinct from stages still pending', () => {
    render(<PipelineRunBreakdown stages={STAGES} lines={PARTIAL_RUN} />);
    const publishRow = screen.getByText('Publish').closest('tr')!;
    expect(within(publishRow).getByText('not run — earlier stage failed')).toBeInTheDocument();
    expect(publishRow).toHaveAttribute('data-status', 'skipped');
  });

  it('surfaces a connection-level failure (synthesized by useTriggerRun before any stage streams) instead of dropping it', () => {
    // Matches the synthetic line AdminPipeline.tsx's useTriggerRun builds on
    // a pre-stream failure: stage is the request path, not a real stage name.
    const preStreamFailure: NdjsonLine[] = [
      { stage: '/admin/pipeline/run?dry_run=true', status: 'error', result: null, error: 'Something went wrong.' },
    ];
    render(<PipelineRunBreakdown stages={STAGES} lines={preStreamFailure} />);
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong.');
    // Every stage row still renders as pending — none of them ran.
    expect(screen.getByText('Sync organizers').closest('tr')).toHaveAttribute('data-status', 'pending');
  });

  it('marks a stage with no line yet (still running, no failure ahead) as pending', () => {
    const inProgress = PARTIAL_RUN.slice(0, 2); // only sync_organizers + ingest have arrived
    render(<PipelineRunBreakdown stages={STAGES} lines={inProgress} />);
    const dedupRow = screen.getByText('Dedup').closest('tr')!;
    expect(dedupRow).toHaveAttribute('data-status', 'pending');
    expect(within(dedupRow).getByText('—')).toBeInTheDocument();
  });
});
