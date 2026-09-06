import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminSubmissions from './AdminSubmissions';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  adminApi: { get: vi.fn(), post: vi.fn() },
}));

import { adminApi, ApiError } from '../../api/client';
const mockGet = vi.mocked(adminApi.get);
const mockPost = vi.mocked(adminApi.post);

const sampleSubmissions = {
  total: 2,
  events: [
    {
      id: 1,
      title: 'Tallinn Jazz Night',
      description: 'Live jazz trio in the museum courtyard.',
      venue_name: 'Fotografiska Tallinn',
      url: 'https://fotografiska.ee/events/jazz-night',
      categories: ['music'],
      status: 'published',
      submitted_by_organizer_id: 14,
      created_at: '2026-08-25T05:00:00Z',
    },
    {
      id: 2,
      title: 'Kalamaja Street Food Market',
      description: null,
      venue_name: 'Kalamaja',
      url: null,
      categories: [],
      status: 'published',
      submitted_by_organizer_id: 22,
      created_at: '2026-08-25T02:00:00Z',
    },
  ],
};

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

describe('AdminSubmissions', () => {
  it('lists pending submissions and shows the first item\'s full context in the detail panel', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    renderWithProviders(<AdminSubmissions />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());
    expect(screen.getByText('Kalamaja Street Food Market')).toBeInTheDocument();
    expect(screen.getByText('Organizer #14', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('Live jazz trio in the museum courtyard.')).toBeInTheDocument();
  });

  it('renders the description snippet as plain text, never as HTML markup (out of scope for #271)', async () => {
    mockGet.mockResolvedValueOnce({
      total: 1,
      events: [
        {
          ...sampleSubmissions.events[0],
          description: 'Doors at 8pm. <strong>Bring ID</strong> — 18+ only.',
        },
      ],
    });
    renderWithProviders(<AdminSubmissions />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());
    expect(screen.getByText(/Doors at 8pm\. <strong>Bring ID<\/strong> — 18\+ only\./)).toBeInTheDocument();
    expect(document.querySelector('strong')).not.toBeInTheDocument();
  });

  it('shows an empty state when there are no pending submissions', async () => {
    mockGet.mockResolvedValueOnce({ total: 0, events: [] });
    renderWithProviders(<AdminSubmissions />);
    await waitFor(() => expect(screen.getByText('No pending submissions.')).toBeInTheDocument());
  });

  it('switches the detail panel when a different row is selected', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    renderWithProviders(<AdminSubmissions />);
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());

    await userEvent.click(screen.getByRole('button', { name: /Kalamaja Street Food Market/ }));
    expect(screen.getByRole('heading', { name: 'Kalamaja Street Food Market' })).toBeInTheDocument();
    expect(screen.getByText('No description.')).toBeInTheDocument();
  });

  it('requires a note before approve/retract are enabled', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    renderWithProviders(<AdminSubmissions />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled());
    expect(screen.getByRole('button', { name: 'Retract' })).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/note/i), 'Looks good.');
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
  });

  it('approves a submission with the typed note, then keeps it in the list greyed out and tagged', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    mockPost.mockResolvedValueOnce({ id: 1, needs_review: false, note: 'Looks good.' });
    renderWithProviders(<AdminSubmissions />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/note/i), 'Looks good.');
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/admin/submissions/1/approve',
      { resolution_note: 'Looks good.' },
    ));
    expect(await screen.findByText(/Submission approved\./)).toBeInTheDocument();

    const list = screen.getAllByRole('button').filter((b) => within(b).queryByText('Tallinn Jazz Night'));
    expect(list[0]).toHaveTextContent('Approved');
  });

  it('retracts a submission with the typed note', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    mockPost.mockResolvedValueOnce({ id: 1, status: 'cancelled', note: 'Duplicate listing.' });
    renderWithProviders(<AdminSubmissions />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/note/i), 'Duplicate listing.');
    await userEvent.click(screen.getByRole('button', { name: 'Retract' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/admin/submissions/1/retract',
      { resolution_note: 'Duplicate listing.' },
    ));
    expect(await screen.findByText(/Submission retracted\./)).toBeInTheDocument();

    const list = screen.getAllByRole('button').filter((b) => within(b).queryByText('Tallinn Jazz Night'));
    expect(list[0]).toHaveTextContent('Retracted');
  });

  it('shows an error toast and leaves the submission actionable when approve fails', async () => {
    mockGet.mockResolvedValueOnce(sampleSubmissions);
    mockPost.mockRejectedValueOnce(new ApiError(429, 'Too many requests.'));
    renderWithProviders(<AdminSubmissions />);

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Tallinn Jazz Night' })).toBeInTheDocument());
    await userEvent.type(screen.getByLabelText(/note/i), 'Looks good.');
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));

    expect(await screen.findByText('Too many requests.')).toBeInTheDocument();
    expect(screen.queryByText(/Submission approved\./)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled();
  });
});
