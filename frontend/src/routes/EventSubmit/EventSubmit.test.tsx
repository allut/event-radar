import { describe, it, expect, vi, beforeEach } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import EventSubmit from './EventSubmit';
import { renderWithProviders } from '../../test/utils';

vi.mock('../../lib/auth', () => ({
  getLocale: vi.fn(() => 'en'),
  setLocale: vi.fn(),
}));

vi.mock('../../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/client')>()),
  organizerApi: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import { organizerApi } from '../../api/client';
const mockGet = vi.mocked(organizerApi.get);
const mockPost = vi.mocked(organizerApi.post);
const mockPatch = vi.mocked(organizerApi.patch);

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockPatch.mockReset();
});

describe('EventSubmit (create)', () => {
  it('renders the create-mode title and required fields', () => {
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });
    expect(screen.getByText(/submit an event/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/title \(estonian\)/i)).toBeInTheDocument();
  });

  it('disables submit until title and start time are filled', () => {
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });
    expect(screen.getByRole('button', { name: /submit event/i })).toBeDisabled();
  });

  it('submits a POST to /organizer/events with the entered title', async () => {
    mockPost.mockResolvedValueOnce({ id: 5, slug: 'new-event', status: 'published' });
    renderWithProviders(<EventSubmit />, { route: '/organizer/submit', pathPattern: '/organizer/submit' });

    await userEvent.type(screen.getByLabelText(/title \(estonian\)/i), 'Jazz Night');
    const startsInput = screen.getByLabelText(/starts/i);
    await userEvent.type(startsInput, '2026-08-01T18:00');

    await waitFor(() => expect(screen.getByRole('button', { name: /submit event/i })).not.toBeDisabled());
    await userEvent.click(screen.getByRole('button', { name: /submit event/i }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledTimes(1));
    const [path, body] = mockPost.mock.calls[0];
    expect(path).toBe('/organizer/events');
    expect(body).toMatchObject({ title: 'Jazz Night' });
  });
});

describe('EventSubmit (edit)', () => {
  it('prefills from the organizer\'s event list and submits a PATCH', async () => {
    mockGet.mockResolvedValueOnce({
      events: [
        {
          id: 9,
          title: 'Existing Event',
          description: null,
          important_info: null,
          starts_at: '2026-08-01T18:00:00Z',
          ends_at: null,
          venue_name: null,
          venue_address: null,
          url: null,
          image_url: null,
          price_min: null,
          price_max: null,
          categories: [],
        },
      ],
      limit: 24,
      offset: 0,
    });
    mockPatch.mockResolvedValueOnce({ id: 9, slug: 'existing-event', status: 'published' });

    renderWithProviders(<EventSubmit />, {
      route: '/organizer/events/9/edit',
      pathPattern: '/organizer/events/:id/edit',
    });

    expect(await screen.findByDisplayValue('Existing Event')).toBeInTheDocument();
    expect(screen.getByText(/edit event/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /save changes/i }));
    await waitFor(() => expect(mockPatch).toHaveBeenCalledWith('/organizer/events/9', expect.objectContaining({ title: 'Existing Event' })));
  });
});
