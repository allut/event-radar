import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminReports from './AdminReports';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn() },
}));

import { adminApi, ApiError } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);
const mockPost = vi.mocked(adminApi.post);

const sampleReports = {
  total: 2,
  events: [
    {
      event_id: 1,
      title: 'MEEDIUM',
      status: 'published',
      venue: 'Von Krahli teater',
      submitted_by_organizer_id: null,
      report_count: 1,
      reasons: ['hateful_or_violent'],
      has_illegal_allegation: true,
      reports: [
        {
          reason: 'hateful_or_violent',
          detail: 'Contains language that may violate local law.',
          is_illegal_allegation: true,
          created_at: '2026-08-25T07:00:00Z',
        },
      ],
      oldest_open_report_at: '2026-08-25T07:00:00Z',
    },
    {
      event_id: 2,
      title: 'Öömaaeg',
      status: 'published',
      venue: 'Von Krahli teater',
      submitted_by_organizer_id: null,
      report_count: 2,
      reasons: ['spam_or_scam', 'misleading_info'],
      has_illegal_allegation: false,
      reports: [
        { reason: 'spam_or_scam', detail: null, is_illegal_allegation: false, created_at: '2026-08-24T10:00:00Z' },
        { reason: 'misleading_info', detail: 'Price mismatch.', is_illegal_allegation: false, created_at: '2026-08-23T10:00:00Z' },
      ],
      oldest_open_report_at: '2026-08-23T10:00:00Z',
    },
  ],
};

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

describe('AdminReports', () => {
  it('lists open reports and shows the first item\'s full context in the detail panel', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    renderWithProviders(<AdminReports />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    expect(screen.getByText('Öömaaeg')).toBeInTheDocument();
    expect(screen.getByText('Illegal content alleged')).toBeInTheDocument();
    expect(screen.getByText('Contains language that may violate local law.')).toBeInTheDocument();
  });

  it('shows an empty state when there are no open reports', async () => {
    mockGet.mockResolvedValueOnce({ total: 0, events: [] });
    renderWithProviders(<AdminReports />);
    await waitFor(() => expect(screen.getByText('No open reports.')).toBeInTheDocument());
  });

  it('switches the detail panel when a different row is selected', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    renderWithProviders(<AdminReports />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    expect(screen.queryByText('Price mismatch.')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /Öömaaeg/ }));
    expect(screen.getByRole('heading', { name: 'Öömaaeg' })).toBeInTheDocument();
    expect(screen.getByText('Price mismatch.')).toBeInTheDocument();
  });

  it('requires a note before resolve/takedown are enabled', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    renderWithProviders(<AdminReports />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Resolve' })).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Take down event' })).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Reviewed, all clear.');
    expect(screen.getByRole('button', { name: 'Resolve' })).toBeEnabled();
  });

  it('resolves a report with the typed note, then keeps it in the list greyed out and tagged', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    mockPost.mockResolvedValueOnce({ event_id: 1, resolved_count: 1 });
    renderWithProviders(<AdminReports />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Confirmed, edited the listing.');
    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/admin/reports/1/resolve',
      { resolution_note: 'Confirmed, edited the listing.' },
    ));
    expect(await screen.findByText(/Resolved\. Reporters notified\./)).toBeInTheDocument();

    const list = screen.getAllByRole('button').filter((b) => within(b).queryByText('MEEDIUM'));
    expect(list[0]).toHaveTextContent('Resolved');
  });

  it('takes an event down with the typed note', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    mockPost.mockResolvedValueOnce({ event_id: 1, status: 'cancelled', resolved_count: 1 });
    renderWithProviders(<AdminReports />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Illegal content confirmed, taken down.');
    await userEvent.click(screen.getByRole('button', { name: 'Take down event' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/admin/reports/1/takedown',
      { resolution_note: 'Illegal content confirmed, taken down.' },
    ));
    expect(await screen.findByText(/Event taken down\. Reporters notified\./)).toBeInTheDocument();
  });

  it('replaces the stale pre-takedown status once the event is actually taken down', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    mockPost.mockResolvedValueOnce({ event_id: 1, status: 'cancelled', resolved_count: 1 });
    renderWithProviders(<AdminReports />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    expect(screen.getByText(/status: published/)).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Illegal content confirmed, taken down.');
    await userEvent.click(screen.getByRole('button', { name: 'Take down event' }));

    await screen.findByText(/Event taken down\. Reporters notified\./);
    expect(screen.getByText(/status: cancelled/)).toBeInTheDocument();
    expect(screen.queryByText(/status: published/)).not.toBeInTheDocument();
  });

  it('shows an error toast and leaves the report actionable when resolve fails', async () => {
    mockGet.mockResolvedValueOnce(sampleReports);
    mockPost.mockRejectedValueOnce(new ApiError(429, 'Too many requests.'));
    renderWithProviders(<AdminReports />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'MEEDIUM' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/resolution note/i), 'Confirmed, edited the listing.');
    await userEvent.click(screen.getByRole('button', { name: 'Resolve' }));

    expect(await screen.findByText('Too many requests.')).toBeInTheDocument();
    expect(screen.queryByText(/Resolved\. Reporters notified\./)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Resolve' })).toBeEnabled();
  });
});
