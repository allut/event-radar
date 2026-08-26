import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '../../test/utils';
import AdminPipeline from './AdminPipeline';
import { adminStream, type NdjsonLine } from '../../api/client';

vi.mock('../../api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/client')>();
  return { ...actual, adminStream: vi.fn() };
});

const mockAdminStream = vi.mocked(adminStream);

describe('AdminPipeline', () => {
  it('shows a starting state, then streams a line through the generic viewer', async () => {
    let resolveStream: () => void = () => {};
    let deliverLine: (line: NdjsonLine) => void = () => {};
    mockAdminStream.mockImplementation((_path, onLine) => {
      deliverLine = onLine;
      return new Promise((resolve) => { resolveStream = resolve; });
    });

    renderWithProviders(<AdminPipeline />);
    const card = screen.getByTestId('trigger-card-dedup');
    await userEvent.click(within(card).getByRole('button', { name: 'Run Dedup pass' }));

    expect(await within(card).findByText('starting…')).toBeInTheDocument();

    deliverLine({ stage: 'dedup', status: 'ok', result: { merged: 3 }, error: null });
    expect(await within(card).findByText(/dedup/)).toBeInTheDocument();
    expect(within(card).getByText(/"merged": 3/)).toBeInTheDocument();

    resolveStream();
    expect(await within(card).findByText('done')).toBeInTheDocument();
  });

  it('renders an error line without leaking internals, matching run_admin_job\'s generic failure', async () => {
    mockAdminStream.mockImplementation((_path, onLine) => {
      onLine({ stage: 'publish', status: 'error', result: null, error: 'Publish failed; see server logs' });
      return Promise.resolve();
    });

    renderWithProviders(<AdminPipeline />);
    const card = screen.getByTestId('trigger-card-publish');
    await userEvent.click(within(card).getByRole('button', { name: 'Run Publish' }));

    expect(await within(card).findByText(/Publish failed; see server logs/)).toBeInTheDocument();
  });

  it('shows a distinct disconnected message on a mid-stream connection drop', async () => {
    const { StreamDisconnectedError } = await import('../../api/client');
    mockAdminStream.mockImplementation((_path, onLine) => {
      onLine({ stage: 'geocode', status: 'ok', result: { geocoded: 1 }, error: null });
      return Promise.reject(new StreamDisconnectedError('network drop'));
    });

    renderWithProviders(<AdminPipeline />);
    const card = screen.getByTestId('trigger-card-geocode');
    await userEvent.click(within(card).getByRole('button', { name: 'Run Geocode' }));

    expect(await within(card).findByText('connection lost — job may still be running')).toBeInTheDocument();
    // Distinct from a plain failure: no error line rendered for a disconnect.
    expect(within(card).queryByRole('alert')).not.toBeInTheDocument();
  });

  it('defaults dry-run-capable triggers to on and reflects the toggle in the streamed path', async () => {
    mockAdminStream.mockResolvedValue(undefined);
    renderWithProviders(<AdminPipeline />);

    const card = screen.getByTestId('trigger-card-cleanup');
    const toggle = within(card).getByRole('checkbox') as HTMLInputElement;
    expect(toggle.checked).toBe(true);

    await userEvent.click(toggle);
    expect(toggle.checked).toBe(false);

    // cleanup is a guarded trigger (issue #160) — a real run requires typed
    // confirmation before adminStream is ever called.
    await userEvent.click(within(card).getByRole('button', { name: 'Run Cleanup' }));
    expect(mockAdminStream).not.toHaveBeenCalled();

    await userEvent.click(screen.getByRole('button', { name: 'I understand, continue' }));
    await userEvent.click(screen.getByRole('button', { name: 'Run for real' }));

    await waitFor(() => {
      expect(mockAdminStream).toHaveBeenCalledWith(
        expect.stringContaining('dry_run=false'),
        expect.any(Function),
        expect.anything(),
      );
    });
  });

  it('disables Run for ingest-one-source until a slug is entered', async () => {
    renderWithProviders(<AdminPipeline />);
    const card = screen.getByTestId('trigger-card-ingest_source');
    const runButton = within(card).getByRole('button', { name: 'Run Ingest one source' });
    expect(runButton).toBeDisabled();

    await userEvent.type(within(card).getByPlaceholderText('source slug'), 'fienta');
    expect(runButton).not.toBeDisabled();
  });

  describe('confirmation modal for a real run (issue #160)', () => {
    it.each([
      ['cleanup', 'Run Cleanup', /deletes rows from satellite tables/],
      ['send_digests', 'Run Send digests', /real email to every opted-in user/],
      ['pipeline_run', 'Run Run full pipeline', /full pipeline end to end/],
    ])('gates a real %s run behind danger copy naming its consequence', async (testId, runLabel, dangerCopy) => {
      mockAdminStream.mockResolvedValue(undefined);
      renderWithProviders(<AdminPipeline />);

      const card = screen.getByTestId(`trigger-card-${testId}`);
      await userEvent.click(within(card).getByRole('checkbox', { name: 'Dry run' }));
      await userEvent.click(within(card).getByRole('button', { name: runLabel }));

      expect(mockAdminStream).not.toHaveBeenCalled();
      expect(screen.getByText(dangerCopy)).toBeInTheDocument();
    });

    it('cancelling the confirmation never starts a run', async () => {
      mockAdminStream.mockResolvedValue(undefined);
      renderWithProviders(<AdminPipeline />);

      const card = screen.getByTestId('trigger-card-cleanup');
      await userEvent.click(within(card).getByRole('checkbox', { name: 'Dry run' }));
      await userEvent.click(within(card).getByRole('button', { name: 'Run Cleanup' }));

      await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
      expect(screen.queryByText(/deletes rows from satellite tables/)).not.toBeInTheDocument();
      expect(mockAdminStream).not.toHaveBeenCalled();
    });

    it('does not gate a dry run — only a real (dry_run=false) run needs confirmation', async () => {
      mockAdminStream.mockResolvedValue(undefined);
      renderWithProviders(<AdminPipeline />);

      const card = screen.getByTestId('trigger-card-cleanup');
      await userEvent.click(within(card).getByRole('button', { name: 'Run Cleanup' }));

      expect(screen.queryByText(/deletes rows from satellite tables/)).not.toBeInTheDocument();
      await waitFor(() => expect(mockAdminStream).toHaveBeenCalledWith(
        expect.stringContaining('dry_run=true'),
        expect.any(Function),
        expect.anything(),
      ));
    });

    it('"Run for real" after a completed dry run carries its numbers into the confirmation', async () => {
      mockAdminStream.mockImplementation((_path, onLine) => {
        onLine({ stage: 'cleanup', status: 'ok', result: { raw_events: 412, dry_run: true }, error: null });
        return Promise.resolve();
      });
      renderWithProviders(<AdminPipeline />);

      const card = screen.getByTestId('trigger-card-cleanup');
      await userEvent.click(within(card).getByRole('button', { name: 'Run Cleanup' }));
      expect(await within(card).findByText('done')).toBeInTheDocument();

      await userEvent.click(within(card).getByRole('button', { name: 'Run Cleanup for real' }));
      await userEvent.click(screen.getByRole('button', { name: 'I understand, continue' }));

      expect(within(screen.getByRole('dialog')).getByText(/"raw_events": 412/)).toBeInTheDocument();

      mockAdminStream.mockClear();
      mockAdminStream.mockResolvedValue(undefined);
      await userEvent.click(screen.getByRole('button', { name: 'Run for real' }));

      await waitFor(() => expect(mockAdminStream).toHaveBeenCalledWith(
        expect.stringContaining('dry_run=false'),
        expect.any(Function),
        expect.anything(),
      ));
    });

    it('does not resurrect "Run for real" after a real run completes', async () => {
      // Regression: startRealRun left the dry-run toggle on, so a completed
      // real run re-satisfied the "show Run for real" condition and
      // mislabeled its own numbers as a dry run's.
      mockAdminStream.mockImplementation((_path, onLine) => {
        onLine({ stage: 'cleanup', status: 'ok', result: { raw_events: 412, dry_run: true }, error: null });
        return Promise.resolve();
      });
      renderWithProviders(<AdminPipeline />);

      const card = screen.getByTestId('trigger-card-cleanup');
      await userEvent.click(within(card).getByRole('button', { name: 'Run Cleanup' }));
      expect(await within(card).findByText('done')).toBeInTheDocument();

      await userEvent.click(within(card).getByRole('button', { name: 'Run Cleanup for real' }));
      await userEvent.click(screen.getByRole('button', { name: 'I understand, continue' }));

      mockAdminStream.mockImplementation((_path, onLine) => {
        onLine({ stage: 'cleanup', status: 'ok', result: { raw_events: 412, dry_run: false }, error: null });
        return Promise.resolve();
      });
      await userEvent.click(screen.getByRole('button', { name: 'Run for real' }));
      await within(card).findByText('done');

      expect(within(card).queryByRole('button', { name: 'Run Cleanup for real' })).not.toBeInTheDocument();
    });
  });
});
