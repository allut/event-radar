import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import ClaimEventPicker from './ClaimEventPicker';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn(), post: vi.fn() },
}));

import { ApiError, organizerApi } from '../../api/client';
import { CLAIM_JUSTIFICATION_REQUIRED_ERROR } from '../../constants/claims';
const mockGet = vi.mocked(organizerApi.get);
const mockPost = vi.mocked(organizerApi.post);

const candidate = { id: 42, title: 'Jazz Night', venue_name: 'Rock Hall', starts_at: '2026-08-01T18:00:00Z', image_url: null };

function mockClaimGet(suggestions: unknown = { events: [] }, search: unknown = { events: [] }) {
  mockGet.mockImplementation((path: string) =>
    Promise.resolve(path.includes('/search') ? search : suggestions),
  );
}

function renderPicker() {
  return renderWithProviders(null, {
    routes: [
      { path: '/', element: <ClaimEventPicker locale="en" /> },
      { path: '/organizer/claims/:id/pending', element: <div>pending-screen</div> },
    ],
  });
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
});

describe('ClaimEventPicker', () => {
  it('shows the suggestions list when the account has matches', async () => {
    mockClaimGet({ events: [candidate] });
    renderPicker();
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());
    expect(screen.getByText('Suggested for you')).toBeInTheDocument();
  });

  it('sends locale= on both the suggestions and search requests (#454)', async () => {
    mockClaimGet({ events: [candidate] }, { events: [candidate] });
    renderPicker();

    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());
    await userEvent.type(screen.getByRole('combobox'), 'jazz');
    await waitFor(() =>
      expect(mockGet).toHaveBeenCalledWith(expect.stringMatching(/\/search.*[?&]locale=en/)),
    );
    expect(mockGet).toHaveBeenCalledWith(expect.stringMatching(/\/suggestions.*[?&]locale=en/));
  });

  it('hides the suggestions section when there are none', async () => {
    mockClaimGet({ events: [] });
    renderPicker();
    await waitFor(() => expect(mockGet).toHaveBeenCalled());
    expect(screen.queryByText('Suggested for you')).not.toBeInTheDocument();
  });

  it('searches on typing and lands on the pending screen after claiming (#415)', async () => {
    mockClaimGet({ events: [] }, { events: [candidate] });
    mockPost.mockResolvedValueOnce({ id: 42, status: 'pending' });
    renderPicker();

    await userEvent.type(screen.getByRole('combobox'), 'jazz');
    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument(), { timeout: 2000 });

    await userEvent.click(screen.getByRole('button', { name: 'Claim this event' }));

    expect(mockPost).toHaveBeenCalledWith('/organizer/claims', { event_id: 42, justification: undefined });
    await waitFor(() => expect(screen.getByText('pending-screen')).toBeInTheDocument());
  });

  it('shows an inline error when claiming fails', async () => {
    mockClaimGet({ events: [candidate] });
    mockPost.mockRejectedValueOnce(new Error('network'));
    renderPicker();

    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Claim this event' }));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
  });

  it('reveals a justification field when the claim resolves to a series claim (#428), then resubmits with it', async () => {
    mockClaimGet({ events: [candidate] });
    mockPost
      .mockRejectedValueOnce(new ApiError(422, CLAIM_JUSTIFICATION_REQUIRED_ERROR))
      .mockResolvedValueOnce({ id: 42, status: 'pending' });
    renderPicker();

    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Claim this event' }));

    const textarea = await screen.findByPlaceholderText(/organize this recurring night/);
    const submitBtn = screen.getByRole('button', { name: 'Submit for review' });
    expect(submitBtn).toBeDisabled();

    await userEvent.type(textarea, 'I run this recurring night.');
    expect(submitBtn).toBeEnabled();
    await userEvent.click(submitBtn);

    expect(mockPost).toHaveBeenLastCalledWith('/organizer/claims', {
      event_id: 42,
      justification: 'I run this recurring night.',
    });
    await waitFor(() => expect(screen.getByText('pending-screen')).toBeInTheDocument());
  });

  it('closes the justification panel when a later attempt fails for an unrelated reason', async () => {
    mockClaimGet({ events: [candidate] });
    mockPost
      .mockRejectedValueOnce(new ApiError(422, CLAIM_JUSTIFICATION_REQUIRED_ERROR))
      .mockRejectedValueOnce(new Error('network'));
    renderPicker();

    await waitFor(() => expect(screen.getByText('Jazz Night')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Claim this event' }));
    const textarea = await screen.findByPlaceholderText(/organize this recurring night/);
    await userEvent.type(textarea, 'reason');
    await userEvent.click(screen.getByRole('button', { name: 'Submit for review' }));

    expect(await screen.findByRole('alert')).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/organize this recurring night/)).not.toBeInTheDocument();
  });
});
